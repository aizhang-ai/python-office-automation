#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单 / 表单自动处理与归档（零依赖版）
--------------------------------------
只使用 Python 标准库，不安装任何第三方包，不联网（除非你自己开启机器人推送）。

做什么：
  1. 读取 inbox/ 里所有 CSV 表单（订单、报名、询盘、售后单都行）
  2. 清洗字段（手机 / 邮箱 / 日期 / 金额）
  3. 校验必填项，缺字段的挑出来单独一张表
  4. 按你写的规则自动分派：分给谁、什么优先级、归到哪个文件夹
  5. 去重（同一手机号 + 同一产品只保留一条）
  6. 生成订单编号、归档到 archive/日期/分类.csv，原文件也备份一份
  7. 出一份当日处理报告（output/daily-report.txt）
  8. 可选：把摘要推到企业微信 / 飞书 / 钉钉群机器人

原文件永远不改动。

用法：
  python form_router.py            正常处理
  python form_router.py --init     生成一份配置模板 config.json
  python form_router.py --dry-run  只试跑，不写任何文件
"""

import csv
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "inbox_dir": "inbox",
    "output_dir": "output",
    "archive_dir": "archive",
    "log_dir": "logs",
    "encoding": "utf-8-sig",
    "id_prefix": "ORD",
    "required_fields": ["name", "phone", "amount"],
    "dedupe": {"enabled": True, "keys": ["phone", "product"], "keep": "last"},
    "archive_originals": True,
    "rules": [
        {
            "name": "大客户",
            "priority": "high",
            "owner": "负责人A",
            "match": [{"field": "amount", "op": "gte", "value": 10000}]
        },
        {
            "name": "华东区",
            "priority": "normal",
            "owner": "负责人B",
            "match": [{"field": "city", "op": "in", "value": ["上海", "杭州", "南京", "苏州"]}]
        },
        {
            "name": "待分配",
            "priority": "low",
            "owner": "客服组",
            "match": []
        }
    ],
    "notify": {"enabled": False, "type": "wecom", "webhook": ""}
}

# ---------------- 工具函数 ----------------

def log(msg, fh=None):
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line)
    if fh:
        try:
            fh.write(line + "\n")
        except Exception:
            pass


def to_number(v):
    """把 '1,200' / '¥1200' / ' 1200.50 ' 转成 float，失败返回 None"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace(",", "").replace("，", "")
    s = re.sub(r"[^\d.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def norm_phone(v):
    """138 0013 8000 / +86-138-0013-8000 -> 13800138000"""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def norm_email(v):
    if v is None:
        return ""
    return str(v).strip().lower().replace(" ", "")


def norm_date(v):
    """2026/9/1、2026.9.3、2026年9月2日、20260905 -> 2026-09-02"""
    if v is None:
        return str(v) if v is not None else ""
    s = str(v).strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    return s


def norm_amount(v):
    n = to_number(v)
    if n is None:
        return str(v).strip() if v is not None else ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return ("%.2f" % n)


def clean_value(col, val):
    """按列名含义做清洗"""
    c = (col or "").lower()
    s = "" if val is None else str(val)
    if any(k in c for k in ("phone", "mobile", "tel", "手机", "电话")):
        return norm_phone(s)
    if any(k in c for k in ("email", "mail", "邮箱")):
        return norm_email(s)
    if any(k in c for k in ("date", "time", "日期", "时间")):
        return norm_date(s)
    if any(k in c for k in ("amount", "money", "price", "金额", "价格", "总价", "付款")):
        return norm_amount(s)
    return re.sub(r"\s+", " ", s).strip()


def match_rule(row, rule):
    """规则内所有条件都满足才算命中；match 为空的规则 = 兜底"""
    conds = rule.get("match") or []
    if not conds:
        return True
    for cond in conds:
        field = cond.get("field", "")
        op = (cond.get("op") or "equals").lower()
        expect = cond.get("value")
        actual = row.get(field, "")
        try:
            if op in ("gt", "gte", "lt", "lte"):
                a = to_number(actual)
                b = to_number(expect)
                if a is None or b is None:
                    return False
                if op == "gt" and not a > b:
                    return False
                if op == "gte" and not a >= b:
                    return False
                if op == "lt" and not a < b:
                    return False
                if op == "lte" and not a <= b:
                    return False
            elif op == "equals":
                if str(actual).strip() != str(expect).strip():
                    return False
            elif op == "contains":
                if str(expect) not in str(actual):
                    return False
            elif op == "in":
                if str(actual).strip() not in [str(x).strip() for x in expect]:
                    return False
            elif op == "regex":
                if not re.search(str(expect), str(actual)):
                    return False
            elif op == "not_empty":
                if not str(actual).strip():
                    return False
            else:
                return False
        except Exception:
            return False
    return True


def read_csv_files(inbox, encoding):
    """读取 inbox 下所有 csv，返回 (rows, files, fieldnames)"""
    rows, files, fields = [], [], []
    if not os.path.isdir(inbox):
        return rows, files, fields
    for fn in sorted(os.listdir(inbox)):
        if not fn.lower().endswith(".csv"):
            continue
        path = os.path.join(inbox, fn)
        if not os.path.isfile(path):
            continue
        files.append(fn)
        for enc in (encoding, "utf-8-sig", "gbk", "utf-8"):
            try:
                with open(path, "r", encoding=enc, newline="") as f:
                    reader = csv.DictReader(f)
                    got = [h.strip() for h in (reader.fieldnames or [])]
                    for h in got:
                        if h and h not in fields:
                            fields.append(h)
                    for i, r in enumerate(reader, 1):
                        clean = {}
                        for k, v in r.items():
                            if k is None:
                                continue
                            clean[k.strip()] = v
                        if any((v or "").strip() for v in clean.values()):
                            clean["__source__"] = fn
                            clean["__row__"] = i
                            rows.append(clean)
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                log("读取 %s 失败：%s" % (fn, e))
                break
    return rows, files, fields


def send_notify(cfg, text):
    """推送到群机器人；失败只告警，不影响主流程"""
    n = cfg.get("notify") or {}
    if not n.get("enabled"):
        return False, "未开启"
    url = (n.get("webhook") or "").strip()
    if not url:
        return False, "未填写 webhook"
    import urllib.request
    kind = (n.get("type") or "wecom").lower()
    if kind == "wecom":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    else:
        payload = {"msgtype": "text", "text": {"content": text}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, "HTTP %s" % resp.status
    except Exception as e:
        return False, str(e)


# ---------------- 主流程 ----------------

def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args

    if "--init" in args:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print("已生成配置模板：%s" % CONFIG_FILE)
        return 0

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        log("未找到配置，已自动生成默认 config.json")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    enc = cfg.get("encoding", "utf-8-sig")
    inbox = os.path.join(BASE_DIR, cfg.get("inbox_dir", "inbox"))
    outdir = os.path.join(BASE_DIR, cfg.get("output_dir", "output"))
    arcdir = os.path.join(BASE_DIR, cfg.get("archive_dir", "archive"))
    logdir = os.path.join(BASE_DIR, cfg.get("log_dir", "logs"))

    if not dry:
        for d in (outdir, arcdir, logdir):
            os.makedirs(d, exist_ok=True)

    logfh = None
    if not dry:
        logfh = open(os.path.join(logdir, "run.log"), "a", encoding="utf-8")

    log("=== 订单/表单处理开始 ===", logfh)
    rows, files, fields = read_csv_files(inbox, enc)
    log("inbox 发现 %d 个 CSV 文件，共 %d 行" % (len(files), len(rows)), logfh)
    if not rows:
        log("没有可读到的数据，退出。", logfh)
        if logfh:
            logfh.close()
        return 1

    # 1. 清洗
    for r in rows:
        for k in list(r.keys()):
            if k in ("__source__", "__row__"):
                continue
            r[k] = clean_value(k, r.get(k, ""))
    log("清洗完成", logfh)

    # 2. 校验必填
    required = cfg.get("required_fields") or []
    good, bad = [], []
    for r in rows:
        missing = [f for f in required if not str(r.get(f, "")).strip()]
        if missing:
            r["__问题__"] = "缺少必填：" + "、".join(missing)
            bad.append(r)
        else:
            good.append(r)
    log("校验完成：有效 %d 行，异常 %d 行" % (len(good), len(bad)), logfh)

    # 3. 去重
    dd = cfg.get("dedupe") or {}
    dup_removed = 0
    if dd.get("enabled"):
        keys = dd.get("keys") or []
        keep = (dd.get("keep") or "last").lower()
        seen = {}
        ordered = []
        for r in good:
            sig = "|".join(str(r.get(k, "")).strip() for k in keys)
            if sig in seen:
                dup_removed += 1
                if keep == "last":
                    # 用位置替换，不用 list.index(dict)，避免两行完全相同时找错位置
                    ordered[seen[sig]] = r
            else:
                seen[sig] = len(ordered)
                ordered.append(r)
        good = ordered
    log("去重完成：去掉 %d 条重复" % dup_removed, logfh)

    # 4. 编号 + 分派
    today = datetime.now().strftime("%Y-%m-%d")
    stamp = datetime.now().strftime("%Y%m%d")
    prefix = cfg.get("id_prefix", "ORD")
    rules = cfg.get("rules") or [{"name": "待分配", "priority": "low", "owner": "客服组", "match": []}]
    for i, r in enumerate(good, 1):
        r["order_id"] = "%s-%s-%04d" % (prefix, stamp, i)
        r["process_date"] = today
        hit = None
        for rule in rules:
            if match_rule(r, rule):
                hit = rule
                break
        if hit is None:
            hit = {"name": "待分配", "priority": "low", "owner": "客服组"}
        r["__分类__"] = hit.get("name", "待分配")
        r["__负责人__"] = hit.get("owner", "")
        r["__优先级__"] = hit.get("priority", "normal")

    # 5. 写总表
    extra = ["order_id", "process_date", "__分类__", "__负责人__", "__优先级__", "__source__"]
    headers = [h for h in fields if h not in extra] + extra

    def write_csv(path, data, cols):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in data:
                w.writerow({c: r.get(c, "") for c in cols})

    report_lines = []
    total_amount = 0.0

    if not dry:
        write_csv(os.path.join(outdir, "orders-all.csv"), good, headers)

        # 6. 按分类归档
        cats = {}
        for r in good:
            cats.setdefault(r["__分类__"], []).append(r)
            total_amount += to_number(r.get("amount", "")) or 0.0
        day_dir = os.path.join(arcdir, today)
        os.makedirs(day_dir, exist_ok=True)
        for name, items in cats.items():
            safe = re.sub(r'[\\/:*?"<>|]', "_", name)
            write_csv(os.path.join(day_dir, safe + ".csv"), items, headers)
            report_lines.append("  %-8s %3d 条   负责人：%s   优先级：%s"
                                % (name, len(items),
                                   items[0].get("__负责人__", ""),
                                   items[0].get("__优先级__", "")))

        # 7. 异常表
        if bad:
            bh = [h for h in fields if h not in ("__问题__", "__source__")] + ["__问题__", "__source__"]
            write_csv(os.path.join(outdir, "异常待处理.csv"), bad, bh)

        # 8. 备份原文件
        if cfg.get("archive_originals", True):
            bak = os.path.join(day_dir, "原始文件")
            os.makedirs(bak, exist_ok=True)
            for fn in files:
                try:
                    shutil.copy2(os.path.join(inbox, fn), os.path.join(bak, fn))
                except Exception as e:
                    log("备份 %s 失败：%s" % (fn, e), logfh)
    else:
        cats = {}
        for r in good:
            cats.setdefault(r["__分类__"], []).append(r)
            total_amount += to_number(r.get("amount", "")) or 0.0
        for name, items in cats.items():
            report_lines.append("  %-8s %3d 条   负责人：%s   优先级：%s"
                                % (name, len(items),
                                   items[0].get("__负责人__", ""),
                                   items[0].get("__优先级__", "")))

    # 9. 报告
    prio_order = {"high": 0, "normal": 1, "low": 2}
    urgent = sorted([r for r in good if r.get("__优先级__") == "high"],
                    key=lambda r: -(to_number(r.get("amount", "")) or 0))
    report = []
    report.append("订单 / 表单处理报告")
    report.append("处理日期：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    report.append("试跑模式：%s" % ("是（未写入任何文件）" if dry else "否"))
    report.append("")
    report.append("源文件：%d 个 CSV（%s）" % (len(files), "、".join(files) if files else "无"))
    report.append("总行数：%d    有效：%d    异常：%d    重复已去掉：%d"
                  % (len(rows), len(good), len(bad), dup_removed))
    report.append("有效金额合计：%.2f" % total_amount)
    report.append("")
    report.append("分派结果：")
    report.extend(report_lines if report_lines else ["  （无）"])
    if urgent:
        report.append("")
        report.append("高优先级订单（按金额降序）：")
        for r in urgent[:10]:
            report.append("  %s  %s  %s  ¥%s  -> %s"
                          % (r.get("order_id", ""), r.get("name", ""),
                             r.get("product", ""), r.get("amount", ""),
                             r.get("__负责人__", "")))
    if bad:
        report.append("")
        report.append("异常待处理：%d 条，见 output/异常待处理.csv" % len(bad))
        for r in bad[:10]:
            report.append("  %s（第 %s 行）%s" % (r.get("__source__", ""), r.get("__row__", ""), r.get("__问题__", "")))
    report.append("")
    report.append("原文件未被修改。")

    report_text = "\n".join(report)
    if not dry:
        with open(os.path.join(outdir, "daily-report.txt"), "w", encoding="utf-8") as f:
            f.write(report_text + "\n")
    print()
    print(report_text)

    ok, detail = send_notify(cfg, report_text[:1800])
    log("群机器人推送：%s（%s）" % ("成功" if ok else "跳过/失败", detail), logfh)
    log("=== 处理结束 ===", logfh)
    if logfh:
        logfh.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("出错了：%s" % e)
        raise
