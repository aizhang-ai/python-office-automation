#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
uptime_monitor.py —— 网站 / 接口可用性监控告警

只依赖 Python 标准库，不用 pip 装任何东西。双击 run.bat 就能跑。

做什么：
  1. 按 config.json 里的清单，逐个访问网站或接口地址
  2. 记录状态码、耗时、页面里有没有你指定的关键词
  3. 失败自动重试（可配次数与间隔），连续失败到阈值才判定为「故障」
  4. 只在状态翻转时告警（正常→故障、故障→恢复），不重复刷屏
  5. 可选推送到企业微信 / 钉钉 / 飞书群机器人（官方 Webhook，默认关闭）
  6. 每次结果追加进 output/uptime-YYYY-MM-DD.csv，方便事后对账

不做什么：
  - 不登录、不带 Cookie、不绕验证码、不高频刷请求（默认每轮间隔 >= 60 秒）

用法：
  python uptime_monitor.py                 # 按 config.json 跑一轮
  python uptime_monitor.py --loop          # 常驻，按 interval 循环
  python uptime_monitor.py --target 官网   # 只跑名字里含「官网」的项
  python uptime_monitor.py --no-alert      # 本轮不推送
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(BASE_DIR, "config.json")
OUT_DIR = os.path.join(BASE_DIR, "output")
STATE_FILE = os.path.join(OUT_DIR, "state.json")

CST = timezone(timedelta(hours=8))
MAX_BODY = 300 * 1024          # 只下载前 300KB，够做关键词判断，避免大页面拖慢
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) UptimeMonitor/1.0 (python-stdlib)"


# ---------------------------------------------------------------- 基础工具

def now() -> datetime:
    return datetime.now(CST)


def stamp(dt: datetime = None) -> str:
    return (dt or now()).strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print("[%s] %s" % (now().strftime("%H:%M:%S"), msg))


def ensure_out() -> None:
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR, exist_ok=True)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    cfg.setdefault("targets", [])
    cfg.setdefault("interval_seconds", 300)
    cfg.setdefault("timeout_seconds", 10)
    cfg.setdefault("retry", 2)
    cfg.setdefault("retry_wait_seconds", 5)
    cfg.setdefault("fail_threshold", 2)
    cfg.setdefault("slow_ms", 3000)
    cfg.setdefault("alert", {"enabled": False, "type": "none", "webhook": ""})
    return cfg


def load_state() -> dict:
    if not os.path.isfile(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    ensure_out()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def build_ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------- 单次探测

def decode_body(raw: bytes, headers) -> str:
    """按响应头 / meta charset / 兜底 utf-8 解码，乱码不影响状态码判断。"""
    enc = None
    ctype = ""
    try:
        ctype = headers.get("Content-Type", "") or ""
    except Exception:
        ctype = ""
    m = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if m:
        enc = m.group(1)
    if not enc:
        head = raw[:2048].decode("ascii", "ignore")
        m = re.search(r'charset=["\']?([\w\-]+)', head, re.I)
        if m:
            enc = m.group(1)
    for cand in [enc, "utf-8", "gb18030"]:
        if not cand:
            continue
        try:
            return raw.decode(cand, "ignore")
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def probe(target: dict, cfg: dict, ctx: ssl.SSLContext) -> dict:
    """探测一个地址，返回结构化结果（不抛异常）。"""
    url = target.get("url", "")
    timeout = float(target.get("timeout_seconds", cfg.get("timeout_seconds", 10)))
    method = str(target.get("method", "GET")).upper()
    headers = {"User-Agent": USER_AGENT}
    for k, v in (target.get("headers") or {}).items():
        headers[str(k)] = str(v)

    data = None
    if "body" in target and target["body"] is not None:
        data = target["body"].encode("utf-8") if isinstance(target["body"], str) else str(target["body"]).encode("utf-8")

    started = time.perf_counter()
    res = {
        "name": target.get("name") or url,
        "url": url,
        "ok": False,
        "status": 0,
        "ms": 0,
        "error": "",
        "keyword_hit": None,
        "checked_at": stamp(),
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(MAX_BODY)
            res["status"] = int(getattr(resp, "status", resp.getcode()) or 0)
            body = decode_body(raw, resp.headers)
    except urllib.error.HTTPError as e:
        # 4xx/5xx 也是「有响应」，状态码要留下来
        raw = b""
        try:
            raw = e.read(MAX_BODY)
        except Exception:
            pass
        res["status"] = int(getattr(e, "code", 0) or 0)
        body = decode_body(raw, e.headers or {})
        res["error"] = "HTTP %s" % res["status"]
    except socket.timeout:
        res["ms"] = int((time.perf_counter() - started) * 1000)
        res["error"] = "超时（>%ss）" % timeout
        return res
    except urllib.error.URLError as e:
        res["ms"] = int((time.perf_counter() - started) * 1000)
        res["error"] = "连接失败：%s" % (e.reason if getattr(e, "reason", None) else e)
        return res
    except Exception as e:
        res["ms"] = int((time.perf_counter() - started) * 1000)
        res["error"] = "%s: %s" % (type(e).__name__, e)
        return res

    res["ms"] = int((time.perf_counter() - started) * 1000)

    # 状态码判定
    expect = target.get("expect_status", 200)
    accepts = expect if isinstance(expect, list) else [expect]
    accepts = [int(x) for x in accepts]
    status_ok = res["status"] in accepts

    # 关键词判定（可选）
    kw = target.get("expect_keyword")
    if kw:
        res["keyword_hit"] = str(kw) in body
        ok = status_ok and res["keyword_hit"]
        if status_ok and not res["keyword_hit"]:
            res["error"] = "页面里找不到关键词「%s」" % kw
    else:
        ok = status_ok
        if not status_ok and not res["error"]:
            res["error"] = "状态码 %s，期望 %s" % (res["status"], "/".join(str(a) for a in accepts))

    res["ok"] = ok
    return res


def probe_with_retry(target: dict, cfg: dict, ctx: ssl.SSLContext) -> dict:
    """失败重试：任一次成功即成功；全失败则取最后一次结果。"""
    retry = int(target.get("retry", cfg.get("retry", 2)))
    wait = float(target.get("retry_wait_seconds", cfg.get("retry_wait_seconds", 5)))
    last = None
    attempt = 0
    while attempt <= retry:
        last = probe(target, cfg, ctx)
        last["attempts"] = attempt + 1
        if last["ok"]:
            return last
        attempt += 1
        if attempt <= retry and wait > 0:
            time.sleep(wait)
    return last


# ---------------------------------------------------------------- 记录与告警

def append_csv(res: dict) -> str:
    ensure_out()
    path = os.path.join(OUT_DIR, "uptime-%s.csv" % now().strftime("%Y-%m-%d"))
    new = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["时间", "名称", "地址", "结果", "状态码", "耗时ms", "重试次数", "关键词命中", "说明"])
        w.writerow([
            res.get("checked_at", ""),
            res.get("name", ""),
            res.get("url", ""),
            "正常" if res.get("ok") else "异常",
            res.get("status", ""),
            res.get("ms", ""),
            res.get("attempts", 1),
            "" if res.get("keyword_hit") is None else ("是" if res["keyword_hit"] else "否"),
            res.get("error", ""),
        ])
    return path


def build_alert_text(title: str, lines: list) -> str:
    return title + "\n" + "\n".join(lines)


def send_webhook(alert_cfg: dict, text: str) -> tuple:
    """只走平台官方群机器人 Webhook。未开启或被禁用时直接返回 (False, 原因)。"""
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
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read(2048)
        return True, "已推送"
    except urllib.error.HTTPError as e:
        return False, "推送失败 HTTP %s" % getattr(e, "code", "?")
    except Exception as e:
        return False, "推送失败：%s" % e


# ---------------------------------------------------------------- 报告

def write_report(results: list, cfg: dict, alerts: list, alert_note: str) -> str:
    ensure_out()
    total = len(results)
    bad = [r for r in results if not r["ok"]]
    good = total - len(bad)
    slow_ms = int(cfg.get("slow_ms", 3000))

    L = []
    L.append("可用性监控报告  %s" % stamp())
    L.append("监控 %d 个地址：正常 %d / 异常 %d" % (total, good, len(bad)))
    L.append("-" * 60)
    for r in results:
        tag = "正常" if r["ok"] else "异常"
        L.append("[%s] %s" % (tag, r["name"]))
        L.append("      地址    %s" % r["url"])
        L.append("      状态码  %s   耗时 %sms   重试 %s 次" %
                 (r["status"] or "-", r["ms"], r.get("attempts", 1)))
        if r.get("keyword_hit") is not None:
            L.append("      关键词  %s" % ("命中" if r["keyword_hit"] else "未命中"))
        if r.get("state_note"):
            L.append("      状态    %s" % r["state_note"])
        if r["ms"] and r["ok"] and r["ms"] > slow_ms:
            L.append("      提示    响应偏慢（阈值 %sms）" % slow_ms)
        if r.get("error"):
            L.append("      原因    %s" % r["error"])
        L.append("")

    L.append("本次告警 %d 条（%s）" % (len(alerts), alert_note))
    for a in alerts:
        L.append("  · %s" % a)
    L.append("")
    L.append("明细已追加到 output/uptime-%s.csv" % now().strftime("%Y-%m-%d"))

    text = "\n".join(L)
    path = os.path.join(OUT_DIR, "latest-report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------- 主流程

def run_once(cfg: dict, state: dict, do_alert: bool, name_filter: str = "") -> tuple:
    targets = cfg["targets"]
    if name_filter:
        targets = [t for t in targets if name_filter in str(t.get("name", ""))]
    if not targets:
        raise SystemExit("config.json 里没有可监控的地址（targets 为空或过滤后为空）")

    ctx = build_ssl_context(bool(cfg.get("verify_ssl", True)))
    threshold = int(cfg.get("fail_threshold", 2))
    results = []
    alerts = []

    for t in targets:
        name = t.get("name") or t.get("url")
        log("检查 %s ..." % name)
        res = probe_with_retry(t, cfg, ctx)
        st = state.get(name) or {}
        prev_fail = int(st.get("consecutive_fail", 0))
        was_down = bool(st.get("down", False))

        if res["ok"]:
            cur_fail = 0
            if was_down:
                res["state_note"] = "已恢复（此前连续异常 %d 次）" % prev_fail
                alerts.append("%s 已恢复，耗时 %sms" % (name, res["ms"]))
            else:
                res["state_note"] = "连续正常"
        else:
            cur_fail = prev_fail + 1
            if cur_fail >= threshold:
                if not was_down:
                    res["state_note"] = "判定故障（连续异常 %d 次，首次 %s）" % (
                        cur_fail, st.get("first_fail_at") or res["checked_at"])
                    alerts.append("%s 故障：%s" % (name, res["error"] or ("状态码 %s" % res["status"])))
                else:
                    res["state_note"] = "仍故障（连续异常 %d 次，首次 %s）" % (
                        cur_fail, st.get("first_fail_at") or res["checked_at"])
            else:
                res["state_note"] = "异常 %d/%d 次，未达告警阈值" % (cur_fail, threshold)

        state[name] = {
            "down": cur_fail >= threshold,
            "consecutive_fail": cur_fail,
            "first_fail_at": st.get("first_fail_at") or ("" if res["ok"] else res["checked_at"]),
            "last_ok_at": res["checked_at"] if res["ok"] else st.get("last_ok_at", ""),
            "last_status": res["status"],
            "last_ms": res["ms"],
        }
        results.append(res)
        append_csv(res)
        log("  %s  状态 %s  耗时 %sms" % ("正常" if res["ok"] else "异常", res["status"] or "-", res["ms"]))

    alert_note = "未开启推送"
    if alerts and do_alert:
        title = "可用性告警 %s" % stamp()
        lines = []
        for r in results:
            if r.get("state_note") and ("故障" in r["state_note"] or "恢复" in r["state_note"]):
                lines.append("· %s：%s（%s）" % (r["name"], r["state_note"], r.get("error") or "状态码 %s" % r["status"]))
        ok, note = send_webhook(cfg.get("alert", {}), build_alert_text(title, lines))
        alert_note = note
    elif alerts:
        alert_note = "本轮 --no-alert，未推送"
    elif not do_alert:
        alert_note = "无状态翻转，无需推送"

    save_state(state)
    return results, alerts, alert_note


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="网站/接口可用性监控告警（纯标准库）")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="配置文件路径，默认 config.json")
    ap.add_argument("--loop", action="store_true", help="常驻循环，按 interval_seconds 间隔执行")
    ap.add_argument("--interval", type=int, default=0, help="覆盖配置里的间隔秒数")
    ap.add_argument("--target", default="", help="只跑名称里包含该关键字的监控项")
    ap.add_argument("--no-alert", action="store_true", help="本轮不推送告警")
    ap.add_argument("--timeout", type=int, default=0, help="覆盖配置里的超时秒数")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.config):
        print("找不到配置文件：%s" % args.config)
        print("请把 config.example.json 复制一份改名为 config.json，再填你要监控的地址。")
        return 2

    try:
        cfg = load_config(args.config)
    except json.JSONDecodeError as e:
        print("config.json 不是合法的 JSON：%s（第 %s 行第 %s 列）" % (e.msg, e.lineno, e.colno))
        return 2

    if args.timeout:
        cfg["timeout_seconds"] = args.timeout
    interval = args.interval or int(cfg.get("interval_seconds", 300))
    if interval < 10:
        print("间隔太短（%ss），已自动改为 60s，避免把对方站点刷挂。" % interval)
        interval = 60

    state = load_state()
    rounds = 0
    try:
        while True:
            rounds += 1
            results, alerts, alert_note = run_once(cfg, state, not args.no_alert, args.target)
            path = write_report(results, cfg, alerts, alert_note)
            print("")
            print("报告已写入：%s" % path)
            print("告警 %d 条（%s）" % (len(alerts), alert_note))
            if not args.loop:
                break
            print("等待 %s 秒后进入下一轮（Ctrl+C 退出）..." % interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已手动停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
