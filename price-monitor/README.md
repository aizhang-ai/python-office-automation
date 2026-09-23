# 价格 / 页面变化监控日报（零依赖版）

每天自动打开你指定的几个页面，把价格抓下来，和昨天的快照比对，**只在有变化的时候**给你发一条企业微信 / 飞书 / 钉钉消息，同时留一份 Excel 能打开的历史记录。

---

## 你需要准备什么

| 项目 | 要求 |
|---|---|
| Python | 3.8 或以上（[python.org](https://www.python.org/downloads/) 下载，安装时勾选 Add to PATH） |
| 其他软件 | **没有**。不用装 pip 包、不用 n8n、不用服务器、不用数据库 |
| 花费 | 0 元。脚本跑在你自己的电脑上 |

> 不需要任何境外服务（不用 Gmail / Slack / Google Sheets），国内网络直接可用。

---

## 三步跑起来

**第 1 步**：把 `config.example.json` 复制一份，改名成 `config.json`。

**第 2 步**：用记事本打开 `config.json`，把 `targets` 改成你要监控的页面：

```json
"targets": [
  {
    "name": "竞品A-主力款",
    "url": "https://对方的公开商品页地址",
    "price_regex": ""
  }
]
```

- `name`：你自己看得懂的名字，会显示在日报里
- `url`：要监控的**公开**页面地址（详见下方合规说明）
- `price_regex`：一般留空就行。如果抓出来的价格不对（比如抓到了别人的市场价），再填自定义正则，例如 `"class=\"price\">([0-9.]+)"`

**第 3 步**：双击 `run.bat`。（或在命令行里执行 `python price_monitor.py`）

第一次运行会记录下当前价格作为基准，从第二天开始才有"变化"可比。

---

## 让它每天自动跑

**Windows**：Win 键搜索「任务计划程序」→ 创建基本任务 → 触发器选「每天」→ 操作选「启动程序」：
- 程序填：本文件夹里的 `run.bat` 的完整路径
- 起始位置填：本文件夹的路径

不想点界面，也可以在命令行里执行（把路径换成你自己的）：

```
schtasks /create /tn "价格监控" /tr "D:\tools\price-monitor\run.bat" /sc daily /st 09:00
```

**Linux / macOS**：`crontab -e` 加一行

```
0 9 * * * cd /path/to/price-monitor && /usr/bin/python3 price_monitor.py
```

---

## 收到告警：配置机器人（可选，不配也能用）

不配也能跑——日报会存在 `reports/` 文件夹里，你自己看。要推送到群里，在 `config.json` 里填 `webhook`：

| 类型 | `type` 填 | webhook 地址在哪拿 |
|---|---|---|
| 企业微信 | `wecom` | 群设置 → 群机器人 → 添加 → 复制 Webhook 地址 |
| 飞书 | `feishu` | 群设置 → 群机器人 → 添加自定义机器人 |
| 钉钉 | `dingtalk` | 群设置 → 智能群助手 → 添加机器人 → 自定义 |

```json
"webhook": { "type": "wecom", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" }
```

只想"有变化才发消息"，就保持 `"push_only_on_change": true`；想每天都收到一份日报，改成 `false`。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `price_monitor.py` | 主程序，不用改它 |
| `config.json` | 你的监控清单（自己建） |
| `config.example.json` | 配置模板 |
| `run.bat` | Windows 双击运行 |
| `history.csv` | 每次运行的快照，Excel 直接能打开，可做趋势图 |
| `reports/report-日期.txt` | 当天的日报文本 |
| `tests/` | 试跑用的样例页面与本脚本的实测输出 |

常用参数：
```
python price_monitor.py            # 正常运行
python price_monitor.py --no-push  # 只跑不推送
python price_monitor.py --verbose  # 打印抓到的候选价格，用来调 price_regex
```

---

## 合规说明（请务必遵守）

- 只监控**公开可访问**的页面。需要登录后才能看的内容，本脚本不支持，也不应去绕。
- 默认开启 **robots.txt 检查**（`respect_robots: true`）：对方不允许抓取的页面会自动跳过，日报里标记为「robots 禁止抓取」。请不要把它改成 false 去抓禁止抓取的站点。
- 默认每个页面之间**间隔 3 秒**、每天只跑一次，属于正常人工访问量级。请不要把间隔改成 0 去高频请求。
- 抓来的数据只供你自己做经营参考，不要转售、不要公开发布他人的价格数据。

---

## 常见问题

**Q：抓不到价格 / 抓到的价格不对？**
先用 `--verbose` 跑一次，看它抓到了哪些候选价格。真不对就在 `targets` 里给那一项填 `price_regex`。

**Q：页面里的价格是图片，或者要 JS 渲染才有？**
纯静态抓取拿不到。这种情况需要改用带浏览器的方案，属于定制开发，不在本包范围内。

**Q：对方改版了怎么办？**
页面结构变了价格就可能抓不到，日报里会出现「未匹配到价格」。改 `price_regex` 即可，或购买月度维护由我们跟进。

**Q：数据存在哪？会不会上传到你们服务器？**
全部存在你自己的电脑上（`history.csv` 和 `reports/`），本脚本不向任何第三方发送数据，唯一的外发请求就是你自己填的机器人 webhook。

**Q：能同时监控多少个页面？**
默认配置下几十个没问题。页面多的话把 `request_delay_seconds` 调大一点（比如 5），对对方站点更友好。

---

## 实测记录

2026-09-23 在 Windows + Python 3.13 上实测通过：

| 场景 | 结果 |
|---|---|
| 首次运行 | 正确提取 ¥199.00（页面里出现 2 次，压过只出现 1 次的市场价 ¥299.00），标记为「首次记录」 |
| 价格改为 ¥159.00 后再运行 | 正确识别为「有变化」，日报显示 ¥199.00 -> ¥159.00 |
| 目标域名不存在 | 标记为「抓取失败」并写明原因，不中断其他目标的监控 |
| 页面能打开但没有价格 | 标记为「未匹配到价格」并提示检查正则（区别于真正的抓取失败） |

样例输出见 `tests/sample-report.txt` 与 `tests/sample-history.csv`。

---

*本文件随程序一同交付。价格与条款以报价单为准。*
