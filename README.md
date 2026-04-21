# Schedule Assistant 日程助手

> 🤖 **AI Generated** — 本插件由 AI 编写

> 图标 Pixiv ID: [130776279](https://www.pixiv.net/artworks/130776279)

你的贴心日程管家，支持 Apple 日历双向同步、Notion 待办、日程 LLM 智能提醒

---

## 功能一览

### ☀️ 每日早报
每天早上自动推送（可配置时间）：
- 天气情况（当前天气、预报、温差、降水概率）
- **今日** Apple 日历事件
- 本地日程列表
- Notion 待办事项（**DDL 倒计时**：还剩N天 / 今天截止 / 已逾期）
- 贴心建议（结合熬夜检测和 Live Dashboard 状态智能生成）

### 🔔 习惯提醒
| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 🚿 洗澡提醒 | 22:00 | 可推迟、可临时改时间 |
| 😴 睡觉提醒 | 23:00 | 智能催睡，超时带吐槽 |
| 💧 喝水提醒 | 每90分钟 | 9:30–21:30 循环，可跳过 |
| 📅 日程提醒 | 提前 N 分钟 | **LLM 生成**自然语言提醒，结合上下文 |

**智能特性：**
- 支持"只改今天"的临时调整
- 结合 Live Dashboard 状态生成个性化提醒文案
- 防重入机制避免重复提醒

### 📝 日程管理（自然语言）
- `添加日程：明天上午10点开组会`
- `删除开组会`
- `查看我的日程`
- `推迟组会20分钟`
- `今天洗澡改到23点`

### 🍎 Apple iCloud 日历双向同步
**读取（Apple → 本地）：**
- 配置 `enable_apple_calendar_sync`，定时拉取 iCloud 日历事件到本地
- 以 Apple 日历为准，自动同步（新增/修改/删除本地）

**写入（本地 → Apple）：**
- 通过机器人添加的日程，自动写入指定 Apple 日历
- 记录事件 UID，支持后续同步识别

**接入方式：**
- `username`：Apple ID 邮箱（如 `xxx@qq.com`）
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

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `enable_schedule_reminder` | bool | `false` | 开启日程 LLM 智能提醒 |
| `schedule_reminder_minutes` | int | `10` | 日程提前提醒分钟数 |
| `enable_apple_calendar_sync` | bool | `false` | 开启 Apple 日历双向同步 |
| `apple_calendar_sync_interval` | int | `30` | Apple 日历同步间隔（分钟） |
| `enable_morning_report` | bool | `true` | 开启早安播报 |
| `morning_report_time` | string | `09:00` | 早报推送时间（HH:MM） |
| `enable_bath_reminder` | bool | `true` | 开启洗澡提醒 |
| `bath_time` | string | `22:00` | 洗澡提醒时间 |
| `enable_sleep_reminder` | bool | `true` | 开启睡觉提醒 |
| `sleep_time` | string | `23:00` | 睡觉提醒时间 |
| `enable_water_reminder` | bool | `true` | 开启喝水提醒 |
| `water_interval` | int | `90` | 喝水间隔（分钟） |
| `water_start_time` | string | `09:30` | 喝水开始时间 |
| `water_end_time` | string | `21:30` | 喝水结束时间 |
| `weather_api_key` | string | — | 心知天气 API Key（[seniverse.com](https://seniverse.com)） |
| `weather_city` | string | `杭州` | 天气查询城市 |
| `maton_api_key` | string | — | Maton API Key（Notion 功能必需） |
| `transaction_db_id` | string | — | Notion 事务库 ID |
| `reading_db_id` | string | — | Notion 阅读库 ID（可选） |
| `whitelist_qq_ids` | list | `[]` | 白名单 QQ 号，只有这些账号能收到提醒 |

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
│   ├── weather.py            # 心知天气 API（带30分钟缓存）
│   ├── notion.py             # Notion 服务（5分钟断路器）
│   ├── dashboard.py          # Live Dashboard 状态获取（单例）
│   └── llm.py                # LLM 封装（fallback + 人格注入）
└── reminders/                # 提醒服务层
    ├── bath.py               # 洗澡提醒（含 fallback）
    ├── sleep.py              # 睡觉提醒（含 fallback）
    ├── water.py              # 喝水提醒（含 fallback + 自动续期）
    ├── briefing.py           # 每日早安播报（LLM 生成）
    └── schedule.py           # 日程 LLM 智能提醒
```

---

## LLM 工具一览

| 工具名 | 说明 |
|--------|------|
| `add_schedule` | 添加日程或习惯；支持 `HH:MM` 或 `YYYY-MM-DD HH:MM` |
| `remove_schedule` | 删除日程或习惯（模糊匹配，命中首项即删除） |
| `list_schedules` | 查看当前用户所有日程和习惯 |
| `snooze_schedule` | 推迟日程或习惯提醒 |
| `temp_override_habit` | 临时修改习惯提醒时间（仅今天生效） |
| `get_notion_tasks` | 查看 Notion 未完成待办 |
| `skip_water` | 跳过本次喝水提醒 |

### 工具边界说明
- 单次日程触发后会自动关闭，避免重复提醒
- `snooze_schedule` 仅改变下次触发时间，不改变原始 `time` 字段
- 自动提醒仅发送给 `whitelist_qq_ids` 中的账号
- 日程提醒由 LLM 生成，结合 Dashboard 状态和对话上下文

---

## 常见问题

**Q: Notion 待办同步不工作？**
- 确认 api-gateway Skill 已启用且 Maton API Key 配置正确
- 确认 Maton 后台 Notion OAuth 连接状态为 **ACTIVE**
- 确认插件中 `transaction_db_id` 填写了正确的数据库 ID

**Q: 没收到早报？**
- 检查 `whitelist_qq_ids` 是否包含你的 QQ 号
- 确认 Bot 在早报时间在线
- 确认 `enable_morning_report` 为 `true`

**Q: Apple 日历同步失败？**
- 确保 App 专用密码在 [appleid.apple.com](https://appleid.apple.com) 正确生成，且账号已开启两步验证
- 确认 `enable_apple_calendar_sync` 为 `true`
- 检查日志中 `[AppleCalendar]` 相关错误信息

**Q: 日程 LLM 提醒不生效？**
- 确认 `enable_schedule_reminder` 为 `true`
- 确认 Maton API Key 已配置（LLM 调用需要）

**Q: 想改喝水提醒间隔？**
- 修改 `water_interval` 配置项，单位为分钟
