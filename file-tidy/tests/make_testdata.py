#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 file-tidy 的测试数据：故意做成「真实世界里那种乱文件夹」

10 个文件，含：
  - 2 组内容完全重复（DSC_0001.jpg 与 DSC_0001_副本.jpg；8月销售.xlsx 与其副本）
  - 1 个空文件（扫描件_空白.pdf）
  - 3 层目录
  - 中文名、带空格名、大写扩展名混用

运行：python tests/make_testdata.py
"""

import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DIR = os.path.join(BASE_DIR, "input")

FILES = [
    ("照片/DSC_0001.jpg", "photo-a-content"),
    ("照片/DSC_0002.jpg", "photo-b-content"),
    ("照片/DSC_0001_副本.jpg", "photo-a-content"),          # 与 DSC_0001 重复
    ("照片/logo.PNG", "logo-content"),                       # 大写扩展名
    ("合同/合同-张三.docx", "contract-a-content"),
    ("合同/扫描件.pdf", "scanned-pdf-content"),
    ("合同/扫描件_空白.pdf", ""),                            # 空文件
    ("报表/8月销售.xlsx", "sales-august-content"),
    ("报表/8月销售 - 副本.xlsx", "sales-august-content"),    # 与 8月销售 重复
    ("杂项/backup 2026.zip", "zip-content"),                 # 名字含空格
    ("杂项/readme.txt", "readme-content"),
]


def main():
    if os.path.isdir(IN_DIR):
        shutil.rmtree(IN_DIR)
    os.makedirs(IN_DIR, exist_ok=True)
    for rel, content in FILES:
        p = os.path.join(IN_DIR, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    print("测试数据已生成：%s（%d 个文件）" % (IN_DIR, len(FILES)))


if __name__ == "__main__":
    main()
