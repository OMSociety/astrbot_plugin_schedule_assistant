# Schedule Assistant 日程助手

[![Version](https://img.shields.io/badge/version-v2.0.0-blue.svg)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

你的贴心日程管家，支持早安播报、习惯提醒、LLM 智能日程管理、Apple 日历双向同步、Notion 待办同步。

> 本项目由AI编写
> 
> 插件 Logo 来源于 Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

[快速开始](#-快速开始) • [功能概览](#-功能概览) • [配置项](#-配置项说明) • [LLM 工具](#-llm-可调用工具) • [更新日志](CHANGELOG.md)

---

## 📖 功能概览

### 每日早安播报
每天早上自动推送（可配置时间），一条消息搞定起床信息：
- 🌤️ **天气情况** — 当前温度、预报、温差、降水概率
- 📅 **今日日程** — Apple 日历已排期的事件一览
- 📝 **Notion 待办** — DDL 倒计时（还剩N天 / 今天截止 / 已逾期）
- 💡 **贴心建议** — 结合熬夜检测智能生成

### 习惯提醒
| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 🚿 洗澡提醒 | 22:00 | 可推迟、可临时改时间 |
| 😴 睡觉提醒 | 23:00 | 智能催睡，超时带吐槽 |
| 💧 喝水提醒 | 每90分钟 | 9:30–21:30 循环，可跳过 |
| 📅 日程智能提醒 | 提前 N 分钟 | **LLM 生成**自然语言提醒，结合上下文 |

### 日程管理
支持自然语言操作日程，动动嘴就能管日程：
```
用户: 帮我加个明天早上9点开组会的日程
用户: 把下午3点的会议改到4点
用户: 删除明天的读书会
用户: 看看这周有什么安排
```

注册 4 个 LLM 工具：`create_schedule` / `delete_schedule` / `list_schedules` / `update_schedule`，支持时间解析与标题关键词匹配。

### Apple iCloud 日历双向同步

**读取（Apple → 本地）：**
- 定时拉取 iCloud 日历事件到本地存储
- 自动同步新增 / 修改 / 删除，以 Apple 日历为准

**写入（本地 → Apple）：**
- 通过机器人添加的日程自动写入指定 Apple 日历
- 记录事件 UID，支持后续同步识别与去重

**接入所需：**
- `username` — Apple ID 邮箱（如 `xxx@icloud.com`）
- `app_password` — **App 专用密码**（在 [appleid.apple.com](https://appleid.apple.com) 生成，不是登录密码）
- `calendar_id` — 目标日历 UUID 或名称（如「日程」），留空默认第一个

### Notion 待办同步
每小时检查一次 Notion 事务库，DDL 临近（24小时内）时私信提醒。需要先配置 Maton Gateway 作为中间层接入。

### Markdown 渲染
所有定时播报（早安 / 习惯 / 日程提醒）走统一渲染管线，按平台自动降级：
- **native** — 平台原生解析 md（qq_official、discord、telegram 等），原文直发
- **plain** — 不支持原生 md 的平台自动 strip 降级为纯文本

QQ 原生表格自动渲染为对齐行，无需额外配置；可在配置中关闭或强制切换。

---

## 🚀 快速开始

### 第一步：配置 api-gateway Skill（如需 Notion 功能）

日程助手通过 Maton Gateway 读写 Notion，需要先配置：

1. 在 [Maton](https://www.maton.ai/) 上接入 Notion（OAuth2 方式），生成 **Maton API Key**
2. 下载 [api-gateway-skill](https://github.com/maton-ai/api-gateway-skill)，在配置中填入你的 Maton API Key
3. AstrBot 管理面板 → **Skills** → 上传 api-gateway-skill 并启用

### 第二步：安装日程助手

**方式一：插件市场**
- AstrBot WebUI → 插件市场 → 搜索 `schedule_assistant`

**方式二：手动安装**
- 将插件文件夹放入 `/AstrBot/data/plugins/`
- 重启 AstrBot
- 在管理面板按需配置各项参数

### 依赖安装
核心依赖已集成在 AstrBot 环境中，无需额外安装。

---

## ⚙️ 配置项说明

### 基础设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `persona_id` | string | `""` | LLM 人设 ID（对应配置文件中的 `persona_id`），留空自动从会话获取 |
| `user_nickname` | string | `""` | 用户昵称，留空则播报称呼为「主人」 |
| `admin_uids` | list | `[]` | 管理员用户 ID 列表（QQ 号或平台用户 ID，用于权限校验） |

### 日程提醒设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enable_schedule_reminder` | bool | `false` | 日程 LLM 智能提醒开关（默认关闭） |
| `schedule_reminder_minutes` | int | `10` | 日程提前提醒分钟数（日程开始前多少分钟提醒，全天日程不提醒） |
| `schedule_reminder_check_interval` | int | `5` | 日程提醒扫描间隔（分钟），建议设为提前量的 1/3~1/2（如提前10分钟则间隔3-5分钟），最小值2分钟 |

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
| `apple_calendar.calendar_id` | string | - | 目标日历 UUID 或名称，留空默认第一个 |
| `webcal_urls` | list | `[]` | WebCal 共享日历链接 |

> 写入开关统一使用顶层的 `enable_apple_calendar_sync`，开启后本地创建/删除的日程会自动同步到 Apple 日历。

### 外部服务设置

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `maton_api_key` | string | Maton API Key（Notion 功能必需） |
| `notion_db_ids` | list | Notion 数据库 ID 列表，格式：`["事务:xxx", "阅读:yyy"]` |
| `weather_api_key` | string | 心知天气 API Key（[seniverse.com](https://seniverse.com)） |
| `weather_city` | string | 天气查询城市（默认：杭州） |

### 消息推送设置

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `user_ids` | list | 用户名单 ID 列表，每行一个接收自动提醒的用户 ID（QQ 号或平台 UID，支持 UMO 格式） |
| `default_session_type` | string | 默认会话类型 |
| `send_platform_id` | string | 默认发送平台 ID |
| `user_platform_bindings` | list | 用户平台绑定列表，格式 `用户ID:会话类型:平台实例ID`（如 `12345:FriendMessage:qq_official`） |

### 消息渲染设置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `markdown_enabled` | bool | `true` | 全局 Markdown 渲染开关，关闭后降级为纯文本 |
| `markdown_native_platforms` | list | `[]` | 额外追加原生解析 Markdown 的平台 ID |
| `qq_markdown_enabled` | bool | 留空 | QQ 平台开关：留空跟随全局；`false` 强制 QQ 不走原生 md |

---

## 🧩 架构

### 定时消息引擎（engine.py）
「定时触发」与「内容生成/发送」解耦：
- 业务通过 `register_job` 注册，`content_provider` 只负责生成内容，发送统一走 MessagingService
- 特殊任务（喝水重排、Apple 同步等）用 `register_raw_job` 注册自定义 handler
- 触发方式：`CronTrigger` 实例 / `"HH:MM"` 每日定时 / `"interval:N"` 每 N 分钟

### Markdown 渲染管线（markdown.py）
两级降级策略，`render` 返回 `(content, kind)`：
- `native`：平台原生解析 md，原文直发（qq_official / discord / telegram / slack / kook 等，可用 `markdown_native_platforms` 追加）
- `plain`：strip 降级为纯文本
- 依赖均为惰性导入，未启用时零开销

---

## 🛠️ LLM 可调用工具

### create_schedule
创建新日程。

| 参数 | 类型 | 说明 |
|------|------|------|
| `title` | string | **必填**，日程标题/内容 |
| `datetime_str` | string | **必填**，支持自然语言时间，如「明天9点」「后天下午3点」「2024-01-15 14:30」 |
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
| `days` | int? | 查看最近几天的日程，默认7天 |

### update_schedule
修改日程。可单独或组合更新标题、时间、备注。

| 参数 | 类型 | 说明 |
|------|------|------|
| `schedule_id` | string? | 日程 ID（精确匹配） |
| `title_keyword` | string? | 标题关键词（模糊匹配） |
| `new_title` | string? | 新标题 |
| `new_datetime` | string? | 新时间，支持自然语言 |
| `new_description` | string? | 新备注 |

---

## 📝 更新日志

> 📋 **[查看完整更新日志 →](CHANGELOG.md)**

---

## 🤝 贡献与反馈

如遇问题请在 [GitHub Issues](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues) 提交，欢迎 Pull Request！

---

## 📜 许可证

本项目采用 **MIT License** 开源协议。

---

## 👤 作者

**OMSociety** — [@OMSociety](https://github.com/OMSociety)
