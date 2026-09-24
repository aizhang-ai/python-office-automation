#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成每日经营数据简报的测试数据。
为什么要造脏数据：真实导出的表从来不干净——金额带千分位和人民币符号、
日期有四种写法、有空行、有退货负数。工具要能扛住这些才算能交付。

运行：python tests/make_testdata.py
输出：input/sales_2026-09-2x.csv（5 天，含一天大跌用于触发告警）
"""

import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IN = os.path.join(ROOT, "input")

CITIES = ["深圳", "广州", "上海", "北京", "杭州"]
CHANNELS = ["门店", "外卖", "电商", "团购"]
# 每天一个"基准额"，第 4 天故意腰斩，用于验证跌告警
BASE = {0: 12000, 1: 13100, 2: 12800, 3: 6400, 4: 13500}
# 日期写法轮换：验证 2026-09-24 / 2026/9/24 / 2026.9.24 / 20260924 / 2026年9月24日 都能解析
DATE_STYLE = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%Y年%m月%d日"]


def money(v):
    """金额也故意写得乱：带千分位、带人民币符号、带空格、负数用括号。"""
    style = random.randint(0, 3)
    if style == 0:
        return "{:,.2f}".format(v)
    if style == 1:
        return "¥{:,.2f}".format(v)
    if style == 2:
        return " {:,.2f} ".format(v)
    return "{:.2f}".format(v)


def main():
    os.makedirs(IN, exist_ok=True)
    random.seed(20260924)
    start = date(2026, 9, 20)
    total_files = 0
    total_rows = 0

    for i in range(5):
        d = start + timedelta(days=i)
        dstr_fmt = DATE_STYLE[i]
        path = os.path.join(IN, "sales_%s.csv" % d.strftime("%Y-%m-%d"))
        rows = []
        n_orders = 12 if i != 3 else 6
        for j in range(n_orders):
            amt = round(BASE[i] / n_orders * random.uniform(0.5, 1.6), 2)
            rows.append({
                "date": d.strftime(dstr_fmt),
                "order_id": "DD%s%03d" % (d.strftime("%Y%m%d"), j + 1),
                "city": random.choice(CITIES),
                "channel": random.choice(CHANNELS),
                "amount": money(amt)
            })
        # 脏数据：1 行空金额（应被跳过）、1 行负数退货（应被计入总额并拉低）
        rows.append({"date": d.strftime(dstr_fmt), "order_id": "DD%s901" % d.strftime("%Y%m%d"),
                     "city": "深圳", "channel": "电商", "amount": ""})
        rows.append({"date": d.strftime(dstr_fmt), "order_id": "DD%s902" % d.strftime("%Y%m%d"),
                     "city": "广州", "channel": "电商", "amount": "(380.00)"})
        # 缺城市字段，验证归入 "(未填)"
        rows.append({"date": d.strftime(dstr_fmt), "order_id": "DD%s903" % d.strftime("%Y%m%d"),
                     "city": "", "channel": "门店", "amount": money(520)})

        cols = ["date", "order_id", "city", "channel", "amount"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(",".join(cols) + "\n")
            for r in rows:
                f.write(",".join('"%s"' % str(r[c]).replace('"', '""') for c in cols) + "\n")
        total_files += 1
        total_rows += len(rows)
        print("写出 %s（%d 行，日期写法 %s）" % (os.path.basename(path), len(rows), dstr_fmt))

    print()
    print("共 %d 个文件 %d 行（含 5 行空金额 + 5 行退货负数 + 5 行缺城市）" % (total_files, total_rows))
    print("第 4 天（2026-09-23）基准额腰斩，用于验证下跌告警。")


if __name__ == "__main__":
    main()
