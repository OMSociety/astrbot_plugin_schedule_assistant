<p align="center"><strong>English</strong> · <a href="README.md">中文</a> · <a href="README_ru.md">Русский</a> · <a href="README_ja.md">日本語</a></p>

<div align="center">

<img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/logo.png" width="120" alt="Schedule Assistant Logo" />

# 🗓️ Schedule Assistant — Schedule Reminder Assistant

**Your considerate schedule butler** — Morning broadcast · Habit reminders · LLM schedule management · Apple Calendar two-way sync · Notion to-do sync

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/stargazers)
[![Issues](https://img.shields.io/github/issues/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues)

</div>

> 🎨 This project was written by AI · Plugin logo from Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

---

## ✨ Core Features

| Feature | Description |
|------|------|
| 🌤️ **Daily morning broadcast** | Weather + today's agenda + Notion to-dos + late-night detection — everything you need to get up in one message |
| ⏰ **Smart habit reminders** | Scheduled reminders for showering / sleeping / drinking water, with snooze and one-off time changes |
| 🤖 **LLM schedule management** | Manage your schedule in natural language: add / delete / query / modify, with automatic time parsing |
| 🔄 **Apple Calendar two-way sync** | iCloud CalDAV read + write, with automatic deduplication and incremental updates |
| 📝 **Notion to-do sync** | DDL countdown reminders (N days left / due today / overdue) |
| 🎨 **Multi-platform Markdown rendering** | Native tables on qq_official, automatic fallback to plain text on Onebot and other platforms |

---

## 📖 Feature Overview

### Daily Morning Broadcast
Automatically pushed every morning (time configurable), one message with everything you need to start the day:

<img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/docs/briefing_example.png" alt="Morning broadcast example" width="480" />

### Habit Reminders

| Habit | Default time | Description |
|------|---------|------|
| 🚿 Shower reminder | 22:00 | Can be snoozed; one-off time changes supported |
| 😴 Sleep reminder | 23:00 | Smart bedtime nudges, with extra teasing if you stay up too late |
| 💧 Water reminder | Every 90 minutes | Loops from 9:30–21:30, can be skipped |
| 📅 Smart schedule reminder | N minutes ahead | **LLM-generated** natural language reminders, with context |

### Apple iCloud Calendar Two-Way Sync

**Read (Apple → local):**
- Periodically pulls iCloud calendar events into local storage
- Automatically syncs additions / changes / deletions, with Apple Calendar as the source of truth

**Write (local → Apple):**
- Schedules added through the bot are automatically written to the specified Apple calendar
- Event UIDs are recorded for later sync identification and deduplication

**What you need to connect:**
- `username` — Apple ID email (e.g. `xxx@icloud.com`)
- `app_password` — an **app-specific password** (generated at [appleid.apple.com](https://appleid.apple.com), not your login password)
- `calendar_id` — UUID of the target calendar; leave empty for the first one. The UUID can be copied from the CalDAV server address of the Apple calendar: the address looks like `…/calendars/<UUID>/`, take the UUID segment and fill it in

### Notion To-Do Sync
Checks your Notion databases once an hour and sends a private message when a DDL is near (within 24 hours). Requires setting up Maton Gateway as the middleware first.

### Markdown Rendering
All scheduled broadcasts (morning / habit / schedule reminders) go through a unified rendering pipeline with automatic fallback per platform:
- **native** — platforms that parse md natively (qq_official, discord, telegram, etc.) receive the message as-is
- **plain** — platforms without native md support are automatically stripped down to plain text

QQ native tables are automatically rendered as aligned rows, no extra configuration needed; it can be disabled or overridden in the configuration.

---

## 🚀 Quick Start

### Step 1: Install Schedule Assistant

**Option 1: Plugin marketplace**
- AstrBot WebUI → Plugin marketplace → search for `schedule_assistant`

**Option 2: Manual installation**
1. Put the plugin folder into `/AstrBot/data/plugins/`
2. Restart AstrBot
3. Configure the parameters as needed in the admin panel

> 💡 Core dependencies are already bundled in the AstrBot environment; no extra installation is required.

### Step 2: Minimal Configuration (Get All Scheduled Reminders Running)

You only need to fill in one line under WebUI plugin config → **Basic settings** → `user_ids`:

```
你的平台ID:FriendMessage:你的用户ID
```

The `PlatformID:SessionType:UserID` format (UMO format) — one line covers both "who to remind" and "which platform to send from". A plain QQ number also works; it will be sent as a private chat automatically.

### Step 3 (Optional): Configure Notion Sync

1. Connect Notion on [Maton](https://www.maton.ai/) (via OAuth2) and generate a **Maton API Key**
2. Download [api-gateway-skill](https://github.com/maton-ai/api-gateway-skill) and fill in your Maton API Key in the configuration
3. AstrBot admin panel → **Skills** → upload api-gateway-skill and enable it

---

## ⚙️ Configuration Reference

### Basic Settings

| Key | Type | Default | Description |
|--------|------|------|------|
| `persona_id` | string | `""` | LLM persona ID (corresponds to `persona_id` in the configuration file); if left empty it is fetched automatically from the conversation |
| `user_nickname` | string | `""` | User nickname; if left empty the broadcast addresses you as "Master" |
| `user_ids` | list | `[]` | List of user IDs to receive automatic reminders, one per line (QQ number or platform UID); use the UMO format (`PlatformID:SessionType:UserID`) to also complete platform routing |

### Schedule Reminder Settings

| Key | Type | Default | Description |
|--------|------|------|------|
| `enable_schedule_reminder` | bool | `false` | Toggle for LLM-based smart schedule reminders (off by default) |
| `schedule_reminder_minutes` | int | `10` | Minutes to remind before a schedule starts (all-day schedules do not trigger reminders) |
| `schedule_reminder_check_interval` | int | `5` | Scan interval for schedule reminders (minutes); recommended 1/3–1/2 of the lead time (e.g. 3–5 minutes for a 10-minute lead time), minimum 2 minutes |

### Habit Reminder Settings

| Key | Type | Default | Description |
|--------|------|------|------|
| `enable_morning_report` | bool | `true` | Toggle for the morning broadcast |
| `morning_report_time` | string | `09:00` | Morning broadcast push time (HH:MM) |
| `enable_bath_reminder` | bool | `true` | Toggle for the shower reminder |
| `bath_time` | string | `22:00` | Shower reminder time |
| `enable_sleep_reminder` | bool | `true` | Toggle for the sleep reminder |
| `sleep_time` | string | `23:00` | Sleep reminder time |
| `enable_water_reminder` | bool | `true` | Toggle for the water reminder |
| `water_interval` | int | `90` | Water reminder interval (minutes) |
| `water_start_time` | string | `09:30` | Water reminder start time |
| `water_end_time` | string | `21:30` | Water reminder end time |

### Calendar Sync Settings

| Key | Type | Default | Description |
|--------|------|------|------|
| `enable_apple_calendar_sync` | bool | `false` | Toggle for Apple Calendar two-way sync |
| `apple_calendar_sync_interval` | int | `30` | Apple Calendar sync interval (minutes) |
| `apple_calendar.username` | string | - | Apple ID email |
| `apple_calendar.app_password` | string | - | **App-specific password** (not your login password) |
| `apple_calendar.calendar_id` | string | - | UUID of the target calendar; leave empty for the first one. Copy the UUID from the CalDAV server address of the Apple calendar (`…/calendars/<UUID>/`) |
| `webcal_urls` | list | `[]` | WebCal shared calendar links |

> 💡 **WebCal subscription security**: `webcal_urls` only accepts public `https://` subscription addresses (`webcal://` is automatically converted to `https://`). The plugin rejects addresses such as `localhost`, intranet addresses (e.g. `192.168.x` / `10.x`), and cloud metadata endpoints (`169.254.169.254`) to prevent SSRF. Do not enter intranet or local addresses.

> Write sync is controlled by the top-level `enable_apple_calendar_sync`; when enabled, schedules created/deleted locally are automatically synced to Apple Calendar.

### External Services Settings

| Key | Type | Description |
|--------|------|------|
| `maton_api_key` | string | Maton API Key (required for Notion features) |
| `notion_db_ids` | list | List of Notion database IDs, format: `["事务:xxx", "阅读:yyy"]` |
| `weather_api_key` | string | Seniverse weather API Key ([seniverse.com](https://seniverse.com)) |
| `weather_city` | string | City for weather queries (default: Beijing) |

### Message Rendering Settings

| Key | Type | Default | Description |
|--------|------|------|------|
| `markdown_enabled` | bool | `true` | Global Markdown rendering toggle; when off, falls back to plain text |
| `markdown_native_platforms` | list | `[]` | Additional platform IDs that parse Markdown natively |
| `qq_markdown_enabled` | bool | Leave empty | QQ platform toggle: leave empty to follow the global setting; `false` forces QQ to skip native md |

### Reminder Prompt Templates

| Key | Type | Default | Description |
|--------|------|------|------|
| `prompt_morning` | string | `""` | Morning broadcast template. Placeholders: `{username} {date} {weekday} {weather_current} {weather_forecast} {agenda} {notion_todos} {late_night}` |
| `prompt_bath` | string | `""` | Shower reminder template. Placeholders: `{current_time} {default_time} {history}` |
| `prompt_sleep` | string | `""` | Sleep reminder template. Placeholders: `{current_time} {default_time} {is_late} {history}` |
| `prompt_water` | string | `""` | Water reminder template. Placeholders: `{current_time} {history}` |
| `prompt_schedule` | string | `""` | Schedule reminder template. Placeholders: `{item_title} {time_label} {ahead_label} {item_context} {conv_history}` |

> If a template is left empty, the built-in default is used (see `prompt_config.py`); fill it in to customize the reminder tone, with support for `{variable_name}` placeholders.

### Quick Configuration Template

Fill it in via the WebUI configuration panel, or refer to the following structure (`data/config/schedule_assistant_config.json`):

```json
{
  "basic_settings": {
    "persona_id": "",
    "user_nickname": "",
    "user_ids": ["你的平台ID:FriendMessage:你的用户ID"]
  },
  "schedule_reminder_settings": {
    "enable_schedule_reminder": false,
    "schedule_reminder_minutes": 10,
    "schedule_reminder_check_interval": 5
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
    "apple_calendar": { "username": "", "app_password": "", "calendar_id": "" },
    "webcal_urls": []
  },
  "external_services_settings": {
    "maton_api_key": "",
    "notion_db_ids": [],
    "weather_api_key": "",
    "weather_city": "北京"
  },
  "message_render_settings": {
    "markdown_enabled": true,
    "markdown_native_platforms": [],
    "qq_markdown_enabled": null
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

## 🛠️ LLM-Callable Tools

The plugin registers 4 LLM tools; the model decides automatically when to call them — just state your needs in natural language:

```
用户: 帮我加个明天早上9点开组会的日程
🤖 → create_schedule(title=组会, datetime_str=明天9点)
    已创建日程「组会」，时间：08-17 09:00 ✅

用户: 把下午3点的会议改到4点
🤖 → update_schedule(title_keyword=会议, new_datetime=下午4点)
    已修改日程：时间改为下午4点 ✅

用户: 看看这周有什么安排
🤖 → list_schedules(days=7)
    📋 接下来7天日程（共3个）：
    ━━━ 08-17 周一 ━━━
      ⏰ 09:00 │ 组会
      ...

用户: 删除明天的读书会
🤖 → delete_schedule(title_keyword=读书会)
    已删除日程「读书会」✅
```

### create_schedule
Creates a new schedule.

| Parameter | Type | Description |
|------|------|------|
| `title` | string | **Required**, schedule title / content |
| `datetime_str` | string | **Required**, supports natural language time, e.g. "tomorrow 9am", "the day after tomorrow at 3pm", "2024-01-15 14:30" |
| `description` | string? | Optional description |

### delete_schedule
Deletes a schedule. Supports exact match by ID or fuzzy match by title keyword.

| Parameter | Type | Description |
|------|------|------|
| `schedule_id` | string? | Schedule ID (exact match) |
| `title_keyword` | string? | Title keyword (fuzzy match, e.g. "meeting", "group meeting") |

### list_schedules
Lists schedules.

| Parameter | Type | Description |
|------|------|------|
| `days` | int? | How many recent days of schedules to show, default 7 days |

### update_schedule
Modifies a schedule. Title, time, and description can be updated individually or in combination.

| Parameter | Type | Description |
|------|------|------|
| `schedule_id` | string? | Schedule ID (exact match) |
| `title_keyword` | string? | Title keyword (fuzzy match) |
| `new_title` | string? | New title |
| `new_datetime` | string? | New time, supports natural language |
| `new_description` | string? | New description |

---

## 📝 Changelog

> 📋 **[View the full changelog →](CHANGELOG.md)**

---

## ⭐ Support This Project

If this plugin helps you, please consider giving it a Star ⭐. For questions and suggestions, feel free to open an [Issue](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues) or a [Pull Request](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/pulls).

## 🙏 Acknowledgements

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) open-source chatbot framework
- Plugin logo from Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

---

## 📜 License

This project is licensed under the **MIT License**.

---

## 👤 Author

[@OMSociety](https://github.com/OMSociety)
