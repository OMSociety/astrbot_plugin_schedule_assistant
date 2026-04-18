# Schedule Assistant 日程助手

> 你的贴心日程管家，每日自动提醒、智能同步日历与待办事项

## 这个插件能做什么？

### 1. 每日早报 ☀️
每天早上 9:00 自动推送：
- 天气情况（今天天气、温差、降水概率）
- 今日日历（从 Apple 日历读取）
- 待办事项（从 Notion 读取即将到期的事项）
- 贴心建议（根据天气和日历智能生成）

### 2. 习惯提醒 🔔
| 习惯 | 默认时间 | 说明 |
|------|---------|------|
| 🚿 洗澡 | 22:00 | 可推迟、可临时改时间 |
| 😴 睡觉 | 23:00 | 智能催睡，支持推迟 |
| 💧 喝水 | 每90分钟 | 9:30-21:30 期间循环提醒，可跳过 |

**智能功能：**
- 可以跟 Bot 说"今天洗澡改到23点"（只改今天）
- 说"跳过这次喝水"就不会打扰你
- 结合 Live Dashboard 状态生成个性化提醒

### 3. 日程管理 📝
直接跟 Bot 说：
- "明天上午10点开组会" → 添加日程
- "删除开组会" → 删除匹配项
- "查看我的日程" → 查看列表
- "推迟组会20分钟" → 临时调整

### 4. Notion 待办同步 📋
每小时检查一次 Notion 事务库，DDL 临近时私信提醒你。

---

## 安装方法

1. 把插件文件夹放进 `/AstrBot/data/plugins/`
2. 重启 AstrBot
3. 在管理面板配置你的 API Key

---

## 配置说明

在 AstrBot 管理面板 → 插件配置 → Schedule Assistant 里填：

| 配置项 | 用途 | 去哪获取 |
|--------|------|---------|
| **Maton API Key** | 读取 Notion 数据库 | https://gateway.maton.ai |
| **Apple 专用密码** | 同步 Apple 日历 | https://appleid.apple.com |
| **心知天气 API** | 查天气 | https://seniverse.com |
| **WebCal 链接** | 共享日历（不用密码） | iCloud 日历 → 复制链接 |

**基础设置：**
- `bath_time`: 洗澡提醒时间（默认 22:00）
- `sleep_time`: 睡觉提醒时间（默认 23:00）
- `water_interval`: 喝水间隔分钟数（默认 90）
- `whitelist_qq_ids`: 白名单QQ号，只有这些QQ能收到自动提醒。格式如 ["123456789"]，第一个会作为默认用户

---

## 文件结构

```
astrbot_plugin_schedule_assistant/
├── main.py              # 主逻辑 + 定时任务
├── schedule_store.py    # 数据存储（AstrBot 自带数据库）
├── apple_calendar.py    # Apple 日历同步
├── dashboard.py         # 读取 Live Dashboard 状态
├── notion_client.py     # Notion API 调用
├── _conf_schema.json    # 配置项定义
├── requirements.txt     # 依赖
└── README.md            # 本文档
```

---

## 自然语言指令（直接跟 Bot 说）

### 日程管理
- "添加日程：明天上午10点开组会"
- "删除开组会"
- "查看我的日程"
- "推迟组会20分钟"

### 习惯控制
- "今天洗澡改到23点"
- "跳过这次喝水"
- "查看 Notion 待办"

---

## 常见问题

**Q: 没收到早报？**
- 检查 `whitelist_qq_ids` 里有没有你的 QQ 号
- 确认 9:00 时机器人在线

**Q: Apple 日历同步失败？**
- 专用密码不是 Apple ID 密码，要去 appleid.apple.com 生成
- 检查 Apple ID 是否开启了双重认证

**Q: 喝水间隔想改短？**
- 改 `water_interval` 配置，单位是分钟

**Q: 提醒太烦想关掉？**
- 把 `enable_bath_reminder` 等设成 `false`

---

*由 Slandre & Flandre 开发，用爱发电 ❤️*
