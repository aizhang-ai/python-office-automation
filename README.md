# 四个能直接跑的自动化小工具

都是**纯 Python 标准库**，不需要 `pip install` 任何东西，不需要服务器，不需要注册任何平台。
装了 Python 3.8 以上（[免费下载](https://www.python.org/downloads/)），双击 `run.bat` 就能用。

| 工具 | 干什么 | 谁用得上 |
|---|---|---|
| [`price-monitor/`](price-monitor/) | 每天定时看几个页面的价格，跟昨天比，**只在变了的时候**发消息到企业微信/飞书/钉钉 | 电商运营、采购、渠道管理 |
| [`table-toolkit/`](table-toolkit/) | 一堆乱表一次性弄干净：合并、去重、清洗、排序、分组汇总、按条件拆分 | 财务、运营、人事、销售 —— 任何要用 Excel 的人 |
| [`form-router/`](form-router/) | 订单 / 表单进来自动校验、去重、按规则分派负责人，异常单独挑出来 | 电商、教育、本地商家 |
| [`file-tidy/`](file-tidy/) | 乱文件夹一键整理：按扩展名分类、按模板批量重命名、按内容查重（不删原件） | 设计、法务、行政、摄影 |

---

## 为什么是纯标准库

因为要能在别人的电脑上跑起来。

一个需要 `pip install` 的工具，在非技术同事那里就卡在第一步：装不上、装错版本、公司网络限制、没管理员权限。
所以这两个工具只依赖 Python 自带的东西，**复制文件夹到任何一台装了 Python 的电脑上都能跑**。

---

## 快速开始

```bash
# 价格监控
cd price-monitor
cp config.example.json config.json    # 改成你要监控的页面
python price_monitor.py

# 表格处理
cd table-toolkit
# 把要处理的表放进 input/ 文件夹
python table_tool.py
```

Windows 用户直接双击目录里的 `run.bat` 就行。详细说明见各目录下的 `README.md`。

---

## 两个设计原则

1. **不破坏原始数据。** 表格工具从不修改 `input/` 里的原文件，所有结果写到 `output/`。
2. **不擅自访问不该访问的东西。** 价格监控默认开启 robots.txt 检查，默认每页每天只访问一次、页面之间间隔 3 秒。需要登录才能看的页面不支持，也不绕。

---

## 关于定制

不想装 Python 也能先试：**[免费在线工具](https://aizhang-ai.github.io/python-office-automation/tools/)**，
表格清洗、CSV↔JSON、JSON 格式化、正则测试、文本差异对比、图片压缩，纯浏览器里跑，数据不上传服务器。

这几个工具是通用版本。如果你的场景不一样——不同的数据格式、不同的通知方式、不同的触发时机——可以按你的流程改。

- 一般几千元一件，24–48 小时交付
- 首单支持**先做一个能跑的给你看，验收通过再谈钱**
- 用不上的场景会直接告诉你用不上

联系方式：邮箱 **A18926032483@outlook.com**，或者直接在
[GitHub 上开一个 Issue](https://github.com/aizhang-ai/python-office-automation/issues) 留言。

---

## 许可

MIT。见 [LICENSE](LICENSE)。可以随便用、随便改，商用也行，不用打招呼。
