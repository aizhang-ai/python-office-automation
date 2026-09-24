#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件自动整理归档工具 —— 零依赖版

只用 Python 标准库，不需要 pip install，不需要任何第三方软件。
把一个乱糟糟的文件夹，按你定的规则变成：分类目录 + 统一文件名 + 重复件单独挑出来。

能做的事：
  1. 按扩展名分类到不同文件夹（图片 / 文档 / 表格 / 压缩包 / 视频 / 其他，可自己改）
  2. 按模板批量重命名，支持变量：{category} {date} {year} {month} {day}
                                {index:03d} {name} {ext} {size} {hash8}
  3. 按文件内容（SHA-256）查重：内容完全一样的文件单独放一个文件夹，不删原件
  4. 顺手标出：空文件、小于指定大小的疑似废文件
  5. 输出归档清单 CSV + 重复文件清单 CSV + 运行报告

默认「复制」而不是「移动」：原文件夹一个字节都不动，先跑一遍看清单，确认无误再改成移动。

用法：
    python file_tidy.py                # 按 config.json 里的规则执行
    python file_tidy.py --dry-run      # 只列出会怎么变，不真动文件（强烈建议先跑这个）
    python file_tidy.py --init         # 生成配置模板，并统计 input 里都有哪些扩展名
    python file_tidy.py --verbose      # 打印每个文件的处理明细
"""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.example.json")
REPORT_PATH = os.path.join(BASE_DIR, "run-report.txt")

TOKEN_RE = re.compile(r"\{(\w+)(?::0?(\d+)d)?\}")

DEFAULT_CONFIG = {
    "input_dir": "input",
    "output_dir": "output",
    "recursive": True,
    "mode": "copy",              # copy = 复制（原文件不动，推荐） / move = 移动
    "dry_run": False,            # true = 只出清单不真动
    "on_conflict": "rename",     # rename = 自动加 (2) / skip = 跳过 / overwrite = 覆盖
    "categories": {
        "图片": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"],
        "文档": [".pdf", ".doc", ".docx", ".txt", ".md", ".ppt", ".pptx"],
        "表格": [".xls", ".xlsx", ".csv"],
        "压缩包": [".zip", ".rar", ".7z", ".tar", ".gz"],
        "视频": [".mp4", ".avi", ".mov", ".mkv", ".wmv"],
        "音频": [".mp3", ".wav", ".m4a", ".flac"],
        "其他": ["*"],
    },
    "rename": {
        "enabled": True,
        "template": "{category}_{date}_{index:03d}",
        "date_source": "mtime",      # mtime = 最后修改时间 / ctime = 创建时间 / today = 今天
        "date_format": "%Y%m%d",
        "lowercase_ext": True,
        "keep_original_name": False,  # true = 完全不改文件名，只做分类和查重
    },
    "dedupe": {
        "enabled": True,
        "action": "separate",        # separate = 重复件单独放文件夹 / skip = 重复件不归档
        "folder": "_重复文件",
    },
    "exclude_names": [".git", "node_modules", "__pycache__", ".DS_Store", "Thumbs.db"],
    "min_size_warn": 1024,           # 小于这个字节数的文件在报告里标一下；设 0 关闭
}


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg))


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    if not os.path.exists(CONFIG_PATH):
        if not os.path.exists(EXAMPLE_PATH):
            write_example_config()
        with open(EXAMPLE_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log("没找到 config.json，已用模板生成一份，请先改规则再跑")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return deep_merge(DEFAULT_CONFIG, cfg)


def write_example_config():
    with open(EXAMPLE_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)


def abs_path(p):
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)


def file_sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def iter_files(root, recursive, exclude_names):
    """产出 (绝对路径, 相对路径)"""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return
    if recursive:
        walker = os.walk(root)
    else:
        walker = [(root, [], os.listdir(root))]
    for dirpath, dirnames, filenames in walker:
        dirnames[:] = [d for d in dirnames if d not in exclude_names]
        for name in filenames:
            if name in exclude_names:
                continue
            full = os.path.join(dirpath, name)
            if not os.path.isfile(full):
                continue
            yield full, os.path.relpath(full, root)


def build_ext_map(categories):
    m = {}
    for cat, exts in categories.items():
        for e in exts:
            m[str(e).lower().strip()] = cat
    return m


def category_of(ext, ext_map, categories):
    cat = ext_map.get(ext.lower())
    if cat:
        return cat
    return "其他" if "其他" in categories else (list(categories.keys())[-1] if categories else "其他")


def render_template(tpl, ctx):
    def rep(m):
        key = m.group(1)
        if key not in ctx:
            return m.group(0)
        v = ctx[key]
        if m.group(2):
            return str(v).zfill(int(m.group(2)))
        return str(v)
    return TOKEN_RE.sub(rep, tpl)


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while True:
        cand = "%s(%d)%s" % (base, i, ext)
        if not os.path.exists(cand):
            return cand
        i += 1


def flatten_rel(rel):
    return rel.replace(os.sep, "__").replace("/", "__")


def place(src, dst, mode, dry_run):
    """复制或移动一个文件，返回实际写入的路径"""
    if dst == src:
        return dst
    if not dry_run:
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        if mode == "move":
            shutil.move(src, dst)
        else:
            shutil.copy2(src, dst)
    return dst


def tidy(cfg, dry_run=False, verbose=False):
    in_dir = abs_path(cfg["input_dir"])
    out_dir = abs_path(cfg["output_dir"])
    if not os.path.isdir(in_dir):
        log("找不到输入文件夹：%s" % in_dir)
        return 1

    ext_map = build_ext_map(cfg["categories"])
    ren = cfg["rename"]
    dd = cfg["dedupe"]
    min_size = cfg.get("min_size_warn") or 0

    files = sorted(iter_files(in_dir, cfg["recursive"], set(cfg["exclude_names"])))
    # 不要把输出目录自己扫进来
    files = [(f, r) for f, r in files if os.path.commonpath([os.path.abspath(f), os.path.abspath(out_dir)]) != os.path.abspath(out_dir)]

    log("输入：%s" % in_dir)
    log("输出：%s" % out_dir)
    log("模式：%s%s" % (cfg["mode"], "（试跑，不真动文件）" if dry_run else ""))
    log("扫到 %d 个文件" % len(files))
    if not files:
        return 0

    seen = {}          # hash -> 第一个出现的相对路径
    counters = defaultdict(int)
    rows = []          # 归档清单
    dups = []          # 重复清单
    empties = []
    tiny = []
    skipped_conflict = []

    for src, rel in files:
        try:
            st = os.stat(src)
        except OSError as e:
            log("读不到：%s（%s）" % (rel, e))
            continue

        name, ext = os.path.splitext(os.path.basename(src))
        if ren.get("lowercase_ext", True):
            ext_out = ext.lower()
        else:
            ext_out = ext
        cat = category_of(ext, ext_map, cfg["categories"])
        size = st.st_size

        if size == 0:
            empties.append(rel)
        elif min_size and size < min_size:
            tiny.append((rel, size))

        h = file_sha256(src) if dd.get("enabled") else ""
        is_dup = bool(h) and h in seen

        if is_dup:
            first = seen[h]
            dups.append((rel, first, h[:16], size))
            if dd.get("action") == "skip":
                if verbose:
                    log("重复，跳过：%s（与 %s 内容一致）" % (rel, first))
                continue
            # separate：重复件放进单独文件夹
            target = os.path.join(out_dir, dd.get("folder") or "_重复文件", flatten_rel(rel))
            target = unique_path(target) if cfg["on_conflict"] == "rename" else target
            if cfg["on_conflict"] == "skip" and os.path.exists(target):
                skipped_conflict.append(rel)
                continue
            place(src, target, cfg["mode"], dry_run)
            rows.append((rel, os.path.relpath(target, out_dir), "重复件", size,
                         datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), h[:16]))
            if verbose:
                log("重复：%s -> %s" % (rel, os.path.relpath(target, out_dir)))
            continue

        if h:
            seen[h] = rel

        counters[cat] += 1
        idx = counters[cat]
        if ren.get("enabled") and not ren.get("keep_original_name"):
            if ren.get("date_source") == "ctime":
                dt = datetime.fromtimestamp(st.st_ctime)
            elif ren.get("date_source") == "today":
                dt = datetime.now()
            else:
                dt = datetime.fromtimestamp(st.st_mtime)
            ctx = OrderedDict([
                ("name", name),
                ("ext", ext_out),
                ("category", cat),
                ("date", dt.strftime(ren.get("date_format") or "%Y%m%d")),
                ("year", dt.strftime("%Y")),
                ("month", dt.strftime("%m")),
                ("day", dt.strftime("%d")),
                ("index", idx),
                ("size", size),
                ("hash8", h[:8] if h else ""),
            ])
            newname = render_template(ren.get("template") or "{name}", ctx) + ext_out
        else:
            newname = os.path.basename(src)

        target = os.path.join(out_dir, cat, newname)
        if os.path.exists(os.path.abspath(target)):
            if cfg["on_conflict"] == "skip":
                skipped_conflict.append(rel)
                continue
            if cfg["on_conflict"] == "rename":
                target = unique_path(target)
        place(src, target, cfg["mode"], dry_run)
        rows.append((rel, os.path.relpath(target, out_dir), cat, size,
                     datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), h[:16]))
        if verbose:
            log("%s -> %s" % (rel, os.path.relpath(target, out_dir)))

    # ---------- 写清单 ----------
    list_dir = os.path.join(out_dir, "_清单")
    os.makedirs(list_dir, exist_ok=True)
    idx_path = os.path.join(list_dir, "file-index.csv")
    dup_path = os.path.join(list_dir, "duplicates.csv")

    with open(idx_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["原路径", "归档后路径", "类别", "大小(字节)", "修改时间", "内容指纹"])
        w.writerows(rows)

    with open(dup_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["重复文件", "与哪个文件相同", "内容指纹", "大小(字节)"])
        w.writerows(dups)

    lines = []
    lines.append("文件自动整理归档 —— 运行报告")
    lines.append("运行时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("输入目录：%s" % in_dir)
    lines.append("输出目录：%s" % out_dir)
    lines.append("模式：%s%s" % (cfg["mode"], "（试跑，未真实写入）" if dry_run else ""))
    lines.append("")
    lines.append("扫描文件数：%d" % len(files))
    lines.append("归档文件数：%d" % len([r for r in rows if r[2] != "重复件"]))
    lines.append("重复文件数：%d" % len(dups))
    lines.append("空文件数：%d" % len(empties))
    lines.append("")
    lines.append("按类别统计：")
    for cat in cfg["categories"]:
        if counters.get(cat):
            lines.append("  %s：%d 个" % (cat, counters[cat]))
    if any(r[2] == "重复件" for r in rows):
        lines.append("  %s：%d 个" % (dd.get("folder") or "_重复文件", len([r for r in rows if r[2] == "重复件"])))
    lines.append("")
    if dups:
        lines.append("重复文件（内容完全一致，原件未删除）：")
        for rel, first, fp, size in dups:
            lines.append("  %s  ==  %s  (%d 字节)" % (rel, first, size))
        lines.append("")
    if empties:
        lines.append("空文件（0 字节，已一并归档，建议人工确认是否该删）：")
        for rel in empties:
            lines.append("  %s" % rel)
        lines.append("")
    if tiny:
        lines.append("疑似废文件（小于 %d 字节）：" % min_size)
        for rel, size in tiny:
            lines.append("  %s（%d 字节）" % (rel, size))
        lines.append("")
    if skipped_conflict:
        lines.append("因目标已存在而跳过的文件：")
        for rel in skipped_conflict:
            lines.append("  %s" % rel)
        lines.append("")
    lines.append("归档清单 CSV：%s" % os.path.relpath(idx_path, BASE_DIR))
    lines.append("重复清单 CSV：%s" % os.path.relpath(dup_path, BASE_DIR))

    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print()
    print(report)
    log("报告已写入：%s" % REPORT_PATH)
    return 0


def scan_extensions(cfg):
    in_dir = abs_path(cfg["input_dir"])
    if not os.path.isdir(in_dir):
        log("找不到输入文件夹：%s" % in_dir)
        return
    tally = defaultdict(int)
    for _, rel in iter_files(in_dir, cfg["recursive"], set(cfg["exclude_names"])):
        ext = os.path.splitext(rel)[1].lower()
        tally[ext or "(无扩展名)"] += 1
    log("input 目录里的扩展名统计（改 config.json 的分类时照着抄）：")
    for ext, n in sorted(tally.items(), key=lambda x: -x[1]):
        print("  %-16s %d 个" % (ext, n))


def main():
    ap = argparse.ArgumentParser(description="文件自动整理归档（零依赖）")
    ap.add_argument("--init", action="store_true", help="生成配置模板并统计扩展名")
    ap.add_argument("--dry-run", action="store_true", help="只出清单，不真动文件")
    ap.add_argument("--verbose", action="store_true", help="打印每个文件的明细")
    args = ap.parse_args()

    if args.init:
        write_example_config()
        log("已生成配置模板：%s" % EXAMPLE_PATH)
        cfg = load_config()
        scan_extensions(cfg)
        return 0

    cfg = load_config()
    dry = args.dry_run or bool(cfg.get("dry_run"))
    return tidy(cfg, dry_run=dry, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
