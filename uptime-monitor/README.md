# 网站 / 接口可用性监控告警

你的网站或接口挂了，你是从客户嘴里知道的，还是自己先知道的？

这个工具按你设定的间隔去访问一批地址，记录状态码和耗时，发现打不开就重试，
重试还是不行、连续失败到阈值才判定为「故障」并告警，恢复的时候再告诉你一声。
**只在状态翻转时告警**，不会每分钟刷你的群。

- 纯 Python 标准库，**不用 pip 装任何东西**
- 客户只需要给一个**公开的域名或接口地址**，不用开服务器权限、不用装东西
- 告警走企业微信 / 钉钉 / 飞书的**官方群机器人 Webhook**（单向推送，不是控制客户端）

---

## 三步跑起来

**第 1 步：装 Python**（已装可跳过）
去 https://www.python.org/downloads/ 下载，安装时勾选 **Add Python to PATH**。

**第 2 步：填要监控的地址**
用记事本打开 `config.json`，把 `targets` 里的示例换成你自己的：

```json
{
  "name": "官网首页",
  "url": "https://www.example.com",
  "method": "GET",
  "expect_status": 200,
  "expect_keyword": "在线咨询"
}
```

**第 3 步：双击 `run.bat`**

跑完打开 `output\latest-report.txt` 就能看到结果。

---

## config.json 字段说明

### 全局

| 字段 | 默认 | 说明 |
|---|---|---|
| `interval_seconds` | 300 | 常驻循环时每隔多少秒跑一轮（`--loop` 生效），最低 60 秒 |
| `timeout_seconds` | 10 | 单个地址多久没响应算超时 |
| `retry` | 2 | 失败后重试几次（任一次成功就算正常） |
| `retry_wait_seconds` | 5 | 每次重试之间等几秒 |
| `fail_threshold` | 2 | 连续失败几次才判定为故障并告警 |
| `slow_ms` | 3000 | 响应超过多少毫秒在报告里提示「偏慢」 |
| `verify_ssl` | true | 证书有问题（自签名、过期）时改成 false 可跳过校验 |
| `alert` | 见下 | 告警推送配置 |

### targets 里的每一项

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 名字，报告里显示 |
| `url` | ✅ | 地址，http/https 都行 |
| `method` | | 默认 `GET`，可填 `POST` |
| `expect_status` | | 默认 `200`；也可以填数组，如 `[200, 301]` |
| `expect_keyword` | | 页面里必须包含这个词，否则算异常（防「白屏但返回 200」） |
| `headers` | | 自定义请求头，如 `{"Authorization": "Bearer xxx"}` |
| `body` | | `POST` 的请求体 |
| `timeout_seconds` / `retry` | | 单独覆盖全局设置 |

### 告警推送

默认关闭。要开启：在企业微信/钉钉/飞书群里添加一个**群机器人**，拿到官方 Webhook 地址，填进来：

```json
"alert": {
  "enabled": true,
  "type": "wecom",
  "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
}
```

`type` 填 `wecom`（企业微信）/ `dingtalk`（钉钉）/ `feishu`（飞书）。

> 说明：这是平台**官方开放**的单向推送接口，只是往群里发消息。
> 本工具不会也不去读取、控制任何聊天客户端。

---

## 命令行用法

```
python uptime_monitor.py                 按 config.json 跑一轮
python uptime_monitor.py --loop          常驻，按 interval_seconds 循环
python uptime_monitor.py --target 官网   只跑名字里含「官网」的项
python uptime_monitor.py --no-alert      本轮不推送
python uptime_monitor.py --timeout 5     临时把超时改成 5 秒
python uptime_monitor.py --config D:\my\cfg.json   用别的配置文件
```

想让它开机就跑、全天盯着：把 `run.bat` 的快捷方式放进
`C:\Users\你的用户名\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`，
并把 `run.bat` 里的命令改成 `python uptime_monitor.py --loop`。

---

## 产出文件

| 文件 | 内容 |
|---|---|
| `output/latest-report.txt` | 最近一轮的文字报告（可直接复制到群里） |
| `output/uptime-YYYY-MM-DD.csv` | 每次探测的明细，按天一个文件，可用 Excel 打开 |
| `output/state.json` | 每个地址的连续失败次数、首次故障时间、上次正常时间 |

---

## 本机实测记录

环境：**Windows + Python 3.13.12**，未安装任何第三方包。

### 测试一：本地假站点全流程（`tests/make_testdata.py`，24 项断言全过）

用标准库在本机起了 4 个接口，把四种情况全造出来，跑三轮：

| 接口 | 行为 | 结果 |
|---|---|---|
| 官网首页 | 200 + 含关键词 | 正常，关键词命中 |
| 慢接口 | 睡 1.2 秒再返回 200 | 正常，但提示「响应偏慢（阈值 800ms）」 |
| 超时接口 | 睡 5 秒（客户端超时 1 秒） | 异常，原因「超时（>1s）」 |
| 支付回调 | 前两次 500，第三次起 200 | 第 1 轮不计告警 → 第 2 轮判定故障 → 第 3 轮报「已恢复」 |

三轮真实输出摘要：

```
第 1 轮：监控 4 个地址：正常 2 / 异常 2      支付回调 异常 1/2 次，未达告警阈值
第 2 轮：监控 4 个地址：正常 2 / 异常 2      支付回调 判定故障（连续异常 2 次）  本次告警 2 条
第 3 轮：监控 4 个地址：正常 3 / 异常 1      支付回调 已恢复（此前连续异常 2 次）  本次告警 1 条
```

告警推送链路单独验证：企业微信 / 飞书两种消息体均能正确 POST 出去并收到对方回执；
未开启推送或地址为空时**不产生任何网络请求**。

跑测试：`python tests/make_testdata.py`

### 测试二：真实外网（Python 3.13.12 / Windows）

用随包自带的 `config.json` 直接跑（`python uptime_monitor.py --timeout 8`）：

```
[11:34:30]   正常  状态 200  耗时 905ms    示例-公司官网首页（https://example.com，关键词命中）
[11:34:31]   正常  状态 200  耗时 765ms    示例-百度首页（https://www.baidu.com）
[11:34:31]   异常  状态 -   耗时 127ms    示例-一定失败的地址
             原因  连接失败：[Errno 11001] getaddrinfo failed
             状态  异常 1/2 次，未达告警阈值
```

第三个地址是故意留的无效域名，用来演示「故障长什么样」。完整报告见 `tests/sample-report.txt`。

---

## 常见问题

**双击 run.bat 一闪就没了？**
多半是没装 Python 或没勾 Add Python to PATH。cmd 里敲 `python --version` 试一下。

**提示 config.json 不是合法的 JSON？**
多半是多了一个逗号或用了中文引号。复制到 https://jsonlint.com 检查一下。

**为什么挂了 5 分钟才告警？**
`fail_threshold` 默认 2 次、`retry` 默认 2 次、`interval_seconds` 默认 300 秒。
想更快就把间隔改成 60 秒、`retry` 改成 1。

**能监控需要登录的后台页面吗？**
不做。需要 Cookie / 登录态 / 验证码的属于绕过访问控制，这个工具不碰。
能做的是监控**公开可访问**的首页、接口、静态资源、健康检查地址。

**会不会把对方站点刷挂？**
间隔低于 10 秒会被程序自动抬到 60 秒。一轮只发一次请求，失败才重试。

---

## 不做什么

- 不模拟登录、不绕验证码、不绕过任何访问控制
- 不做高频轮询（最低间隔 60 秒）
- 不读取或控制企业微信 / 微信 / 钉钉客户端
- 不采集页面里的业务数据，只判断「通不通、快不快、有没有那个词」

---

## 要定制？

网页版/标准版能做的是：**定时探测 + 故障与恢复告警 + 每日可用率报表**。

定制版可以做：多地区探测、按业务接口分组告警给不同的人、可用率月度报表（含 SLA 统计）、
挂了自动跑一次重启或回滚脚本、和你的工单系统打通。

邮箱 **A18926032483@outlook.com**，
或在 https://github.com/aizhang-ai/python-office-automation/issues 开一个 Issue。
说清楚三件事就行：现在谁在盯、要盯哪些地址、告警发给谁。

---

MIT 协议，随便改，随便用。
