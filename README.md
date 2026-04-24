# Schedule Assistant 日程助手

> 🤖 **AI Generated** — 本插件由 AI 编写

> 图标 Pixiv ID: [130776279](https://www.pixiv.net/artworks/130776279)
你的贴心日程管家，支持 Apple 日历双向同步、Notion 待办、日程 LLM 智能提醒、Live Dashboard 视奸面板

---

## 功能一览

### ☀️ 每日早报
每天早上自动推送（可配置时间）：
- 天气情况（当前天气、预报、温差、降水概率）
- 今日日程（Apple日历）
- Notion 待办事项（**DDL 倒计时**：还剩N天 / 今天截止 / 已逾期）
- 贴心建议（结合熬夜检测和 Live Dashboard 状态智能生成）

### 🔔 习惯提醒
| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 🚿 洗澡提醒 | 22:00 | 可推迟、可临时改时间 |
| 😴 睡觉提醒 | 23:00 | 智能催睡，超时带吐槽 |
| 💧 喝水提醒 | 每90分钟 | 9:30–21:30 循环，可跳过 |
| 📅 日程提醒 | 提前 N 分钟 | **LLM 生成**自然语言提醒，结合上下文 |

### 📝 日程管理
**支持自然语言操作日程：**
```
用户: 帮我加个明天早上9点开组会的日程
用户: 把下午3点的会议改到4点
用户: 删除明天的读书会
用户: 看看这周有什么安排
```

### 📊 Live Dashboard 视奸面板
**实时查询设备状态：**
- 查询当前设备在线情况
- 显示应用名、窗口标题
- 电量与充电状态
- 音乐播放信息
- **黑名单机制**：用户/群组/信息黑名单

**使用方式：**
```
/视奸
/live
/dashboard
/设备状态
```

**LLM 工具**：`query_live_dashboard_status` — 在对话中自动调用查询

> [!NOTE]
> Live Dashboard 功能由 [astrbot_plugin_live_dashboard](https://github.com/DBJD-CR/astrbot_plugin_live_dashboard) 合并而来，感谢原作者 DBJD-CR 的贡献！

### 🍎 Apple iCloud 日历双向同步
**读取（Apple → 本地）：**
- 配置 `enable_apple_calendar_sync`，定时拉取 iCloud 日历事件到本地
- 以 Apple 日历为准，自动同步（新增/修改/删除本地）

**写入（本地 → Apple）：**
- 通过机器人添加的日程，自动写入指定 Apple 日历
- 记录事件 UID，支持后续同步识别

**接入方式：**
- `username`：Apple ID 邮箱（如 `xxx@icloud.com`）
- `app_password`：**App 专用密码**（不是登录密码！在 [appleid.apple.com](https://appleid.apple.com) 生成）
- `calendar_id`：目标日历 UUID 或名称（如「日程」），留空默认第一个

### 📋 Notion 待办同步
每小时检查一次 Notion 事务库，DDL 临近（24小时内）时私信提醒。

---

## 安装

### 第一步：安装 AstrBot api-gateway Skill（如需使用 Notion 数据库功能）

日程助手通过 Maton Gateway 读写 Notion，需要先配置：

1. 在 [Maton](https://www.maton.ai/) 上接入 Notion（OAuth2 方式），并生成 **Maton API Key**
2. 下载 [api-gateway-skill](https://github.com/maton-ai/api-gateway-skill)，在配置中填入你的 **Maton API Key**
3. 进入 AstrBot 管理面板 → **Skills** → 上传 api-gateway-skill

### 第二步：安装日程助手插件

1. 将插件文件夹放入 `/AstrBot/data/plugins/`
2. 重启 AstrBot
3. 在管理面板配置插件参数（参考下方配置项）

---

## 配置项

### 开关配置
| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enable_morning_report` | bool | `true` | 早安播报开关 |
| `enable_bath_reminder` | bool | `true` | 洗澡提醒开关 |
| `enable_sleep_reminder` | bool | `true` | 睡觉提醒开关 |
| `enable_water_reminder` | bool | `true` | 喝水提醒开关 |
| `enable_schedule_reminder` | bool | `false` | 日程 LLM 智能提醒开关 |
| `enable_apple_calendar_sync` | bool | `false` | Apple 日历双向同步开关 |

### 时间配置
| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `morning_report_time` | string | `09:00` | 早报推送时间（HH:MM） |
| `bath_time` | string | `22:00` | 洗澡提醒时间 |
| `sleep_time` | string | `23:00` | 睡觉提醒时间 |
| `water_interval` | int | `90` | 喝水间隔（分钟） |
| `water_start_time` | string | `09:30` | 喝水开始时间 |
| `water_end_time` | string | `21:30` | 喝水结束时间 |
| `schedule_reminder_minutes` | int | `10` | 日程提前提醒分钟数 |
| `apple_calendar_sync_interval` | int | `30` | Apple 日历同步间隔（分钟） |

### 其他配置
| 配置项 | 类型 | 说明 |
|--------|------|------|
| `weather_api_key` | string | 心知天气 API Key（[seniverse.com](https://seniverse.com)） |
| `weather_city` | string | 天气查询城市（默认：杭州） |
| `maton_api_key` | string | Maton API Key（Notion 功能必需，从 [www.maton.ai](https://www.maton.ai) 获取） |
| `notion_db_ids` | list | Notion 数据库 ID 列表，兼容两种格式：`["事务:xxx", "阅读:yyy"]` 或 `[{"name":"事务","id":"xxx"}]` |
| `whitelist_qq_ids` | list | 白名单 QQ 号，只有这些账号能收到提醒 |
| `target_user_ids` | list | 额外提醒目标用户 ID（可与白名单并用） |
| `broadcast_to_all_known_users` | bool | 是否把历史活跃用户纳入自动提醒 |
| `default_session_type` | string | 发送会话类型，默认 `FriendMessage` |
| `send_platform_id` | string | 默认发送平台 ID，留空则按最近会话/可用平台选择 |
| `user_platform_bindings` | list | 用户平台绑定，格式：`["123456:aiocqhttp"]` |

### Apple 日历配置（嵌套在 `apple_calendar` 下）
| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enable_sync` | bool | 启用写入（本地新建 → Apple 日历） |
| `username` | string | Apple ID 邮箱 |
| `app_password` | string | **App 专用密码**（非登录密码） |
| `calendar_id` | string | 目标日历 UUID 或名称，留空默认第一个 |

> **Note:** App 专用密码在 [appleid.apple.com](https://appleid.apple.com) → 登录 → 安全性 → 生成 App 专用密码。

---

## 文件结构
```
astrbot_plugin_schedule_assistant/
├── main.py                    # 主逻辑、定时任务调度、LLM工具
├── schedule_store.py          # 数据持久化（AstrBot Preference API）
├── notion_client.py           # Notion API 调用（通过 Maton Gateway）
├── apple_calendar.py          # Apple iCloud CalDAV 同步（读写）
├── constants.py               # 统一常量定义
├── _conf_schema.json          # 配置项 schema
├── metadata.yaml              # 插件元信息
├── logo.png                   # 插件图标
├── README.md                  # 本文档
├── CHANGELOG.md               # 更新日志
├── services/                  # 数据服务层
│   ├── weather.py             # 心知天气 API（带30分钟缓存）
│   ├── notion.py              # Notion 服务（5分钟断路器）
│   ├── dashboard.py           # Live Dashboard 状态获取（单例）
│   └── llm.py                 # LLM 封装（fallback + 人格注入）
├── commands.py                # 历史命令模块（为兼容旧结构保留，当前主流程未接入）
├── messaging.py               # 历史消息模块（为兼容旧结构保留，当前主流程未接入）
└── reminders/                 # 提醒服务层
    ├── habits.py              # 洗澡/睡觉/喝水提醒（含 fallback + 自动续期）
    ├── briefing.py            # 每日早安播报（LLM 生成）
    └── schedule.py            # 日程 LLM 智能提醒
```

---

## LLM 可调用工具

日程助手注册了 4 个 LLM 工具，支持自然语言管理日程：

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `create_schedule` | 创建日程 | title, datetime_str, description? |
| `delete_schedule` | 删除日程 | schedule_id?, title_keyword? |
| `list_schedules` | 查看日程列表 | days? |
| `update_schedule` | 修改日程 | schedule_id?, title_keyword?, new_title?, new_datetime?, new_description? |

---

## 常见问题

**Q: Notion 待办同步不工作？**
- 确认 api-gateway Skill 已启用且 Maton API Key 配置正确
- 确认 Maton 后台 Notion OAuth 连接状态为 **ACTIVE**
- 确认 `notion_db_ids` 填写了正确的数据库 ID（支持 `["事务:xxx"]` 或 `[{"name":"事务","id":"xxx"}]`）

**Q: 没收到早报？**
- 检查 `whitelist_qq_ids` 是否包含你的 QQ 号
- 确认 Bot 在早报时间在线
- 确认 `enable_morning_report` 为 `true`

**Q: Apple 日历同步失败？**
- 确保 App 专用密码在 [appleid.apple.com](https://appleid.apple.com) 正确生成，且账号已开启两步验证
- 确认 `enable_apple_calendar_sync` 为 `true`
- 复制粘贴账号和密码时避免携带多余字符（如空格、`"`、`>` 等）
- 建议将 `apple_calendar_sync_interval` 设为 `15` 分钟及以上，降低触发平台限流概率
- 检查日志中 `[AppleCalendar]` 相关错误信息

**Q: 日程 LLM 提醒不生效？**
- 确认 `enable_schedule_reminder` 为 `true`
- 确认 `schedule_reminder_minutes` 为正整数（默认 `10`）
- 确认 Maton API Key 已配置（LLM 调用需要）

**Q: 想改喝水提醒间隔？**
- 修改 `water_interval` 配置项，单位为分钟
