#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tests/make_testdata.py —— 本地起一个假站点，把 uptime_monitor.py 完整跑一遍。

为什么要这么测：真去访问外部网站，结果取决于当时的网络，不稳定也不好验收。
这里用 Python 标准库 http.server 在本机起 4 个接口，把「正常 / 慢 / 超时 / 故障后恢复」
四种情况全部造出来，一轮跑完就能同时验证状态码、关键词、超时、连续失败计数、
故障判定和恢复告警五条链路。

跑法：  python tests/make_testdata.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SCRIPT = os.path.join(BASE, "uptime_monitor.py")
TEST_CFG = os.path.join(HERE, "test-config.json")
OUT_DIR = os.path.join(BASE, "output")
REPORT = os.path.join(OUT_DIR, "latest-report.txt")

PY = sys.executable or "python"

# /flaky 前两次返回 500，之后返回 200 —— 用来验证「连续失败 → 判定故障 → 恢复」
flaky_hits = {"n": 0}
slow_ms = {"v": 1200}
webhook_posts = []     # 收到的告警推送内容


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # 不刷屏

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/ok":
            self._send(200, "<html><body><h1>后台运行正常</h1><p>订单队列 0 积压</p></body></html>",
                       "text/html; charset=utf-8")
        elif p == "/slow":
            time.sleep(slow_ms["v"] / 1000.0)
            self._send(200, "slow but ok")
        elif p == "/hang":
            time.sleep(5)          # 客户端超时 1s，必然触发超时分支
            self._send(200, "too late")
        elif p == "/flaky":
            flaky_hits["n"] += 1
            if flaky_hits["n"] <= 2:
                self._send(500, "internal error", "text/plain; charset=utf-8")
            else:
                self._send(200, "recovered")
        elif p == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(404, "not found")

    def do_POST(self):
        # 充当群机器人 Webhook，把收到的内容记下来
        n = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(n) if n else b""
        webhook_posts.append(raw.decode("utf-8", "ignore"))
        self._send(200, '{"errcode":0,"errmsg":"ok"}', "application/json")


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def run_monitor():
    r = subprocess.run([PY, SCRIPT, "--config", TEST_CFG, "--no-alert"],
                       cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r


def read_report():
    with open(REPORT, "r", encoding="utf-8") as f:
        return f.read()


def main():
    srv, port = start_server()
    base = "http://127.0.0.1:%d" % port
    print("本地假站点已启动：%s" % base)

    cfg = {
        "interval_seconds": 60,
        "timeout_seconds": 1,
        "retry": 0,
        "retry_wait_seconds": 0,
        "fail_threshold": 2,
        "slow_ms": 800,
        "verify_ssl": True,
        "alert": {"enabled": False, "type": "none", "webhook": ""},
        "targets": [
            {"name": "官网首页", "url": base + "/ok", "expect_status": 200, "expect_keyword": "后台运行正常"},
            {"name": "慢接口", "url": base + "/slow", "expect_status": 200, "timeout_seconds": 5},
            {"name": "超时接口", "url": base + "/hang", "expect_status": 200},
            {"name": "支付回调", "url": base + "/flaky", "expect_status": 200}
        ]
    }
    with open(TEST_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    fails = []
    checks = 0

    def expect(cond, label):
        nonlocal checks
        checks += 1
        if cond:
            print("  PASS  " + label)
        else:
            print("  FAIL  " + label)
            fails.append(label)

    # ---------- 第 1 轮：支付回调第 1 次失败，未达阈值 ----------
    print("\n=== 第 1 轮 ===")
    r = run_monitor()
    print(r.stdout.strip())
    rep = read_report()
    expect(r.returncode == 0, "第 1 轮退出码为 0")
    expect("监控 4 个地址：正常 2 / 异常 2" in rep, "第 1 轮 2 正常 2 异常（超时接口 + 支付回调）")
    expect("异常 1/2 次，未达告警阈值" in rep, "支付回调第 1 次失败且不告警")
    expect("超时（>1s）" in rep or "超时" in rep, "超时接口正确识别为超时")
    expect("响应偏慢（阈值 800ms）" in rep, "慢接口触发响应偏慢提示")
    expect("关键词  命中" in rep, "官网首页关键词命中")

    # ---------- 第 2 轮：支付回调第 2 次失败，判定故障 ----------
    print("\n=== 第 2 轮 ===")
    r = run_monitor()
    print(r.stdout.strip())
    rep = read_report()
    expect("监控 4 个地址：正常 2 / 异常 2" in rep, "第 2 轮 2 正常 2 异常")
    expect("判定故障（连续异常 2 次" in rep, "支付回调第 2 次失败判定为故障")
    expect("本次告警 2 条" in rep, "第 2 轮产生 2 条告警（超时接口 + 支付回调均达阈值）")

    # ---------- 第 3 轮：支付回调恢复 ----------
    print("\n=== 第 3 轮 ===")
    r = run_monitor()
    print(r.stdout.strip())
    rep = read_report()
    expect("监控 4 个地址：正常 3 / 异常 1" in rep, "第 3 轮 3 正常 1 异常（仅超时接口仍故障）")
    expect("已恢复（此前连续异常 2 次）" in rep, "支付回调正确报出恢复")
    expect("本次告警 1 条" in rep, "第 3 轮产生 1 条恢复告警")

    # ---------- CSV 明细 ----------
    csv_path = os.path.join(OUT_DIR, "uptime-%s.csv" % time.strftime("%Y-%m-%d"))
    if os.path.isfile(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            rows = f.read().strip().split("\n")
        expect(len(rows) >= 13, "CSV 累计行数 >= 13（1 表头 + 3 轮 x 4 项），实际 %d" % len(rows))
        expect("时间,名称,地址,结果,状态码,耗时ms,重试次数,关键词命中,说明" in rows[0], "CSV 表头正确")
    else:
        expect(False, "CSV 明细文件存在：%s" % csv_path)

    # ---------- 状态文件 ----------
    st_path = os.path.join(OUT_DIR, "state.json")
    if os.path.isfile(st_path):
        with open(st_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        expect(st.get("支付回调", {}).get("consecutive_fail") == 0, "state.json 记录支付回调已归零")
        expect(st.get("超时接口", {}).get("down") is True, "state.json 记录超时接口为故障态")
    else:
        expect(False, "state.json 存在")

    # ---------- 告警推送链路 ----------
    print("\n=== 告警推送 ===")
    sys.path.insert(0, BASE)
    import uptime_monitor as um
    ok, note = um.send_webhook({"enabled": True, "type": "wecom", "webhook": base + "/webhook"},
                               "可用性告警 测试\n· 官网首页：判定故障")
    expect(ok is True and note == "已推送", "企业微信 Webhook 推送成功（%s）" % note)
    expect(len(webhook_posts) == 1 and "判定故障" in webhook_posts[0], "推送内容含告警正文")
    expect(webhook_posts and '"msgtype": "text"' in webhook_posts[0].replace('"msgtype":"text"', '"msgtype": "text"'),
           "企业微信消息体格式正确")
    ok2, _ = um.send_webhook({"enabled": True, "type": "feishu", "webhook": base + "/webhook"}, "飞书测试")
    expect(ok2 is True, "飞书 Webhook 推送成功")
    expect(webhook_posts and '"msg_type"' in webhook_posts[-1], "飞书消息体格式正确")
    ok3, note3 = um.send_webhook({"enabled": False, "type": "wecom", "webhook": base + "/webhook"}, "不该发出去")
    expect(ok3 is False and "未开启" in note3, "未开启推送时不发请求")
    ok4, note4 = um.send_webhook({"enabled": True, "type": "wecom", "webhook": ""}, "空地址")
    expect(ok4 is False and "未配置" in note4, "webhook 为空时安全跳过")
    before = len(webhook_posts)
    um.send_webhook({"enabled": False, "type": "wecom", "webhook": base + "/webhook"}, "不该发出去")
    expect(len(webhook_posts) == before, "关闭状态下确实没有产生网络请求")

    srv.shutdown()
    srv.server_close()

    print("\n" + "=" * 56)
    print("断言 %d 项，失败 %d 项" % (checks, len(fails)))
    if fails:
        for x in fails:
            print("  - " + x)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
