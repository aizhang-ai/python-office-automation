#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
shop_diff.py —— 多店铺商品信息核对与差异报告

只依赖 Python 标准库，不用 pip 装任何东西。双击 run.bat 就能跑。

做什么：
  1. 读两个（或多个）店铺导出的商品表 CSV
  2. 按 SKU / 商品编码对齐，逐字段比对价格、库存、标题、上下架状态
  3. 输出四类结果：价格不一致、库存不一致、其他字段不一致、只在一家有的 SKU
  4. 表头名字不一样没关系，config 里配一下别名映射就能对上
  5. 差异超过阈值时，可选推送到企业微信 / 钉钉 / 飞书群机器人（官方 Webhook，默认关闭）

不做什么：
  - 不改你的原始文件，所有结果写到 output/
  - 不联网抓取任何平台数据，只读你自己导出的文件

用法：
  python shop_diff.py                   按 config.json 跑一次
  python shop_diff.py --top 20          报告里价格差异 TOP 显示 20 条（默认 10）
  python shop_diff.py --no-alert        本轮不推送
  python shop_diff.py --config D:\my\cfg.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(BASE_DIR, "config.json")
OUT_DIR = os.path.join(BASE_DIR, "output")

CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShopDiff/1.0 (python-stdlib)"

# 常见编码，按概率排
ENCODINGS = ["utf-8-sig", "gb18030", "utf-8", "big5"]


# ---------------------------------------------------------------- 基础工具

def now():
    return datetime.now(CST)


def stamp():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print("[%s] %s" % (now().strftime("%H:%M:%S"), msg))


def ensure_out(out_dir):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)


def load_config(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    cfg.setdefault("stores", [])
    cfg.setdefault("key", "sku")
    cfg.setdefault("compare_fields", ["price", "stock", "title", "status"])
    cfg.setdefault("numeric_fields", ["price", "stock"])
    cfg.setdefault("tolerance", 0.01)
    cfg.setdefault("trim", True)
    cfg.setdefault("ignore_case", False)
    cfg.setdefault("mode", "baseline")
    cfg.setdefault("top_n", 10)
    cfg.setdefault("max_alert_diff", 1)
    cfg.setdefault("column_alias", {})
    cfg.setdefault("alert", {"enabled": False, "type": "none", "webhook": ""})
    return cfg


def read_text(path):
    """按常见编码依次尝试，全失败则报错。"""
    raw = open(path, "rb").read()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "unknown(replace)"


def read_table(path, cfg):
    """读一份商品表，返回 {'rows','header','skipped','dups','encoding','path'}"""
    text, enc = read_text(path)
    alias = cfg.get("column_alias") or {}
    trim = bool(cfg.get("trim", True))
    key = cfg.get("key", "sku")

    f = io.StringIO(text)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        dialect = csv.excel
    reader = csv.reader(f, dialect)
    raw_rows = [r for r in reader if any(str(c).strip() for c in r)]
    if not raw_rows:
        return {"rows": [], "header": [], "skipped": [], "dups": [], "encoding": enc, "path": path, "empty": True}

    header = [str(c).strip() for c in raw_rows[0]]
    header = [alias.get(h, h) for h in header]
    rows = []
    skipped = []
    for i, r in enumerate(raw_rows[1:], start=2):
        rec = {}
        for j, h in enumerate(header):
            rec[h] = r[j] if j < len(r) else ""
        if trim:
            rec = {k: str(v).strip() for k, v in rec.items()}
        if not rec.get(key):
            skipped.append((i, "缺主键「%s」" % key))
            continue
        rows.append(rec)

    dups = []
    seen = {}
    uniq = []
    for rec in rows:
        k = rec[key]
        if k in seen:
            dups.append((k, "第 %d 行与前面重复，已取第一条" % (seen[k])))
            continue
        seen[k] = len(uniq) + 1
        uniq.append(rec)

    return {"rows": uniq, "header": header, "skipped": skipped, "dups": dups,
            "encoding": enc, "path": path, "empty": False}


# ---------------------------------------------------------------- 值归一化

_NUM_RE = re.compile(r"[^0-9eE+\-.]")


def norm_num(v):
    """把 ¥1,200.50 / 1 200.50 / (380) / 99元 / 12.5% 之类解析成 float，失败返回 None。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace("¥", "").replace("￥", "").replace("$", "")
    s = s.replace(",", "").replace("，", "").replace(" ", "").replace("\u00a0", "")
    s = s.replace("元", "").replace("件", "").replace("个", "")
    if s in ("", "-", "--", "—", "N/A", "null", "None"):
        return None
    if s.startswith("-"):
        neg, s = True, s[1:]
    s = _NUM_RE.sub("", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def norm_text(v, ignore_case):
    s = "" if v is None else str(v)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower() if ignore_case else s


def fmt_num(n):
    if n is None:
        return "-"
    if abs(n - round(n)) < 1e-9:
        return "{:,}".format(int(round(n)))
    return "{:,.2f}".format(n)


def fmt_money(n):
    if n is None:
        return "-"
    return "¥" + ("{:,.0f}".format(n) if abs(n - round(n)) < 1e-9 else "{:,.2f}".format(n))


# ---------------------------------------------------------------- 比对

def build_map(table, key, ignore_case):
    m = {}
    for rec in table["rows"]:
        k = rec.get(key)
        if k is None:
            continue
        k = str(k).strip()
        m[k.lower() if ignore_case else k] = rec
    return m


def compare_pair(base, other, cfg):
    """比对一对店铺，返回结构化差异。"""
    key = cfg.get("key", "sku")
    fields = cfg.get("compare_fields") or []
    numeric = set(cfg.get("numeric_fields") or [])
    tol = float(cfg.get("tolerance", 0.01))
    ic = bool(cfg.get("ignore_case", False))

    bmap = build_map(base, key, ic)
    omap = build_map(other, key, ic)

    bkeys = set(bmap.keys())
    okeys = set(omap.keys())
    common = sorted(bkeys & okeys)
    only_base = sorted(bkeys - okeys)
    only_other = sorted(okeys - bkeys)

    diffs = []
    for k in common:
        b = bmap[k]
        o = omap[k]
        for f in fields:
            if f not in b and f not in o:
                continue
            bv = b.get(f, "")
            ov = o.get(f, "")
            if f in numeric:
                bn, on = norm_num(bv), norm_num(ov)
                if bn is None and on is None:
                    continue
                if bn is None or on is None:
                    diffs.append({"sku": k, "field": f, "kind": "缺值",
                                  "base": bv, "other": ov, "delta": None, "pct": None})
                elif abs(bn - on) > tol + 1e-12:
                    pct = None
                    if bn:
                        pct = (on - bn) / abs(bn) * 100.0
                    diffs.append({"sku": k, "field": f, "kind": "数值不一致",
                                  "base": bv, "other": ov, "delta": on - bn, "pct": pct})
            else:
                if norm_text(bv, ic) != norm_text(ov, ic):
                    diffs.append({"sku": k, "field": f, "kind": "文本不一致",
                                  "base": bv, "other": ov, "delta": None, "pct": None})

    by_field = {}
    for d in diffs:
        by_field.setdefault(d["field"], []).append(d)

    return {
        "base_name": base.get("name", os.path.basename(base["path"])),
        "other_name": other.get("name", os.path.basename(other["path"])),
        "base_count": len(bkeys),
        "other_count": len(okeys),
        "common": len(common),
        "only_base": only_base,
        "only_other": only_other,
        "diffs": diffs,
        "by_field": by_field,
        "bmap": bmap,
        "omap": omap,
    }


def price_top(res, key_field, n):
    items = []
    for d in res["diffs"]:
        if d["field"] != key_field or d["delta"] is None:
            continue
        items.append(d)
    items.sort(key=lambda x: -abs(x["delta"] or 0))
    return items[:n]


# ---------------------------------------------------------------- 输出

def write_csv(path, header, rows):
    ensure_out(os.path.dirname(path))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return path


def build_report(results, cfg, tables, out_dir):
    key = cfg.get("key", "sku")
    top_n = int(cfg.get("top_n", 10))
    L = []
    L.append("多店铺商品信息核对报告  %s" % stamp())
    L.append("对齐主键：%s    比对字段：%s" % (key, "、".join(cfg.get("compare_fields") or [])))
    L.append("=" * 64)

    for res in results:
        L.append("")
        L.append("【%s】 vs 【%s】" % (res["base_name"], res["other_name"]))
        L.append("-" * 64)
        L.append("一、规模   基准 %d 个 / 比对方 %d 个 / 共有 %d 个"
                 % (res["base_count"], res["other_count"], res["common"]))
        rate = (len({d["sku"] for d in res["diffs"]}) / res["common"] * 100.0) if res["common"] else 0.0
        L.append("二、差异   有差异的 SKU %d 个（占共有 %.1f%%），共 %d 处"
                 % (len({d["sku"] for d in res["diffs"]}), rate, len(res["diffs"])))
        if res["by_field"]:
            for f in (cfg.get("compare_fields") or []):
                if f in res["by_field"]:
                    L.append("           %s 不一致 %d 处" % (f, len(res["by_field"][f])))

        tops = price_top(res, "price", top_n)
        if tops:
            L.append("三、价格差异 TOP %d" % len(tops))
            for d in tops:
                pct = ("  (%+.1f%%)" % d["pct"]) if d["pct"] is not None else ""
                L.append("           %s   %s -> %s   差 %+.2f%s"
                         % (d["sku"], fmt_money(norm_num(d["base"])), fmt_money(norm_num(d["other"])),
                            d["delta"], pct))

        if res["only_base"]:
            L.append("四、只在【%s】有（%d 个）—— 对方疑似未上架或编码不一致"
                     % (res["base_name"], len(res["only_base"])))
            for k in res["only_base"][:top_n]:
                t = res["bmap"][k].get("title", "")
                L.append("           %s  %s" % (k, t))
            if len(res["only_base"]) > top_n:
                L.append("           …… 其余 %d 个见 diff-detail.csv" % (len(res["only_base"]) - top_n))

        if res["only_other"]:
            L.append("五、只在【%s】有（%d 个）—— 基准方疑似漏了或已下架"
                     % (res["other_name"], len(res["only_other"])))
            for k in res["only_other"][:top_n]:
                t = res["omap"][k].get("title", "")
                L.append("           %s  %s" % (k, t))
            if len(res["only_other"]) > top_n:
                L.append("           …… 其余 %d 个见 diff-detail.csv" % (len(res["only_other"]) - top_n))

    L.append("")
    L.append("=" * 64)
    L.append("六、数据质量（读文件时发现的）")
    any_bad = False
    for t in tables:
        name = t.get("name", os.path.basename(t["path"]))
        if t.get("empty"):
            L.append("   %s：文件是空的或没有数据行" % name)
            any_bad = True
            continue
        if t["skipped"]:
            L.append("   %s：跳过 %d 行（缺主键）" % (name, len(t["skipped"])))
            any_bad = True
        if t["dups"]:
            L.append("   %s：主键重复 %d 个，已取第一条（说明：%s）"
                     % (name, len(t["dups"]), t["dups"][0][1]))
            any_bad = True
    if not any_bad:
        L.append("   无。所有行主键完整、无重复。")
    L.append("")
    L.append("明细已写入 output/diff-detail.csv，汇总见 output/summary.csv")

    text = "\n".join(L)
    path = os.path.join(out_dir, "latest-report.txt")
    ensure_out(out_dir)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path, text


def write_details(results, cfg, out_dir):
    rows = []
    for res in results:
        for d in res["diffs"]:
            rows.append([
                res["base_name"], res["other_name"], d["sku"], d["field"], d["kind"],
                d["base"], d["other"],
                "" if d["delta"] is None else round(d["delta"], 4),
                "" if d["pct"] is None else round(d["pct"], 2),
            ])
        for k in res["only_base"]:
            rows.append([res["base_name"], res["other_name"], k, "（整条）", "仅基准方有",
                         res["bmap"][k].get("title", ""), "", "", ""])
        for k in res["only_other"]:
            rows.append([res["base_name"], res["other_name"], k, "（整条）", "仅比对方有",
                         "", res["omap"][k].get("title", ""), "", ""])
    return write_csv(os.path.join(out_dir, "diff-detail.csv"),
                     ["基准方", "比对方", cfg.get("key", "sku"), "字段", "类型",
                      "基准方值", "比对方值", "差值", "幅度%"], rows)


def write_summary(results, cfg, out_dir):
    rows = []
    for res in results:
        rows.append([
            res["base_name"], res["other_name"], res["base_count"], res["other_count"],
            res["common"], len(res["only_base"]), len(res["only_other"]),
            len({d["sku"] for d in res["diffs"]}), len(res["diffs"]),
        ] + [len(res["by_field"].get(f, [])) for f in (cfg.get("compare_fields") or [])])
    return write_csv(os.path.join(out_dir, "summary.csv"),
                     ["基准方", "比对方", "基准数", "比对数", "共有", "仅基准有", "仅比对有",
                      "有差异SKU", "差异处数"] + ["差异_" + f for f in (cfg.get("compare_fields") or [])], rows)


# ---------------------------------------------------------------- 告警

def send_webhook(alert_cfg, text):
    if not alert_cfg.get("enabled"):
        return False, "推送未开启"
    url = (alert_cfg.get("webhook") or "").strip()
    typ = (alert_cfg.get("type") or "none").lower()
    if not url or typ in ("none", ""):
        return False, "未配置 webhook 地址"

    if typ in ("wecom", "weixin", "qywx", "企业微信"):
        payload = {"msgtype": "text", "text": {"content": text}}
    elif typ in ("dingtalk", "ding", "钉钉"):
        payload = {"msgtype": "text", "text": {"content": text}}
    elif typ in ("feishu", "lark", "飞书"):
        payload = {"msg_type": "text", "content": {"text": text}}
    else:
        return False, "不支持的推送类型：%s" % typ

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read(2048)
        return True, "已推送"
    except urllib.error.HTTPError as e:
        return False, "推送失败 HTTP %s" % getattr(e, "code", "?")
    except Exception as e:
        return False, "推送失败：%s" % e


# ---------------------------------------------------------------- 主流程

def main(argv=None):
    ap = argparse.ArgumentParser(description="多店铺商品信息核对与差异报告（纯标准库）")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--out", default=OUT_DIR, help="输出目录，默认 output/")
    ap.add_argument("--top", type=int, default=0, help="报告里 TOP 显示几条，默认取配置 top_n")
    ap.add_argument("--no-alert", action="store_true", help="本轮不推送")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.config):
        print("找不到配置文件：%s" % args.config)
        print("把 config.example.json 复制成 config.json，再填你的文件路径。")
        return 2
    try:
        cfg = load_config(args.config)
    except json.JSONDecodeError as e:
        print("config.json 不是合法 JSON：%s（第 %s 行第 %s 列）" % (e.msg, e.lineno, e.colno))
        return 2

    if args.top:
        cfg["top_n"] = args.top

    stores = cfg.get("stores") or []
    if len(stores) < 2:
        print("config.json 的 stores 至少要配 2 份表。")
        return 2

    tables = []
    for s in stores:
        path = s.get("file", "")
        if not os.path.isabs(path):
            path = os.path.join(BASE_DIR, path)
        if not os.path.isfile(path):
            print("找不到文件：%s" % path)
            return 2
        log("读取 %s ..." % path)
        t = read_table(path, cfg)
        t["name"] = s.get("name") or os.path.basename(path)
        tables.append(t)
        log("  %d 行，编码 %s" % (len(t["rows"]), t["encoding"]))

    mode = str(cfg.get("mode", "baseline")).lower()
    results = []
    if mode == "all_pairs":
        for i in range(len(tables)):
            for j in range(i + 1, len(tables)):
                results.append(compare_pair(tables[i], tables[j], cfg))
    else:
        for j in range(1, len(tables)):
            results.append(compare_pair(tables[0], tables[j], cfg))

    ensure_out(args.out)
    detail = write_details(results, cfg, args.out)
    summary = write_summary(results, cfg, args.out)
    report, text = build_report(results, cfg, tables, args.out)

    total_diff = sum(len(r["diffs"]) for r in results)
    print("")
    print(text)
    print("")
    print("报告：%s" % report)
    print("明细：%s" % detail)
    print("汇总：%s" % summary)

    alert_note = "未开启推送"
    thr = int(cfg.get("max_alert_diff", 1))
    if total_diff >= thr and not args.no_alert:
        lines = ["多店铺核对 %s" % stamp()]
        for r in results:
            lines.append("· %s vs %s：差异 %d 处，仅基准有 %d，仅比对有 %d"
                         % (r["base_name"], r["other_name"], len(r["diffs"]),
                            len(r["only_base"]), len(r["only_other"])))
        ok, note = send_webhook(cfg.get("alert", {}), "\n".join(lines))
        alert_note = note
    elif total_diff < thr:
        alert_note = "差异 %d 处未达阈值 %d，不告警" % (total_diff, thr)
    else:
        alert_note = "本轮 --no-alert，未推送"
    print("告警：%s" % alert_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
