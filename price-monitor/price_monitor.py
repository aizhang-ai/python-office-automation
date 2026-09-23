#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格 / 页面变化监控日报 —— 零依赖版

只用 Python 标准库，不需要 pip install 任何东西，不需要服务器，不需要 n8n。
装了 Python 3.8+ 就能跑。

用法：
    python price_monitor.py              正常运行（抓取 -> 比对 -> 写快照 -> 推送）
    python price_monitor.py --no-push    只跑不推送，先看结果
    python price_monitor.py --verbose    打印抓取到的价格明细
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.example.json")
HISTORY_PATH = os.path.join(BASE_DIR, "history.csv")
REPORT_DIR = os.path.join(BASE_DIR, "reports")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 匹配 ¥199.00 / ￥1,299 / $29.99 / 199元 这类写法
PRICE_PATTERN = re.compile(
    r"(?:[¥￥$]\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?))"
    r"|(?:\d+(?:\.\d{1,2})?\s?元)"
)


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg))


# ---------------------------------------------------------------- 配置

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            "找不到 config.json。请先复制 config.example.json 为 config.json，"
            "按 README.md 填写监控目标后重试。\n示例文件位置：%s" % EXAMPLE_PATH
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("targets"):
        sys.exit("config.json 里的 targets 是空的，至少要填一个要监控的页面。")
    return cfg


# ---------------------------------------------------------------- 抓取

def robots_allows(url, ua, respect=True):
    """遵守对方 robots.txt。读不到 robots.txt 时按允许处理（HTTP 无 robots 即无限制）。"""
    if not respect:
        return True, "已按配置跳过 robots 检查"
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return True, "非网页地址，跳过"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url("%s://%s/robots.txt" % (parts.scheme, parts.netloc))
        rp.read()
        allowed = rp.can_fetch(ua, url)
        return allowed, "robots 允许" if allowed else "robots 禁止抓取"
    except Exception as exc:
        return True, "robots 读取失败(%s)，按允许处理" % exc


def fetch(url, ua, timeout=20):
    # 不以 http 开头的按本地文件读取（方便先用本地页面试跑，也支持监控导出的网页快照）
    if not url.lower().startswith(("http://", "https://")):
        path = url if os.path.isabs(url) else os.path.join(BASE_DIR, url)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="ignore")


def extract_price(html, custom_regex=None):
    """取页面里出现次数最多的价格作为主价格 —— 比取第一个更稳（能避开侧边栏推荐价）。"""
    if custom_regex:
        try:
            hits = re.findall(custom_regex, html)
        except re.error:
            hits = []
        hits = [h if isinstance(h, str) else h[0] for h in hits]
    else:
        hits = [m.group(0).strip() for m in PRICE_PATTERN.finditer(html)]

    hits = [h.replace(" ", "") for h in hits if h and h.strip()]
    if not hits:
        return None, []
    top = Counter(hits).most_common(1)[0][0]
    return top, hits[:10]


# ---------------------------------------------------------------- 快照

def read_last_snapshot():
    """返回 {name: (date, price)}，用于和今天比对。"""
    last = {}
    if not os.path.exists(HISTORY_PATH):
        return last
    with open(HISTORY_PATH, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = row.get("name")
            if key:
                last[key] = (row.get("date", ""), row.get("price", ""))
    return last


def append_snapshot(rows):
    is_new = not os.path.exists(HISTORY_PATH)
    os.makedirs(os.path.dirname(HISTORY_PATH) or ".", exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "time", "name", "url", "price", "status", "note"])
        if is_new:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)


# ---------------------------------------------------------------- 报告与推送

def build_report(results, today):
    lines = ["价格监控日报 %s" % today, ""]
    changed = [r for r in results if r["status"] == "changed"]
    errors = [r for r in results if r["status"] in ("error", "blocked")]
    noprice = [r for r in results if r["status"] == "no_price"]
    unchanged = [r for r in results if r["status"] == "unchanged"]
    first = [r for r in results if r["status"] == "first"]

    if changed:
        lines.append("== 有变化（%d 项）==" % len(changed))
        for r in changed:
            lines.append("· %s：%s -> %s" % (r["name"], r["prev_price"], r["price"]))
            lines.append("  %s" % r["url"])
        lines.append("")
    if first:
        lines.append("== 首次记录（%d 项）==" % len(first))
        for r in first:
            lines.append("· %s：%s" % (r["name"], r["price"] or "未取到价格"))
        lines.append("")
    if noprice:
        lines.append("== 未匹配到价格（%d 项）==" % len(noprice))
        for r in noprice:
            lines.append("· %s：%s" % (r["name"], r["note"]))
        lines.append("")
    if errors:
        lines.append("== 抓取失败（%d 项）==" % len(errors))
        for r in errors:
            lines.append("· %s：%s" % (r["name"], r["note"]))
        lines.append("")
    lines.append("无变化 %d 项。" % len(unchanged))
    if not changed:
        lines.append("")
        lines.append("（今天没有需要你处理的价格变动。）")
    return "\n".join(lines)


def push(webhook_cfg, text):
    """支持企业微信 / 飞书 / 钉钉 三种机器人。没配置就跳过。"""
    if not webhook_cfg or not webhook_cfg.get("url"):
        return "未配置机器人，跳过推送"
    wtype = (webhook_cfg.get("type") or "wecom").lower()
    url = webhook_cfg["url"]
    if wtype == "wecom":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif wtype == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    elif wtype == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
    else:
        payload = {"text": text}

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        return "推送成功：%s" % body[:120]
    except urllib.error.URLError as exc:
        return "推送失败：%s" % exc


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="价格/页面变化监控日报（零依赖）")
    ap.add_argument("--no-push", action="store_true", help="只跑不推送")
    ap.add_argument("--verbose", action="store_true", help="打印抓到的价格明细")
    args = ap.parse_args()

    cfg = load_config()
    ua = cfg.get("user_agent") or DEFAULT_UA
    respect = cfg.get("respect_robots", True)
    targets = cfg.get("targets", [])
    delay = float(cfg.get("request_delay_seconds", 3))

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M:%S")
    last = read_last_snapshot()
    results = []

    log("开始监控 %d 个目标" % len(targets))
    for t in targets:
        name = t.get("name") or t.get("url")
        url = t["url"]
        note = ""

        allowed, why = robots_allows(url, ua, respect)
        if not allowed:
            log("%s：%s，跳过" % (name, why))
            results.append({
                "date": today, "time": now, "name": name, "url": url,
                "price": "", "status": "blocked", "note": why,
                "prev_price": "", "changed": False,
            })
            continue

        try:
            html = fetch(url, ua)
            price, samples = extract_price(html, t.get("price_regex"))
            status = "first" if name not in last else ("changed" if last[name][1] != (price or "") else "unchanged")
            if price is None:
                note = "页面里没匹配到价格，检查 price_regex 是否要自定义"
                status = "error" if status == "first" else status
            if args.verbose:
                log("%s 候选价格：%s" % (name, samples))
            log("%s：%s（%s）" % (name, price or "未取到", {"first": "首次记录", "changed": "有变化", "unchanged": "无变化", "error": "失败"}[status]))
        except Exception as exc:
            price, status, note = "", "error", str(exc)
            log("%s：抓取失败 %s" % (name, exc))

        prev = last.get(name, ("", ""))[1]
        results.append({
            "date": today, "time": now, "name": name, "url": url,
            "price": price or "", "status": status, "note": note,
            "prev_price": prev, "changed": status == "changed",
        })

        if delay > 0:
            import time
            time.sleep(delay)

    append_snapshot([{k: r[k] for k in ("date", "time", "name", "url", "price", "status", "note")} for r in results])

    report = build_report(results, today)
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, "report-%s.txt" % today)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print("")
    print(report)
    print("")
    print("快照已写入：%s" % HISTORY_PATH)
    print("日报已写入：%s" % report_path)

    if args.no_push:
        print("（--no-push：未推送）")
    else:
        only_on_change = cfg.get("push_only_on_change", True)
        need_push = (not only_on_change) or any(r["changed"] for r in results)
        if need_push:
            print(push(cfg.get("webhook"), report))
        else:
            print("今天没有变化，按配置不推送。")


if __name__ == "__main__":
    main()
