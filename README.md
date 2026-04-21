# Schedule Assistant 日程助手

![icon](icon.png)

> 🤖 **AI Generated** — 本插件全是AI写的
> 图标 Pixiv ID: [130776279](https://www.pixiv.net/users/130776279)

你的贴心日程管家，每日自动提醒、智能同步日历与待办事项

---

## 功能一览

### ☀️ 每日早报
每天早上 9:00（可配置）自动推送：
- 天气情况（当前天气、预报、温差、降水概率）
- **今日**日历事件（Apple 日历同步，只显示当天日程）
- 本地日程列表
- Notion 待办事项（**显示 DDL 倒计时**：还剩N天/今天截止/已逾期）
- 贴心建议（结合熬夜检测和 Live Dashboard 状态智能生成）

### 🔔 习惯提醒
| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 🚿 洗澡提醒 | 22:00 | 可推迟、可临时改时间 |
| 😴 睡觉提醒 | 23:00 | 智能催睡，超时带吐槽 |
| 💧 喝水提醒 | 每90分钟 | 9:30-21:30 循环，可跳过 |
| 📅 用户日程 | 定时扫描 | 每小时01分扫描最近65分钟窗口, 非整点时间也能触发 |

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

### 📋 Notion 待办同步
每小时检查一次 Notion 事务库，DDL 临近（24小时内）时私信提醒。

---

## 安装

### 第一步：安装 AstrBot api-gateway Skill（如需使用Notion数据库功能）

日程助手通过 Maton Gateway 读写 Notion，需要先配置Maton api-gateway：

1. 在[Maton](https://www.maton.ai/)上接入Notion（OAuth2方式），并生成**Maton API Key**
2. 下载[api-gateway-skill](https://github.com/maton-ai/api-gateway-skill)，在配置中填入你的**Maton API Key**
3. 进入 AstrBot 管理面板 → **Skills** → 上传api-gateway-skill

### 第二步：安装日程助手插件

1. 将插件文件夹放入 `/AstrBot/data/plugins/`
2. 重启 AstrBot
3. 在管理面板配置插件参数（参考下方配置项）

---

## 配置项

| 配置项 | 说明 | 获取方式 |
|--------|------|---------|
| `morning_report_time` | 早报推送时间，默认 `09:00` | — |
| `weather_api_key` | 心知天气 API Key | [seniverse.com](https://seniverse.com) 免费注册 |
| `weather_city` | 天气查询城市，默认 `杭州` | — |
| `transaction_db_id` | Notion 事务库 ID | Notion 页面链接中复制 |
| `reading_db_id` | Notion 阅读库 ID（可选） | 同上 |
| `apple_calendar_enabled` | 启用 Apple 日历同步 | `true` / `false` |
| `apple_id` | Apple ID 邮箱 | — |
| `apple_app_password` | Apple 专用密码 | [appleid.apple.com](https://appleid.apple.com) 生成 |
| `webcal_urls` | WebCal 公共日历链接列表 | iCloud 日历 → 复制公共链接 |
| `bath_time` | 洗澡提醒时间，默认 `22:00` | — |
| `sleep_time` | 睡觉提醒时间，默认 `23:00` | — |
| `water_interval` | 喝水间隔（分钟），默认 `90` | — |
| `water_start_time` | 喝水提醒开始时间，默认 `09:30` | — |
| `water_end_time` | 喝水提醒结束时间，默认 `21:30` | — |
| `enable_bath_reminder` | 开启洗澡提醒，默认 `true` | — |
| `enable_sleep_reminder` | 开启睡觉提醒，默认 `true` | — |
| `enable_water_reminder` | 开启喝水提醒，默认 `true` | — |
| `whitelist_qq_ids` | 白名单 QQ 号列表，只有这些账号能收到提醒 | 格式：`["123456"]` |

> **Note:** `maton_api_key` 已不需要在插件中单独配置，Notion 连接统一由 api-gateway Skill 管理。

---

## 文件结构

```
astrbot_plugin_schedule_assistant/
├── main.py              # 主逻辑、定时任务调度、LLM工具
├── schedule_store.py     # 数据持久化（AstrBot Preference API）
├── notion_client.py      # Notion API 调用（通过 Maton Gateway）
├── apple_calendar.py     # Apple 日历同步（WebCal）
├── dashboard.py          # Live Dashboard 状态获取
├── constants.py          # 统一常量定义
├── _conf_schema.json     # 配置项 schema
├── metadata.yaml         # 插件元信息
└── README.md             # 本文档
```

---

## LLM 工具一览

| 工具名 | 说明 |
|--------|------|
| `add_schedule` | 添加日程或习惯；支持 `HH:MM` 或 `YYYY-MM-DD HH:MM` |
| `remove_schedule` | 删除日程或习惯（模糊匹配，命中首项即删除） |
| `list_schedules` | 查看当前用户所有日程和习惯 |
| `snooze_schedule` | 推迟日程或习惯提醒（到点触发后自动清空推迟状态） |
| `temp_override_habit` | 临时修改习惯提醒时间（仅今天生效，仅影响习惯） |
| `get_notion_tasks` | 查看 Notion 未完成待办（依赖 api-gateway Skill 和数据库配置） |
| `skip_water` | 跳过本次喝水提醒（仅影响当前用户喝水间隔计算） |

### 工具边界说明
- 单次日程触发后会自动关闭，避免重复提醒。
- `snooze_schedule` 仅改变下次触发时间，不改变原始 `time` 字段。
- 自动提醒仅发送给 `whitelist_qq_ids` 中的账号。
- `apple_id` / `apple_app_password` 为兼容旧配置保留；当前日历同步仅使用 `webcal_urls`。

---

## 常见问题

**Q: Notion 待办同步不工作？**
- 确认 api-gateway Skill 已启用且 Maton API Key 配置正确
- 确认 Maton 后台 Notion OAuth 连接状态为 **ACTIVE**
- 确认插件中 `transaction_db_id` 填写了正确的数据库 ID

**Q: 没收到早报？**
- 检查 `whitelist_qq_ids` 是否包含你的 QQ 号
- 确认 Bot 在 9:00 时在线

**Q: Apple 日历同步失败？**
- 请确认 `webcal_urls` 已配置且可访问
- 当前版本通过 WebCal 公共链接拉取日历，不依赖 Apple ID 登录

**Q: 想改喝水提醒间隔？**
- 修改 `water_interval` 配置项，单位为分钟

**Q: 提醒太烦想关掉？**
- 设置 `enable_bath_reminder` / `enable_sleep_reminder` / `enable_water_reminder` 为 `false`
