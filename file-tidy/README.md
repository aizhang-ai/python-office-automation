# 文件自动整理归档工具（零依赖版）

把一个乱糟糟的文件夹，按你定的规则变成：**分类目录 + 统一文件名 + 重复件单独挑出来**。

- 只用 Python 标准库，**不用 pip install、不用装任何软件**
- 默认「复制」模式：**原文件夹一个字节都不动**，满意了再改成移动
- 支持先 `--dry-run` 试跑：只出清单，不碰文件

---

## 三步跑起来

1. 装 Python 3.8 以上（装的时候一定勾 **Add Python to PATH**）
2. 把要整理的文件放进 `input` 文件夹（支持子文件夹）
3. 双击 `run.bat`

第一次跑建议先点「试跑」，看清单对不对，再正式执行。

命令行用法：

```
python file_tidy.py                # 按 config.json 执行
python file_tidy.py --dry-run      # 只出清单，不真动文件
python file_tidy.py --init         # 生成配置模板 + 统计 input 里都有哪些扩展名
python file_tidy.py --verbose      # 打印每个文件怎么变的
```

---

## 能做什么

| 功能 | 说明 |
|---|---|
| 按扩展名分类 | 图片 / 文档 / 表格 / 压缩包 / 视频 / 音频 / 其他，类别和扩展名都能自己改 |
| 批量重命名 | 模板变量：`{category}` `{date}` `{year}` `{month}` `{day}` `{index:03d}` `{name}` `{ext}` `{size}` `{hash8}` |
| 内容查重 | 按 SHA-256 比对文件内容，**只挑出来，不删原件**（默认放进 `_重复文件` 文件夹） |
| 标出空文件 | 0 字节的文件单独列出来，建议人工确认后再删 |
| 出清单 | `output/_清单/file-index.csv`（每个文件从哪来到哪去）、`duplicates.csv`（哪两个文件内容一样） |

## 配置文件 config.json

常用几项：

```jsonc
{
  "input_dir": "input",          // 要整理的文件夹
  "output_dir": "output",        // 整理结果放哪
  "recursive": true,             // 是否连子文件夹一起整理
  "mode": "copy",                // copy=复制（原文件不动）/ move=移动
  "on_conflict": "rename",       // 目标已存在时：rename=自动加(2) / skip=跳过 / overwrite=覆盖
  "rename": {
    "template": "{category}_{date}_{index:03d}",   // 例：文档_20260924_001.docx
    "date_source": "mtime",                        // mtime=修改时间 / ctime=创建时间 / today=今天
    "keep_original_name": false                    // true=完全不改文件名，只分类和查重
  },
  "dedupe": {
    "enabled": true,
    "action": "separate",        // separate=重复件单独放 / skip=重复件不归档
    "folder": "_重复文件"
  },
  "min_size_warn": 1024          // 小于该字节数的文件在报告里标一下；设 0 关闭
}
```

想按自己的分类（比如「合同」「发票」「毕业照」），改 `categories` 就行，
先跑 `python file_tidy.py --init`，它会把 input 里出现的扩展名统计出来，照着抄即可。

---

## 本机实测记录（Windows + Python 3.13，可复现）

测试数据由 `tests/make_testdata.py` 生成：11 个文件、3 层目录，
故意放进 2 组内容完全相同的文件、1 个空文件、1 个大写扩展名、1 个带空格的文件名。

**真实运行输出**（`python file_tidy.py --verbose`）：

```
[19:49:38] 扫到 11 个文件
[19:49:38] 合同\合同-张三.docx -> 文档\文档_20260924_001.docx
[19:49:38] 合同\扫描件.pdf -> 文档\文档_20260924_002.pdf
[19:49:38] 合同\扫描件_空白.pdf -> 文档\文档_20260924_003.pdf
[19:49:38] 报表\8月销售 - 副本.xlsx -> 表格\表格_20260924_001.xlsx
[19:49:38] 重复：报表\8月销售.xlsx -> _重复文件\报表__8月销售.xlsx
[19:49:38] 杂项\backup 2026.zip -> 压缩包\压缩包_20260924_001.zip
[19:49:38] 杂项\readme.txt -> 文档\文档_20260924_004.txt
[19:49:38] 照片\DSC_0001.jpg -> 图片\图片_20260924_001.jpg
[19:49:38] 重复：照片\DSC_0001_副本.jpg -> _重复文件\照片__DSC_0001_副本.jpg
[19:49:38] 照片\DSC_0002.jpg -> 图片\图片_20260924_002.jpg
[19:49:38] 照片\logo.PNG -> 图片\图片_20260924_003.png
```

核对：11 个扫描 → 9 个归档 + 2 个重复件；空文件 1 个已标出；
`logo.PNG` 大写扩展名已归一为 `.png`；`input` 目录全程未改（copy 模式）。

`mode = "move"` 另在临时目录验证过：3 个文件（含 1 组重复），
归档 2 个 + 重复 1 个，执行后 `input` 变为空，结果全部落在 `output` 对应分类下。

完整报告样例见 `tests/sample-report.txt`。

---

## 不做什么

- **不删除任何文件**。重复件只是被挑到单独的文件夹，删不删由你决定。
- 不读文件内容做识别（不做 OCR、不做图片内容分类），只按扩展名和内容指纹工作。
- 不联网、不上传。所有操作都在你自己电脑上。

---

## 要更多？

这个免费版一次整理一个文件夹。如果需要：按你们的文件命名规范定制模板、
几万个文件的批量整理、每天自动跑、整理完推送到企业微信/钉钉群，可以做定制版。

联系：邮箱 **A18926032483@outlook.com**，或在
<https://github.com/aizhang-ai/python-office-automation/issues> 开一个 Issue。

说清楚三件事就行：现在谁在做、多久做一次、文件在哪有多少。

MIT 协议，随便用、随便改。
