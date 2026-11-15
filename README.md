<p align="center"><strong>中文</strong> · <a href="README_en.md">English</a> · <a href="README_ru.md">Русский</a> · <a href="README_ja.md">日本語</a></p>

<div align="center">

<h1><img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/logo.png" width="192" alt="Schedule Assistant Logo"><br>Schedule Assistant 日程提醒助手</h1>

**你的贴心日程管家** —— 早安播报 · 习惯提醒 · LLM 日程管理 · Apple 日历双向同步 · Notion 待办同步

[![Version](https://img.shields.io/badge/version-2.2.0-blue.svg)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/stargazers)
[![Issues](https://img.shields.io/github/issues/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues)

[核心特性](#核心特性) • [功能概览](#功能概览) • [快速开始](#快速开始) • [配置项说明](#配置项说明) • [LLM 可调用工具](#llm-可调用工具) • [更新日志](CHANGELOG.md)

</div>

> 本项目由 AI 编写 · 插件 Logo 来源于 Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **全托管定时推送** | 提醒文本由 AstrBot 主 Agent 按目标会话的人格与历史生成，再经 `send_message_to_user` 发出，纯文本 |
| **每日早安播报** | 天气 + 未来 24 小时日程（本地与 Apple）+ Notion 待办，一条消息搞定起床信息 |
| **智能习惯提醒** | 洗澡 / 睡觉 / 喝水定时提醒，时间与开关可配置 |
| **日程智能提醒** | 日程开始前 N 分钟推送，结合日程备注生成自然语言提醒 |
| **LLM 日程管理** | 动嘴管日程：新增 / 删除 / 查询 / 修改；模型把口语时间转成 ISO 参数 |
| **Apple 日历双向同步** | iCloud CalDAV 读取 + 写入，自动去重与增量更新 |
| **Notion 待办同步** | 早安播报中附 DDL 倒计时（还剩 N 天 / 今天截止 / 已逾期） |

---

## 功能概览

### 推送方式

定时提醒由 AstrBot 的主动 Agent 机制完成：插件只负责按时刻整理数据、写好任务说明，交给框架的 `active job`；框架唤醒目标会话的主 Agent，由它沿用该会话的人格与历史生成正文，并调用 `send_message_to_user` 发送。因此提醒语气会跟随你为机器人配置的人格，不需要在插件里另设人设。

推送全部为纯文本。投递失败按本次丢失处理，不自动重试，也不会重复补发。

### 每日早安播报

每天早上自动推送（时间可配置）：

- 天气实况与预报
- 今天（以及从播报时刻起 24 小时内）的本地日程与 Apple 日程，自动合并去重
- Notion 待办与 DDL 倒计时
- 全天日程只统计播报当天

内置提示词只给出任务与数据，不设字数或输出约束；自定义提示词会整段接管内置模板。

### 习惯提醒

| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 洗澡提醒 | 22:00 | 提醒时间可配置 |
| 睡觉提醒 | 23:00 | 提醒时间可配置 |
| 喝水提醒 | 每 90 分钟 | 9:30–21:30 时段内按间隔提醒 |
| 日程智能提醒 | 提前 N 分钟 | 默认关闭，开启后按开始时间推送 |

### Apple iCloud 日历双向同步

**读取（Apple → 本地）**：
- 定时拉取 iCloud 日历事件到本地存储
- 自动同步新增 / 修改 / 删除，以 Apple 日历为准

**写入（本地 → Apple）**：
- 通过机器人添加的日程自动写入指定 Apple 日历
- 记录事件 UID，支持后续同步识别与去重

**接入所需**：
- `username` — Apple ID 邮箱（如 `xxx@icloud.com`）
- `app_password` — **App 专用密码**（在 [appleid.apple.com](https://appleid.apple.com) 生成，不是登录密码）
- `calendar_id` — 目标日历 UUID，留空默认第一个。可用值见日志里的「可用日历」清单（形如 `工作日 → UUID`），也可从 CalDAV 地址 `…/calendars/<UUID>/` 里取 UUID 段
- `caldav_host` — CalDAV 服务器地址，留空用 `caldav.icloud.com`。中国大陆区账号被拒绝认证时可填 `caldav.icloud.com.cn`；若该地址仍不通，填网页版 iCloud 日历共享链接里自己的主机，形如 `pXX-caldav.icloud.com.cn`

### Notion 待办同步

Notion 待办会在每日早安播报中列出，并附 DDL 倒计时（还剩 N 天 / 今天截止 / 已逾期）。需先配置 Maton Gateway 作为中间层接入。

---

## 快速开始

### 第一步：安装日程提醒助手

AstrBot WebUI → 插件市场 → 搜索 `schedule_assistant`

> **提示：** 依赖声明在插件 `requirements.txt`（`aiohttp` / `python-dateutil`）：AstrBot 加载与安装插件时会自动预检并补齐缺失依赖，通常无需手动安装。

### 第二步：填写会话名单

在要接收提醒的会话里（私聊或群聊）发送 `/sid`，拿到该会话的 UMO。然后在 WebUI 插件配置 → **基础设置** → `user_umos` 中逐行填写：

```
qq:FriendMessage:123456789
qq:GroupMessage:987654321
```

`平台:消息类型:会话 ID`（UMO 格式）一行搞定「提醒哪个会话 + 从哪个平台发」。格式不符的条目会在启动时告警一次并跳过。

群聊被视为独立用户：群内成员共享同一份日程，早安、洗澡、睡觉、喝水等推送都会发到群里，日程提醒与工具也作用于该群。填写前请确认群成员都知情。

### 第三步（可选）：配置 Notion 同步

1. 在 [Maton](https://www.maton.ai/) 上接入 Notion（OAuth2 方式），生成 **Maton API Key**
2. 插件配置 → **外部服务** 填入 `maton_api_key`，并用 `notion_db_ids` 指定要读取的数据库（如 `事务:xxx`、`阅读:yyy`）

> **注意：** Notion 待办经第三方网关 `gateway.maton.ai` 中转（非直连 Notion 官方 API）：`maton_api_key` 会作为请求头发送给该第三方，其可读取你指定数据库中的标题、状态与截止日期等字段。

---

## 配置项说明

### 基础设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `user_umos` | list | `[]` | 接收自动提醒的会话 UMO 列表，每行一个 `platform:message_type:session` |

### 日程提醒设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enable_schedule_reminder` | bool | `false` | 日程智能提醒开关（默认关闭） |
| `schedule_reminder_minutes` | int | `10` | 日程提前提醒分钟数（全天日程不提醒） |

### 习惯提醒设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enable_morning_report` | bool | `true` | 早安播报开关 |
| `morning_report_time` | string | `09:00` | 早报推送时间（HH:MM） |
| `enable_bath_reminder` | bool | `true` | 洗澡提醒开关 |
| `bath_time` | string | `22:00` | 洗澡提醒时间 |
| `enable_sleep_reminder` | bool | `true` | 睡觉提醒开关 |
| `sleep_time` | string | `23:00` | 睡觉提醒时间 |
| `enable_water_reminder` | bool | `true` | 喝水提醒开关 |
| `water_interval` | int | `90` | 喝水间隔（分钟） |
| `water_start_time` | string | `09:30` | 喝水开始时间 |
| `water_end_time` | string | `21:30` | 喝水结束时间 |

### 日历同步设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enable_apple_calendar_sync` | bool | `false` | Apple 日历双向同步开关 |
| `apple_calendar_sync_interval` | int | `30` | Apple 日历同步间隔（分钟） |
| `apple_calendar.username` | string | - | Apple ID 邮箱 |
| `apple_calendar.app_password` | string | - | **App 专用密码**（非登录密码） |
| `apple_calendar.caldav_host` | string | - | CalDAV 服务器地址，留空用 `caldav.icloud.com`；国区账号可填 `caldav.icloud.com.cn`，或分区主机 `pXX-caldav.icloud.com.cn` |
| `apple_calendar.calendar_id` | string | - | 目标日历 UUID，留空默认第一个；可用值见日志的「可用日历」清单（`工作日 → UUID`） |
| `webcal_urls` | list | `[]` | WebCal 共享日历链接 |

> **WebCal 订阅安全：** `webcal_urls` 只接受公网 `https://` 订阅地址（`webcal://` 自动转 `https://`）。插件会拒绝 `localhost`、内网（如 `192.168.x` / `10.x`）、云元数据（`169.254.169.254`）等地址（防 SSRF）。请勿填写内网或本机地址。

> 写入开关统一使用顶层的 `enable_apple_calendar_sync`，开启后本地创建/删除的日程会自动同步到 Apple 日历。

### 外部服务设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `maton_api_key` | string | `""` | Maton API Key（Notion 功能必需） |
| `notion_db_ids` | list | `[]` | Notion 数据库 ID 列表，格式：`["事务:xxx", "阅读:yyy"]` |
| `weather_api_key` | string | `""` | 心知天气 API Key（[seniverse.com](https://seniverse.com)） |
| `weather_city` | string | `北京` | 天气查询城市（默认：北京） |

### 提醒提示词

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `prompt_morning` | string | `""` | 早安播报提示词。占位符：`{date} {weekday} {weather_current} {weather_forecast} {agenda} {notion_todos}` |
| `prompt_bath` | string | `""` | 洗澡提醒提示词。占位符：`{current_time}` |
| `prompt_sleep` | string | `""` | 睡觉提醒提示词。占位符：`{current_time}` |
| `prompt_water` | string | `""` | 喝水提醒提示词。占位符：`{current_time}` |
| `prompt_schedule` | string | `""` | 日程提醒提示词。占位符：`{item_title} {time_label} {ahead_label} {item_context}` |

> 留空时使用内置模板（任务说明与数据）。填写后整段接管，插件不再追加任何约束；纯文本推送，可自行在提示词里写明表达要求。

### 快速配置模板

在 WebUI 配置面板填写，或参考以下结构（`data/config/schedule_assistant_config.json`）：

```json
{
  "basic_settings": {
    "user_umos": ["qq:FriendMessage:123456789", "qq:GroupMessage:987654321"]
  },
  "schedule_reminder_settings": {
    "enable_schedule_reminder": false,
    "schedule_reminder_minutes": 10
  },
  "habit_reminder_settings": {
    "enable_morning_report": true,
    "morning_report_time": "09:00",
    "enable_bath_reminder": true,
    "bath_time": "22:00",
    "enable_sleep_reminder": true,
    "sleep_time": "23:00",
    "enable_water_reminder": true,
    "water_interval": 90,
    "water_start_time": "09:30",
    "water_end_time": "21:30"
  },
  "calendar_sync_settings": {
    "enable_apple_calendar_sync": false,
    "apple_calendar_sync_interval": 30,
    "apple_calendar": {
      "username": "",
      "app_password": "",
      "caldav_host": "",
      "calendar_id": ""
    },
    "webcal_urls": []
  },
  "external_services_settings": {
    "maton_api_key": "",
    "notion_db_ids": [],
    "weather_api_key": "",
    "weather_city": "北京"
  },
  "prompt_settings": {
    "prompt_morning": "",
    "prompt_bath": "",
    "prompt_sleep": "",
    "prompt_water": "",
    "prompt_schedule": ""
  }
}
```

---

## LLM 可调用工具

插件注册 4 个 LLM 工具，模型会自动判断何时调用，你只需用自然语言说需求：

> **时间写法：** ISO 8601。带时间用 `2026-09-10 14:30`，全天用 `2026-09-10` 并置 `all_day=true`。开始时间不能早于当前时间，年份不能晚于 2100。

```
用户: 帮我加个明天早上9点开组会的日程
-> create_schedule(title=组会, start=2026-09-11 09:00)
   已创建日程「组会」，时间：09-11 09:00 ✅

用户: 明天9点到11点开组会
-> create_schedule(title=组会, start=2026-09-11 09:00, end=2026-09-11 11:00)
   已创建日程「组会」，时间：09-11 09:00-11:00 ✅

用户: 后天全天团建
-> create_schedule(title=团建, start=2026-09-12, all_day=true)
   已创建日程「团建」，时间：09-12 全天 ✅

用户: 把下午3点的会议改到4点
-> update_schedule(title_keyword=会议, new_start=2026-09-11 16:00)
   已修改日程：时间改为09-11 16:00 ✅

用户: 看看这周有什么安排
-> list_schedules(days=7)
   📋 接下来7天日程（共3个）：

   ━━━ 08-17 周一 ━━━
     ⏰ 09:00 │ 组会

用户: 删除明天的读书会
-> delete_schedule(title_keyword=读书会)
   已删除日程「读书会」✅
```

### create_schedule
创建新日程。

| 参数 | 类型 | 说明 |
|------|------|------|
| `title` | string | **必填**，日程标题/内容 |
| `start` | string | **必填**，ISO 8601 开始时间（`2026-09-10 14:30`）；全天日程可直接给日期 `2026-09-10` |
| `end` | string? | 可选，ISO 8601 结束时间；不填为单时间点（Apple 日历按开始后 1 小时） |
| `all_day` | bool? | 是否全天日程 |
| `description` | string? | 可选备注描述 |

### delete_schedule
删除日程。支持按 ID 精确匹配或按标题关键词模糊匹配。

| 参数 | 类型 | 说明 |
|------|------|------|
| `schedule_id` | string? | 日程 ID（精确匹配） |
| `title_keyword` | string? | 标题关键词（模糊匹配，如「开会」「组会」） |

### list_schedules
查看日程列表。

| 参数 | 类型 | 说明 |
|------|------|------|
| `days` | int? | 查看最近几天的日程，默认 7 天 |

### update_schedule
修改日程。可单独或组合更新标题、时间、备注。

| 参数 | 类型 | 说明 |
|------|------|------|
| `schedule_id` | string? | 日程 ID（精确匹配） |
| `title_keyword` | string? | 标题关键词（模糊匹配） |
| `new_title` | string? | 新标题 |
| `new_start` | string? | 新开始时间（ISO 8601） |
| `new_end` | string? | 新结束时间（ISO 8601），需与 `new_start` 一起给 |
| `new_all_day` | bool? | 是否改为全天日程 |
| `new_description` | string? | 新备注 |

## 更新日志

> **[查看完整更新日志 →](CHANGELOG.md)**

## 支持与致谢

如果这个插件对你有帮助，欢迎点亮 Star，有问题和建议请提交 [Issue](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues) 或 [Pull Request](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/pulls)。

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) 开源聊天机器人框架
- 插件 Logo 来源于 Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

## 许可证与作者

本项目采用 **MIT License** 开源协议。

[@OMSociety](https://github.com/OMSociety)
