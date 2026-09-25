#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tests/make_testdata.py —— 造两份「故意对不上」的店铺商品表，把 shop_diff.py 完整跑一遍。

造的数据（全部写死，结果可预期）：
  总店   SKU S001–S040（其中 1 行缺主键、S021 重复一次）→ 有效 40 个
  京东店 SKU S001–S035 + S041–S044（文件用 GBK 编码存）   → 39 个
  差异：价格 7 处（6 处数值 + S014 对方空值）、库存 4 处、标题 2 处、状态 1 处
  只在总店有：S036–S040（5 个）    只在京东店有：S041–S044（4 个）
  脏数据：金额带 ¥ 与千分位、库存带「件」、SKU 前后带空格

跑法：  python tests/make_testdata.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SCRIPT = os.path.join(BASE, "shop_diff.py")
IN_DIR = os.path.join(BASE, "input")
OUT_DIR = os.path.join(BASE, "output")
REPORT = os.path.join(OUT_DIR, "latest-report.txt")
STORE_A = os.path.join(IN_DIR, "store_a.csv")
STORE_B = os.path.join(IN_DIR, "store_b.csv")

PY = sys.executable or "python"

PRICE_DELTA = {1: 100, 2: 50, 3: 300, 4: 20, 5: 10, 6: 5}   # S001–S006 改价
STOCK_DIFF = set([7, 8, 9, 10])                              # S007–S010 改库存
TITLE_DIFF = set([11, 12])                                   # S011–S012 改标题
STATUS_DIFF = set([13])                                      # S013 改状态
BLANK_PRICE = 14                                             # S014 对方价格为空


def base_price(i):
    return 1000 + i * 10


def build_rows():
    """返回 (总店行, 京东店行)，行是 list[str]，含表头。"""
    a = [["sku", "title", "price", "stock", "status"]]
    b = [["sku", "title", "price", "stock", "status"]]

    for i in range(1, 41):
        sku = "S%03d" % i
        # 故意在 S020 的前后加空格，检验 trim
        a_sku = " %s " % sku if i == 20 else sku
        title = "商品%03d" % i
        p = base_price(i)
        stock = 100 + i
        # 总店：金额带 ¥ 和千分位，库存带「件」
        a.append([a_sku, title, "¥%s" % format(p, ",.2f"), "%d件" % stock, "在售"])

        if i > 35:
            continue          # S036–S040 只在总店有

        bp = p
        if i in PRICE_DELTA:
            bp = p + PRICE_DELTA[i]
        bstock = stock - 3 if i in STOCK_DIFF else stock
        btitle = title + "（京东专供）" if i in TITLE_DIFF else title
        bstatus = "下架" if i in STATUS_DIFF else "在售"

        b_price = ""
        if i == BLANK_PRICE:
            b_price = ""                     # 对方价格缺失
        elif i == 2:
            b_price = format(bp, ",.2f")     # 带千分位不带 ¥
        else:
            b_price = "%d" % bp
        # 京东店 SKU 也来一个前后空格，检验两边都能 trim
        b_sku = " %s " % sku if i == 20 else sku
        b.append([b_sku, btitle, b_price, str(bstock), bstatus])

    for i in range(41, 45):                  # 只在京东店有
        b.append(["S%03d" % i, "商品%03d" % i, str(base_price(i)), str(100 + i), "在售"])

    # 脏数据：一行缺主键、一行主键重复
    a.append(["", "没编码的商品", "¥1,111.00", "5件", "在售"])
    a.append(["S021", "商品021 重复行", "¥1,210.00", "121件", "在售"])
    return a, b


def write_csv(path, rows, encoding):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    import csv
    with open(path, "w", encoding=encoding, newline="") as f:
        csv.writer(f).writerows(rows)


def snapshot(paths):
    return {p: (os.path.getsize(p), int(os.path.getmtime(p))) for p in paths}


def run(extra=None, cfg=None, out=None):
    cmd = [PY, SCRIPT]
    if cfg:
        cmd += ["--config", cfg]
    if out:
        cmd += ["--out", out]
    cmd += extra or []
    return subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def line_count(p):
    with open(p, "r", encoding="utf-8-sig") as f:
        return len([x for x in f.read().split("\n") if x.strip()])


def main():
    fails, checks = [], 0

    def expect(cond, label):
        nonlocal checks
        checks += 1
        if cond:
            print("  PASS  " + label)
        else:
            print("  FAIL  " + label)
            fails.append(label)

    a_rows, b_rows = build_rows()
    write_csv(STORE_A, a_rows, "utf-8-sig")
    write_csv(STORE_B, b_rows, "gb18030")
    print("已造数据：%s（UTF-8-BOM）、%s（GBK）" % (os.path.basename(STORE_A), os.path.basename(STORE_B)))

    before = snapshot([STORE_A, STORE_B])

    sys.path.insert(0, BASE)
    import shop_diff as sd

    print("\n== 1. 金额/数字解析 ==")
    expect(sd.norm_num("¥1,299.00") == 1299.0, "¥1,299.00 -> 1299.0")
    expect(sd.norm_num("1 299") == 1299.0, "带空格 1 299 -> 1299.0")
    expect(sd.norm_num("(380)") == -380.0, "(380) -> -380.0（括号负数）")
    expect(sd.norm_num("120件") == 120.0, "120件 -> 120.0")
    expect(sd.norm_num("99元") == 99.0, "99元 -> 99.0")
    expect(sd.norm_num("-45") == -45.0, "-45 -> -45.0")
    expect(sd.norm_num("") is None, "空 -> None")
    expect(sd.norm_num("N/A") is None, "N/A -> None")
    expect(sd.norm_num("待定") is None, "中文 -> None")
    expect(sd.norm_num("12.5%") == 12.5, "12.5% -> 12.5")

    print("\n== 2. 读表（编码探测 + 脏数据）==")
    cfg = sd.load_config(os.path.join(BASE, "config.json"))
    ta = sd.read_table(STORE_A, cfg)
    tb = sd.read_table(STORE_B, cfg)
    expect(ta["encoding"] == "utf-8-sig", "总店文件识别为 utf-8-sig（实际 %s）" % ta["encoding"])
    expect(tb["encoding"] == "gb18030", "京东店文件识别为 gb18030（实际 %s）" % tb["encoding"])
    expect(len(ta["rows"]) == 40, "总店有效 40 行（实际 %d）" % len(ta["rows"]))
    expect(len(tb["rows"]) == 39, "京东店有效 39 行（实际 %d）" % len(tb["rows"]))
    expect(len(ta["skipped"]) == 1, "缺主键跳过 1 行（实际 %d）" % len(ta["skipped"]))
    expect(len(ta["dups"]) == 1, "主键重复识别 1 个（实际 %d）" % len(ta["dups"]))
    expect(ta["dups"][0][0] == "S021", "重复的是 S021（实际 %s）" % (ta["dups"][0][0] if ta["dups"] else "-"))
    expect("S020" in [r["sku"] for r in ta["rows"]], "前后带空格的 S020 被 trim 后正确读入")

    print("\n== 3. 比对逻辑 ==")
    res = sd.compare_pair(ta, tb, cfg)
    expect(res["common"] == 35, "共有 35 个（实际 %d）" % res["common"])
    expect(len(res["only_base"]) == 5, "只在总店有 5 个（实际 %d）" % len(res["only_base"]))
    expect(len(res["only_other"]) == 4, "只在京东店有 4 个（实际 %d）" % len(res["only_other"]))
    expect(len(res["diffs"]) == 14, "差异共 14 处（实际 %d）" % len(res["diffs"]))
    expect(len(res["by_field"].get("price", [])) == 7, "price 差异 7 处（实际 %d）" % len(res["by_field"].get("price", [])))
    expect(len(res["by_field"].get("stock", [])) == 4, "stock 差异 4 处（实际 %d）" % len(res["by_field"].get("stock", [])))
    expect(len(res["by_field"].get("title", [])) == 2, "title 差异 2 处（实际 %d）" % len(res["by_field"].get("title", [])))
    expect(len(res["by_field"].get("status", [])) == 1, "status 差异 1 处（实际 %d）" % len(res["by_field"].get("status", [])))
    blank = [d for d in res["diffs"] if d["sku"] == "S014"]
    expect(bool(blank) and blank[0]["kind"] == "缺值", "S014 对方价格为空 -> 记为「缺值」")
    tops = sd.price_top(res, "price", 3)
    expect(tops[0]["sku"] == "S003", "价格差异最大的是 S003（实际 %s）" % tops[0]["sku"])
    expect(abs(tops[0]["delta"] - 300.0) < 1e-9, "S003 差值 +300（实际 %s）" % tops[0]["delta"])
    expect("S020" not in res["only_base"] + res["only_other"], "带空格的 S020 没被误判为「只有一方有」")

    print("\n== 4. 端到端跑一遍（run.bat 走的就是这条命令）==")
    r = run(["--no-alert"])
    expect(r.returncode == 0, "退出码 0（实际 %s）" % r.returncode)
    rep = read(REPORT)
    expect("共有 35" in rep, "报告含「共有 35」")
    expect("有差异的 SKU 14 个" in rep, "报告含「有差异的 SKU 14 个」")
    expect("price 不一致 7 处" in rep, "报告含「price 不一致 7 处」")
    expect("只在【总店】有（5 个）" in rep, "报告含「只在【总店】有（5 个）」")
    expect("只在【京东店】有（4 个）" in rep, "报告含「只在【京东店】有（4 个）」")
    expect("S003" in rep and "+300.00" in rep, "价格 TOP 首条为 S003 +300.00")
    expect("跳过 1 行" in rep, "报告提示跳过 1 行")
    expect("主键重复 1 个" in rep, "报告提示主键重复 1 个")

    print("\n== 5. 产出文件 ==")
    dpath = os.path.join(OUT_DIR, "diff-detail.csv")
    spath = os.path.join(OUT_DIR, "summary.csv")
    expect(line_count(dpath) == 24, "diff-detail.csv 24 行（1 表头 + 14 差异 + 9 单边），实际 %d" % line_count(dpath))
    expect(line_count(spath) == 2, "summary.csv 2 行（1 表头 + 1 对比对），实际 %d" % line_count(spath))

    print("\n== 6. 原始文件未被改动 ==")
    after = snapshot([STORE_A, STORE_B])
    expect(before == after, "两份源 CSV 的字节数与修改时间全程未变")

    print("\n== 7. 告警阈值与推送 ==")
    ok, note = sd.send_webhook({"enabled": False, "type": "wecom", "webhook": "https://x"}, "不该发")
    expect(ok is False and "未开启" in note, "未开启推送时不发请求")
    ok, note = sd.send_webhook({"enabled": True, "type": "wecom", "webhook": ""}, "空地址")
    expect(ok is False and "未配置" in note, "webhook 为空时安全跳过")
    cfg2 = json.loads(json.dumps(cfg))
    cfg2["max_alert_diff"] = 9999
    p2 = os.path.join(HERE, "test-config-pair.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(cfg2, f, ensure_ascii=False, indent=2)
    r2 = run(cfg=p2)
    expect("未达阈值" in (r2.stdout or ""), "差异未达阈值时不告警")

    print("\n== 8. all_pairs 模式（3 个店铺两两比对 == 3 对）==")
    write_csv(os.path.join(IN_DIR, "store_c.csv"),
              [["sku", "title", "price", "stock", "status"]] +
              [["S%03d" % i, "商品%03d" % i, str(base_price(i)), str(100 + i), "在售"] for i in range(1, 31)],
              "utf-8-sig")
    cfg3 = json.loads(json.dumps(cfg))
    cfg3["mode"] = "all_pairs"
    cfg3["stores"] = [{"name": "总店", "file": "input/store_a.csv"},
                      {"name": "京东店", "file": "input/store_b.csv"},
                      {"name": "抖音店", "file": "input/store_c.csv"}]
    cfg3["max_alert_diff"] = 9999
    p3 = os.path.join(HERE, "test-config-all.json")
    out3 = os.path.join(BASE, "output-test")
    with open(p3, "w", encoding="utf-8") as f:
        json.dump(cfg3, f, ensure_ascii=False, indent=2)
    r3 = run(cfg=p3, out=out3)
    expect(r3.returncode == 0, "all_pairs 模式退出码 0")
    expect(line_count(os.path.join(out3, "summary.csv")) == 4,
           "all_pairs 产出 3 个对比对（summary 4 行），实际 %d" % line_count(os.path.join(out3, "summary.csv")))

    # 清理测试产物
    for p in (p2, p3):
        if os.path.isfile(p):
            os.remove(p)
    import shutil
    if os.path.isdir(out3):
        shutil.rmtree(out3)
    cpath = os.path.join(IN_DIR, "store_c.csv")
    if os.path.isfile(cpath):
        os.remove(cpath)

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
