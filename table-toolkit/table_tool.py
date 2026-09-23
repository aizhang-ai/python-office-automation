#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格批量处理工具 —— 零依赖版

只用 Python 标准库，不需要 pip install，不需要 Excel 软件。
处理 CSV（Excel 可以直接打开和另存）。

能做的事：
  merge   把 input 文件夹里所有表格合并成一个
  clean   清洗字段：手机号、邮箱、日期、去空格、去空行
  dedupe  按指定列去重
  group   按某列分组统计（求和 / 计数）
  split   按某列的值拆成多个文件
  sort    按某列排序

用法：
    python table_tool.py                # 按 config.json 里的步骤执行
    python table_tool.py --init         # 生成一份配置模板和问题报告
    python table_tool.py --verbose      # 打印每个步骤的明细
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
REPORT_PATH = os.path.join(BASE_DIR, "run-report.txt")

DEFAULT_ENCODING = "utf-8-sig"

PHONE_RE = re.compile(r"^\d{11}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_PATTERNS = [
    ("%Y-%m-%d", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")),
    ("%Y/%m/%d", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("%Y.%m.%d", re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")),
    ("%Y年%m月%d日", re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$")),
    ("%Y%m%d", re.compile(r"^\d{8}$")),
]


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg))


# ---------------------------------------------------------------- 读写

def read_csv(path, encoding):
    with open(path, "r", encoding=encoding, errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or []
    return rows, fields


def write_csv(path, rows, fields, encoding):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


# ---------------------------------------------------------------- 清洗

def clean_value(col, value):
    """返回 (清洗后的值, 是否有效)。列名决定用哪套规则。"""
    if value is None:
        return "", True
    v = str(value).strip()
    name = col.lower()

    if any(k in name for k in ("phone", "mobile", "tel", "手机", "电话")):
        digits = re.sub(r"\D", "", v)
        if not digits:
            return "", True
        return digits, bool(PHONE_RE.match(digits))

    if any(k in name for k in ("email", "mail", "邮箱")):
        v2 = v.replace(" ", "").lower()
        if not v2:
            return "", True
        return v2, bool(EMAIL_RE.match(v2))

    if any(k in name for k in ("amount", "money", "price", "fee", "total", "金额", "价格", "总额")):
        v2 = v.replace(",", "").replace("¥", "").replace("￥", "").replace("$", "").replace(" ", "")
        if v2 == "":
            return "", True
        try:
            f = float(v2)
            return str(int(f)) if f.is_integer() else str(round(f, 2)), True
        except ValueError:
            return v, False

    if any(k in name for k in ("date", "time", "日期", "时间")):
        v2 = v.replace(" ", "")
        for fmt, pat in DATE_PATTERNS:
            if pat.match(v2):
                try:
                    return datetime.strptime(v2, fmt).strftime("%Y-%m-%d"), True
                except ValueError:
                    return v, False
        return v, (v2 == "")

    return re.sub(r"\s+", " ", v), True


def step_clean(rows, fields, cfg, verbose):
    cols = cfg.get("columns") or fields
    targets = [c for c in fields if c in cols]
    invalid = defaultdict(int)
    for r in rows:
        for c in targets:
            new_v, ok = clean_value(c, r.get(c))
            r[c] = new_v
            if not ok:
                invalid[c] += 1
    if invalid and verbose:
        log("清洗后发现格式异常：%s" % dict(invalid))
    return rows, fields, "清洗 %d 个字段，异常值 %d 个" % (len(targets), sum(invalid.values()))


# ---------------------------------------------------------------- 各步骤

def step_merge(rows, fields, cfg, encoding, verbose):
    input_dir = os.path.join(BASE_DIR, cfg.get("input_dir", "input"))
    pattern = cfg.get("pattern", "*.csv")
    files = sorted(glob.glob(os.path.join(input_dir, pattern)))
    if not files:
        return rows, fields, "合并失败：%s 里没有匹配 %s 的文件" % (input_dir, pattern)

    merged, all_fields = [], []
    for p in files:
        r, f = read_csv(p, encoding)
        for col in f:
            if col not in all_fields:
                all_fields.append(col)
        for row in r:
            row["__source__"] = os.path.basename(p)
        merged.extend(r)
        if verbose:
            log("读入 %s（%d 行）" % (os.path.basename(p), len(r)))
    if "__source__" not in all_fields:
        all_fields.append("__source__")
    return merged, all_fields, "合并 %d 个文件，共 %d 行，%d 列" % (len(files), len(merged), len(all_fields))


def step_dedupe(rows, fields, cfg, verbose):
    key = cfg.get("key") or cfg.get("by")
    if not key or key not in fields:
        return rows, fields, "去重跳过：找不到列 %s" % key
    keep = cfg.get("keep", "first")
    seen, out, removed = set(), [], 0
    for r in rows:
        k = (r.get(key) or "").strip()
        if k and k in seen:
            removed += 1
            continue
        if k:
            seen.add(k)
        out.append(r)
    if keep == "last":
        out, seen, removed = [], set(), 0
        for r in reversed(rows):
            k = (r.get(key) or "").strip()
            if k and k in seen:
                removed += 1
                continue
            if k:
                seen.add(k)
            out.append(r)
        out.reverse()
    return out, fields, "按「%s」去重，去掉 %d 行，剩 %d 行" % (key, removed, len(out))


def step_group(rows, fields, cfg, out_dir, encoding, verbose):
    """分组统计结果单独存文件，不改变主数据集（后面还能继续处理明细）。"""
    by = cfg.get("by")
    if not by or by not in fields:
        return rows, fields, "分组跳过：找不到列 %s" % by
    sums = cfg.get("sum") or []
    counts = cfg.get("count") or []
    agg = OrderedDict()
    for r in rows:
        k = (r.get(by) or "").strip() or "(空)"
        if k not in agg:
            agg[k] = {"n": 0}
            for s in sums:
                agg[k][s] = 0.0
            for c in counts:
                agg[k][c] = 0
        agg[k]["n"] += 1
        for s in sums:
            try:
                agg[k][s] += float(str(r.get(s) or "0").replace(",", "").replace("¥", "").replace("$", "") or 0)
            except ValueError:
                pass
        for c in counts:
            if (r.get(c) or "").strip():
                agg[k][c] += 1

    out_fields = [by, "行数"] + ["%s_合计" % s for s in sums] + ["%s_非空数" % c for c in counts]
    out = []
    for k, v in agg.items():
        row = {by: k, "行数": v["n"]}
        for s in sums:
            val = v[s]
            row["%s_合计" % s] = int(val) if float(val).is_integer() else round(val, 2)
        for c in counts:
            row["%s_非空数" % c] = v[c]
        out.append(row)

    fname = cfg.get("output") or ("group_by_%s.csv" % by)
    write_csv(os.path.join(out_dir, fname), out, out_fields, encoding)
    return rows, fields, "按「%s」分组，得到 %d 组，已存为 %s（明细数据保持不变）" % (by, len(out), fname)


def step_sort(rows, fields, cfg, verbose):
    by = cfg.get("by")
    if not by or by not in fields:
        return rows, fields, "排序跳过：找不到列 %s" % by
    desc = str(cfg.get("order", "asc")).lower() in ("desc", "down", "倒序", "降序")

    def key(r):
        v = (r.get(by) or "").strip()
        try:
            return (0, float(v.replace(",", "")))
        except ValueError:
            return (1, v)

    out = sorted(rows, key=key, reverse=desc)
    return out, fields, "按「%s」%s排序" % (by, "降序" if desc else "升序")


def step_split(rows, fields, cfg, encoding, out_dir, verbose):
    by = cfg.get("by")
    if not by or by not in fields:
        return rows, fields, "拆分跳过：找不到列 %s" % by
    sub = cfg.get("output_dir") or ("by_" + by)
    target = os.path.join(out_dir, sub)
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r.get(by) or "").strip() or "(空)"].append(r)
    for k, v in buckets.items():
        safe = re.sub(r'[\\/:*?"<>|]', "_", k)
        write_csv(os.path.join(target, "%s.csv" % safe), v, fields, encoding)
    return rows, fields, "按「%s」拆成 %d 个文件，放在 %s" % (by, len(buckets), target)


# ---------------------------------------------------------------- 主流程

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit("找不到 config.json。先执行 python table_tool.py --init 生成模板，再按 README 填写。")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_init_config():
    if os.path.exists(CONFIG_PATH):
        print("config.json 已存在，不覆盖。")
        return
    cfg = {
        "input_dir": "input",
        "output_dir": "output",
        "encoding": "utf-8-sig",
        "steps": [
            {"action": "merge", "pattern": "*.csv"},
            {"action": "clean", "columns": []},
            {"action": "dedupe", "key": "phone", "keep": "first"},
            {"action": "sort", "by": "date", "order": "desc"},
            {"action": "group", "by": "city", "sum": ["amount"], "count": ["order_id"], "output": "summary.csv"},
            {"action": "split", "by": "city", "output_dir": "by_city"},
            {"action": "save", "output": "result.csv"},
        ],
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("已生成 config.json，按 README 修改后运行 python table_tool.py")


def main():
    ap = argparse.ArgumentParser(description="表格批量处理工具（零依赖）")
    ap.add_argument("--init", action="store_true", help="生成配置模板")
    ap.add_argument("--verbose", action="store_true", help="打印明细")
    args = ap.parse_args()

    if args.init:
        write_init_config()
        return

    cfg = load_config()
    encoding = cfg.get("encoding", DEFAULT_ENCODING)
    out_dir = os.path.join(BASE_DIR, cfg.get("output_dir", "output"))
    os.makedirs(out_dir, exist_ok=True)

    rows, fields = [], []
    lines = ["表格处理报告 %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""]

    for i, step in enumerate(cfg.get("steps", []), 1):
        action = (step.get("action") or "").lower()
        note = ""
        if action == "merge":
            rows, fields, note = step_merge(rows, fields, step, encoding, args.verbose)
        elif action == "clean":
            rows, fields, note = step_clean(rows, fields, step, args.verbose)
        elif action == "dedupe":
            rows, fields, note = step_dedupe(rows, fields, step, args.verbose)
        elif action == "group":
            rows, fields, note = step_group(rows, fields, step, out_dir, encoding, args.verbose)
        elif action == "sort":
            rows, fields, note = step_sort(rows, fields, step, args.verbose)
        elif action == "split":
            rows, fields, note = step_split(rows, fields, step, encoding, out_dir, args.verbose)
        elif action == "save":
            out = step.get("output", "result.csv")
            n = write_csv(os.path.join(out_dir, out), rows, fields, encoding)
            note = "已保存 %s（%d 行）" % (out, n)
        else:
            note = "未知步骤 %s，已跳过" % action
        log("步骤 %d %s：%s" % (i, action, note))
        lines.append("%d. %s —— %s" % (i, action, note))

    if rows and not any((s.get("action") or "").lower() == "save" for s in cfg.get("steps", [])):
        n = write_csv(os.path.join(out_dir, "result.csv"), rows, fields, encoding)
        lines.append("（未配置 save 步骤，默认已保存 result.csv，%d 行）" % n)

    lines.append("")
    lines.append("输出目录：%s" % out_dir)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("")
    print("\n".join(lines))
    print("")
    print("报告已写入：%s" % REPORT_PATH)


if __name__ == "__main__":
    main()
