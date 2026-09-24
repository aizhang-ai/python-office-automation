#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每日经营数据简报机器人 v1
------------------------------------------
做什么：读本地的 CSV 经营数据（订单/销售/门店流水都行），
        自动算出当天核心指标、环比、分组构成、TOP 榜、异常告警，
        生成一份「可以直接粘贴到群里」的日报文本 + Markdown 报告 + 汇总 CSV，
        可选推送到企业微信/钉钉/飞书群机器人（官方 Webhook，需你自己填地址，默认关闭）。

不做什么：不读数据库、不登录任何系统、不抓取网页、不自动改你的原始数据。
          原始数据全程只读，输出一律写到 output 目录。

运行环境：Windows / macOS / Linux + Python 3.8 以上，纯标准库，零 pip 安装。

用法：
    python daily_brief.py                 # 正常跑，写 output/
    python daily_brief.py --dry-run        # 只算不写文件，打印到屏幕
    python daily_brief.py --date 2026-09-24        # 指定"今天"是哪天
    python daily_brief.py --push           # 顺便推到 config.json 里填的群机器人
    python daily_brief.py --config my.json # 用另一份配置
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config.json")
EXAMPLE_CONFIG = os.path.join(HERE, "config.example.json")


# ---------------------------------------------------------------- 基础工具

def log(msg):
    ts = time.strftime("%H:%M:%S")
    try:
        print("[%s] %s" % (ts, msg), flush=True)
    except UnicodeEncodeError:
        print("[%s] %s" % (ts, msg.encode("gbk", "replace").decode("gbk")), flush=True)


def read_text(path):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def to_number(raw):
    """把 '1,200.50'、'¥1,200'、' 1200 '、'(300)' 之类转成 float；转不了返回 None。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace("¥", "").replace("￥", "").replace("$", "")
    s = s.replace(",", "").replace("，", "").replace(" ", "")
    s = s.replace("%", "")
    if s in ("", "-", "--", "nan", "None", "null"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


DATE_PATTERNS = [
    ("%Y-%m-%d", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")),
    ("%Y/%m/%d", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("%Y.%m.%d", re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")),
    ("%Y%m%d", re.compile(r"^\d{8}$")),
    ("%Y年%m月%d日", re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$")),
]


def parse_date(raw):
    """支持 2026-09-24 / 2026/9/24 / 2026.9.24 / 20260924 / 2026年9月24日 / Excel 序列号。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    s = s.split(" ")[0].split("T")[0]
    for fmt, pat in DATE_PATTERNS:
        if pat.match(s):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                return None
    if re.match(r"^\d{5}$", s):  # Excel 日期序列号
        try:
            return (datetime(1899, 12, 30) + timedelta(days=int(s))).date()
        except Exception:
            return None
    return None


def fmt_money(v):
    if v is None:
        return "-"
    return "{:,.2f}".format(v)


def fmt_pct(v):
    if v is None:
        return "-"
    return "{:+.1f}%".format(v)


def pct_change(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev) * 100.0


def bar(v, maxv, width=20):
    if not maxv:
        return ""
    n = int(round(v / maxv * width))
    return "#" * max(1, n) if v > 0 else ""


# ---------------------------------------------------------------- 配置

DEFAULT_CFG = {
    "input_dir": "input",
    "output_dir": "output",
    "file_pattern": "*.csv",
    "recursive": True,
    "encoding": "auto",
    "date_field": "date",
    "amount_field": "amount",
    "group_fields": ["city"],
    "top_field": "order_id",
    "top_n": 5,
    "compare_mode": "previous_day",
    "alerts": {
        "drop_pct": 20,
        "rise_pct": 50,
        "min_amount": 0,
        "min_orders": 0
    },
    "history_file": "history.csv",
    "webhook": {
        "enabled": False,
        "type": "wecom",
        "url": ""
    }
}


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    if not os.path.exists(path):
        if os.path.exists(EXAMPLE_CONFIG):
            log("没找到 config.json，先用 config.example.json（建议复制一份改成自己的字段）")
            path = EXAMPLE_CONFIG
        else:
            log("没找到配置文件，用内置默认值")
            return cfg
    with open(path, "r", encoding="utf-8-sig") as f:
        user = json.load(f)

    def merge(base, over):
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                merge(base[k], v)
            else:
                base[k] = v
    merge(cfg, user)
    return cfg


# ---------------------------------------------------------------- 读数据

def find_files(root, pattern, recursive):
    import fnmatch
    root = os.path.abspath(os.path.join(HERE, root))
    if not os.path.isdir(root):
        return [], root
    out = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(('.', '_'))]
            for fn in filenames:
                if fnmatch.fnmatch(fn.lower(), pattern.lower()):
                    out.append(os.path.join(dirpath, fn))
    else:
        for fn in os.listdir(root):
            if fnmatch.fnmatch(fn.lower(), pattern.lower()):
                out.append(os.path.join(root, fn))
    out.sort()
    return out, root


def load_rows(cfg):
    files, root = find_files(cfg["input_dir"], cfg["file_pattern"], cfg["recursive"])
    if not files:
        return [], [], root
    date_k = cfg["date_field"]
    amt_k = cfg["amount_field"]
    rows, skipped = [], []
    for path in files:
        text = read_text(path)
        try:
            reader = csv.DictReader(text.splitlines())
        except Exception as e:
            skipped.append((os.path.basename(path), "读取失败: %s" % e))
            continue
        if not reader.fieldnames:
            skipped.append((os.path.basename(path), "空文件"))
            continue
        fields = [(f or "").strip() for f in reader.fieldnames]
        if amt_k not in fields:
            skipped.append((os.path.basename(path), "缺列「%s」，现有列：%s" % (amt_k, "/".join(fields))))
            continue
        n = 0
        for raw in reader:
            rec = {}
            for f in reader.fieldnames:
                rec[(f or "").strip()] = raw.get(f)
            d = parse_date(rec.get(date_k)) if date_k in fields else None
            amt = to_number(rec.get(amt_k))
            if amt is None:
                continue
            rec["_date"] = d
            rec["_amount"] = amt
            rec["_file"] = os.path.basename(path)
            rows.append(rec)
            n += 1
        if n == 0:
            skipped.append((os.path.basename(path), "没有可用金额行"))
    return rows, skipped, root


# ---------------------------------------------------------------- 计算

def summarize(rows, cfg, target_date):
    """返回当天的指标字典。"""
    day_rows = [r for r in rows if r["_date"] == target_date] if target_date else rows
    total = sum(r["_amount"] for r in day_rows)
    cnt = len(day_rows)
    avg = total / cnt if cnt else 0.0

    groups = {}
    for gf in cfg["group_fields"]:
        bucket = {}
        for r in day_rows:
            k = str(r.get(gf, "") or "").strip() or "(未填)"
            bucket[k] = bucket.get(k, 0.0) + r["_amount"]
        groups[gf] = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)

    top_field = cfg.get("top_field") or ""
    tops = []
    if top_field:
        pairs = []
        for r in day_rows:
            name = str(r.get(top_field, "") or "").strip() or "(未填)"
            pairs.append((name, r["_amount"], r))
        pairs.sort(key=lambda p: p[1], reverse=True)
        tops = pairs[:int(cfg["top_n"])]

    return {
        "date": target_date,
        "total": total,
        "count": cnt,
        "avg": avg,
        "groups": groups,
        "tops": tops,
        "rows": day_rows
    }


def pick_dates(rows, target_date, mode):
    dates = sorted({r["_date"] for r in rows if r["_date"]})
    if not dates:
        return None, None
    if target_date is None:
        target_date = dates[-1]
    prev = None
    if mode == "previous_day":
        earlier = [d for d in dates if d < target_date]
        prev = earlier[-1] if earlier else None
    elif mode == "same_day_last_week":
        prev = target_date - timedelta(days=7)
        if prev not in dates:
            prev = None
    return target_date, prev


# ---------------------------------------------------------------- 告警

def build_alerts(cur, prev_sum, cfg):
    a = cfg.get("alerts") or {}
    out = []
    drop = a.get("drop_pct")
    rise = a.get("rise_pct")
    if prev_sum and prev_sum["count"] > 0:
        chg = pct_change(cur["total"], prev_sum["total"])
        if chg is not None and drop is not None and chg <= -abs(float(drop)):
            out.append("销售额较上一周期下降 %.1f%%（阈值 -%.0f%%）：%s -> %s"
                       % (abs(chg), abs(float(drop)), fmt_money(prev_sum["total"]), fmt_money(cur["total"])))
        if chg is not None and rise is not None and chg >= abs(float(rise)):
            out.append("销售额较上一周期上涨 %.1f%%（阈值 +%.0f%%）：%s -> %s"
                       % (chg, abs(float(rise)), fmt_money(prev_sum["total"]), fmt_money(cur["total"])))
    min_amt = float(a.get("min_amount") or 0)
    if min_amt > 0 and cur["total"] < min_amt:
        out.append("销售额 %s 低于设定的下限 %s" % (fmt_money(cur["total"]), fmt_money(min_amt)))
    min_cnt = int(a.get("min_orders") or 0)
    if min_cnt > 0 and cur["count"] < min_cnt:
        out.append("单数 %d 低于设定的下限 %d" % (cur["count"], min_cnt))
    if cur["count"] == 0:
        out.append("当天没有任何数据行，请检查数据文件是否按时导出")
    return out


# ---------------------------------------------------------------- 渲染

def render_text(cur, prev, cfg, alerts, files, skipped, history):
    L = []
    d = cur["date"]
    L.append("=" * 46)
    L.append("每日经营数据简报  %s" % (d.strftime("%Y-%m-%d") if d else "(未指定日期)"))
    L.append("=" * 46)
    if files:
        L.append("数据来源：%s" % "、".join(os.path.basename(f) for f in files[:6]) +
                 (" 等 %d 个文件" % len(files) if len(files) > 6 else ""))
    L.append("统计口径：金额字段「%s」，共 %d 行有效数据" % (cfg["amount_field"], cur["count"]))
    L.append("")

    L.append("一、核心指标")
    chg_total = pct_change(cur["total"], prev["total"]) if prev else None
    chg_cnt = (cur["count"] - prev["count"]) if prev else None
    chg_avg = pct_change(cur["avg"], prev["avg"]) if prev else None
    L.append("  销售额    ¥%s%s" % (fmt_money(cur["total"]),
                                  ("   环比 %s" % fmt_pct(chg_total)) if chg_total is not None else "   （无对比期）"))
    L.append("  订单数    %d 单%s" % (cur["count"],
                                   ("   环比 %+d 单" % chg_cnt) if chg_cnt is not None else ""))
    L.append("  客单价    ¥%s%s" % (fmt_money(cur["avg"]),
                                  ("   环比 %s" % fmt_pct(chg_avg)) if chg_avg is not None else ""))
    if prev:
        L.append("  对比期    %s（销售 ¥%s / %d 单）"
                 % (prev["date"].strftime("%Y-%m-%d"), fmt_money(prev["total"]), prev["count"]))
    L.append("")

    for gf, items in cur["groups"].items():
        if not items:
            continue
        L.append("二、按「%s」拆分" % gf)
        mx = items[0][1]
        for k, v in items:
            share = (v / cur["total"] * 100) if cur["total"] else 0
            L.append("  %-12s ¥%12s  %5.1f%%  %s" % (k, fmt_money(v), share, bar(v, mx)))
        L.append("")

    if cur["tops"]:
        L.append("三、TOP %d（按「%s」）" % (len(cur["tops"]), cfg.get("top_field")))
        for i, (name, amt, _r) in enumerate(cur["tops"], 1):
            L.append("  %d. %-16s ¥%s" % (i, name, fmt_money(amt)))
        L.append("")

    L.append("四、告警")
    if alerts:
        for a in alerts:
            L.append("  ! %s" % a)
    else:
        L.append("  无。各项指标均在设定范围内。")
    L.append("")

    if len(history) > 1:
        L.append("五、近期走势")
        for h in history[-7:]:
            L.append("  %s  ¥%12s  %4d 单  %s" % (h[0], fmt_money(h[1]), h[2], bar(h[1], max(x[1] for x in history), 18)))
        L.append("")

    if skipped:
        L.append("附：被跳过的文件")
        for fn, why in skipped:
            L.append("  - %s：%s" % (fn, why))
        L.append("")

    L.append("本简报由 daily_brief.py 自动生成 %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    return "\n".join(L)


def render_markdown(cur, prev, cfg, alerts, history):
    L = []
    d = cur["date"]
    L.append("# 每日经营数据简报 %s" % (d.strftime("%Y-%m-%d") if d else ""))
    L.append("")
    L.append("| 指标 | 今日 | 环比 |")
    L.append("|---|---|---|")
    chg_total = pct_change(cur["total"], prev["total"]) if prev else None
    L.append("| 销售额 | ¥%s | %s |" % (fmt_money(cur["total"]), fmt_pct(chg_total) if chg_total is not None else "-"))
    L.append("| 订单数 | %d | %s |" % (cur["count"], ("%+d" % (cur["count"] - prev["count"])) if prev else "-"))
    L.append("| 客单价 | ¥%s | %s |" % (fmt_money(cur["avg"]),
             fmt_pct(pct_change(cur["avg"], prev["avg"])) if prev and prev["avg"] else "-"))
    L.append("")
    for gf, items in cur["groups"].items():
        if not items:
            continue
        L.append("## 按「%s」拆分" % gf)
        L.append("")
        L.append("| %s | 金额 | 占比 |" % gf)
        L.append("|---|---|---|")
        for k, v in items:
            share = (v / cur["total"] * 100) if cur["total"] else 0
            L.append("| %s | ¥%s | %.1f%% |" % (k, fmt_money(v), share))
        L.append("")
    L.append("## 告警")
    L.append("")
    if alerts:
        for a in alerts:
            L.append("- %s" % a)
    else:
        L.append("- 无")
    L.append("")
    if len(history) > 1:
        L.append("## 近期走势")
        L.append("")
        L.append("| 日期 | 销售额 | 订单数 |")
        L.append("|---|---|---|")
        for h in history[-7:]:
            L.append("| %s | ¥%s | %d |" % (h[0], fmt_money(h[1]), h[2]))
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 历史

def load_history(path):
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows.append([r.get("date", ""), to_number(r.get("amount")) or 0.0,
                             int(to_number(r.get("orders")) or 0)])
    except Exception:
        return []
    return rows


def save_history(path, history):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "amount", "orders"])
        for h in history:
            w.writerow(h)


# ---------------------------------------------------------------- 推送

def push_webhook(text, cfg):
    wh = cfg.get("webhook") or {}
    url = (wh.get("url") or "").strip()
    if not url:
        return False, "没有填 Webhook 地址"
    kind = (wh.get("type") or "wecom").lower()
    if kind == "wecom":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif kind == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    else:
        return False, "不支持的 webhook 类型：%s" % kind
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
        return True, body[:200]
    except urllib.error.HTTPError as e:
        return False, "HTTP %s" % e.code
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="每日经营数据简报机器人")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--date", default=None, help="报告日期 YYYY-MM-DD，默认取数据里最新的一天")
    ap.add_argument("--dry-run", action="store_true", help="只算不写文件")
    ap.add_argument("--push", action="store_true", help="推送到 config 里配置的群机器人")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = load_config(args.config)
    log("读取配置：%s" % os.path.basename(args.config if os.path.exists(args.config) else EXAMPLE_CONFIG))

    rows, skipped, root = load_rows(cfg)
    log("数据目录：%s" % root)
    log("读到 %d 行有效数据" % len(rows))
    if not rows:
        log("没有可用数据。请确认 input 目录里有 CSV，且包含「%s」列。" % cfg["amount_field"])
        return 1

    target = parse_date(args.date) if args.date else None
    target, prev_date = pick_dates(rows, target, cfg.get("compare_mode", "previous_day"))
    cur = summarize(rows, cfg, target)
    prev = summarize(rows, cfg, prev_date) if prev_date else None
    if prev and prev["count"] == 0:
        prev = None

    alerts = build_alerts(cur, prev, cfg)

    out_dir = os.path.abspath(os.path.join(HERE, cfg["output_dir"]))
    os.makedirs(out_dir, exist_ok=True)
    history = load_history(os.path.join(out_dir, cfg["history_file"]))
    ds = target.strftime("%Y-%m-%d")
    # 把数据里出现的每一天都并入历史，这样第一次跑就有走势，不用攒
    existing = {h[0]: h for h in history}
    all_dates = sorted({r["_date"] for r in rows if r["_date"]})
    for d in all_dates:
        s = summarize(rows, cfg, d)
        existing[d.strftime("%Y-%m-%d")] = [d.strftime("%Y-%m-%d"), round(s["total"], 2), s["count"]]
    existing[ds] = [ds, round(cur["total"], 2), cur["count"]]
    history = sorted(existing.values(), key=lambda h: h[0])

    files, _ = find_files(cfg["input_dir"], cfg["file_pattern"], cfg["recursive"])
    text = render_text(cur, prev, cfg, alerts, files, skipped, history)
    md = render_markdown(cur, prev, cfg, alerts, history)

    print()
    print(text)
    print()

    if args.dry_run:
        log("--dry-run：未写入任何文件")
        return 0

    p_txt = os.path.join(out_dir, "daily-brief.txt")
    p_md = os.path.join(out_dir, "daily-brief.md")
    with open(p_txt, "w", encoding="utf-8") as f:
        f.write(text)
    with open(p_md, "w", encoding="utf-8") as f:
        f.write(md)

    day_rows = cur["rows"]
    fields = []
    for r in day_rows:
        for k in r.keys():
            if not k.startswith("_") and k not in fields:
                fields.append(k)
    p_csv = os.path.join(out_dir, "detail-%s.csv" % ds)
    with open(p_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in day_rows:
            w.writerow({k: r.get(k, "") for k in fields})

    p_grp = os.path.join(out_dir, "groups-%s.csv" % ds)
    with open(p_grp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["分组字段", "分组值", "金额", "占比%"])
        for gf, items in cur["groups"].items():
            for k, v in items:
                share = (v / cur["total"] * 100) if cur["total"] else 0
                w.writerow([gf, k, "%.2f" % v, "%.1f" % share])

    save_history(os.path.join(out_dir, cfg["history_file"]), history)

    log("已写出：%s" % os.path.basename(p_txt))
    log("已写出：%s" % os.path.basename(p_md))
    log("已写出：%s（%d 行）" % (os.path.basename(p_csv), len(day_rows)))
    log("已写出：%s" % os.path.basename(p_grp))
    log("已更新：%s（累计 %d 天）" % (cfg["history_file"], len(history)))

    if args.push:
        ok, info = push_webhook(text, cfg)
        log("推送：%s %s" % ("成功" if ok else "失败", info))

    return 0


if __name__ == "__main__":
    sys.exit(main())
