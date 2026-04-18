# Schedule Assistant 日程助手

> 🤖 **AI Generated** — 本插件由 AI 辅助开发

> 你的贴心日程管家，每日自动提醒、智能同步日历与待办事项

---

## 功能一览

### ☀️ 每日早报
每天早上 9:00（可配置）自动推送：
- 天气情况（当前天气、预报、温差、降水概率）
- 今日日历事件（Apple 日历同步）
- 本地日程列表
- Notion 待办事项（只显示已过期或一周内的事项）
- 贴心建议（结合 Live Dashboard 状态智能生成）

### 🔔 习惯提醒
| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 🚿 洗澡提醒 | 22:00 | 可推迟、可临时改时间 |
| 😴 睡觉提醒 | 23:00 | 智能催睡，超时带吐槽 |
| 💧 喝水提醒 | 每90分钟 | 9:30-21:30 循环，可跳过 |

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

1. 将插件文件夹放入 `/AstrBot/data/plugins/`
2. 重启 AstrBot
3. 在管理面板配置 API Key

---

## 配置项

| 配置项 | 说明 | 获取方式 |
|--------|------|---------|
| `morning_report_time` | 早报推送时间，默认 `09:00` | — |
| `weather_api_key` | 心知天气 API Key | [seniverse.com](https://seniverse.com) 免费注册 |
| `weather_city` | 天气查询城市，默认 `杭州` | — |
| `maton_api_key` | Maton Gateway Key | [gateway.maton.ai](https://gateway.maton.ai) |
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

---

## 文件结构

```
astrbot_plugin_schedule_assistant/
├── main.py              # 主逻辑、定时任务调度、LLM工具
├── schedule_store.py    # 数据持久化（AstrBot Preference API）
├── notion_client.py     # Notion API 调用（通过 Maton Gateway）
├── apple_calendar.py    # Apple 日历同步（WebCal）
├── dashboard.py         # Live Dashboard 状态获取
├── constants.py         # 统一常量定义
├── _conf_schema.json    # 配置项 schema
├── metadata.yaml        # 插件元信息
├── requirements.txt     # 依赖（仅需 aiohttp）
└── README.md            # 本文档
```

---

## LLM 工具一览

| 工具名 | 说明 |
|--------|------|
| `add_schedule` | 添加日程或习惯 |
| `remove_schedule` | 删除日程或习惯（模糊匹配） |
| `list_schedules` | 查看所有日程和习惯 |
| `snooze_schedule` | 推迟日程或习惯提醒 |
| `temp_override_habit` | 临时修改习惯提醒时间（仅今天生效） |
| `get_notion_tasks` | 查看 Notion 未完成待办 |
| `skip_water` | 跳过本次喝水提醒 |

---

## 常见问题

**Q: 没收到早报？**
- 检查 `whitelist_qq_ids` 是否包含你的 QQ 号
- 确认 Bot 在 9:00 时在线

**Q: Apple 日历同步失败？**
- 专用密码不是登录密码，需在 appleid.apple.com 生成
- 确保 Apple ID 开启了双重认证

**Q: 想改喝水提醒间隔？**
- 修改 `water_interval` 配置项，单位为分钟

**Q: 提醒太烦想关掉？**
- 设置 `enable_bath_reminder` / `enable_sleep_reminder` / `enable_water_reminder` 为 `false`

---

## 更新日志

### v1.2.0
- 🎨 重构代码架构，删除死代码约300行
- ⚡ 统一为纯异步实现，提升响应性能
- 🔧 修复 LLM 工具描述不一致问题
- 📦 发布至 GitHub

### v1.1.0
- ✅ 支持临时修改习惯提醒时间（仅当天生效）
- ✅ 喝水提醒增加防重入机制
- ✅ 早安播报支持 Live Dashboard 状态感知

### v1.0.0
- 🎉 初始版本
- ✅ 基础日程管理
- ✅ 洗澡/睡觉/喝水定时提醒
- ✅ Notion 待办同步
- ✅ Apple 日历同步
- ✅ 每日早安播报

---

## 技术说明

- **数据存储**：使用 AstrBot 内置 Preference API，无需额外数据库
- **异步框架**：全程 `asyncio` + `aiohttp`，兼容 AstrBot 异步环境
- **定时调度**：使用 `APScheduler` 的 `AsyncIOScheduler`
- **外部集成**：Notion（通过 Maton Gateway）、Apple 日历（WebCal）
- **上下文感知**：结合 Live Dashboard 设备状态生成智能提醒

---

*🤖 由 [Slandre](https://github.com/OMSociety) & [Flandre](https://github.com/Slandre) 开发，用爱发电 ❤️*
