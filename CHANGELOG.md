# 更新日志

> 本项目仍处于活跃维护中。

---

## [2.2.0] - 2026-04-25

### 修复
- **Apple 日历日程提醒失效**：日程提醒扫描现在正确覆盖 Apple 同步过来的日程，不再依赖同步时机
- **扫描间隔优化**：日程提醒扫描改为可配置间隔（默认5分钟），避免1分钟高频扫描的资源浪费
- **即时补扫机制**：Apple 同步到新增日程后，30秒后触发一次即时扫描，确保临近日程不会被错过
- **时间解析增强**：支持 ISO 格式（带时区后缀如 `+08:00`、`Z`）的时间字符串解析

### 新增
- `schedule_reminder_check_interval`：日程提醒扫描间隔配置，默认5分钟，最小2分钟

---

## [2.1.0] - 2026-04-25

### 新增
- **Live Dashboard 视奸面板功能**：合并自 [astrbot_plugin_live_dashboard](https://github.com/DBJD-CR/astrbot_plugin_live_dashboard)
  - 支持 `/视奸` `/live` `/dashboard` `/设备状态` 命令查询设备状态
  - LLM 工具 `query_live_dashboard_status`，支持对话中自动调用
  - 丰富的黑名单机制（用户/群组/信息黑名单）
  - 可配置显示项（平台/应用名/标题/电量/音乐/最后活跃时间等）
- 配置项重构：Live Dashboard 配置独立成区块，与日程、Apple日历等配置分类管理

### 修复
- 修复 LLM 工具 schema 中可选参数校验问题（nullable + required: []）

---

## [2.0.0] - 2026-04-23

### 新增
- 注册 4 个 LLM 日程管理工具：`create_schedule` / `delete_schedule` / `list_schedules` / `update_schedule`
- 支持自然语言时间解析与标题关键词匹配

### 修复
- 修复 Apple 日历 UTC/TZID 时间解析相关问题

---

## [1.9.0] - 2026-04-XX

### 新增
- Apple iCloud 日历同步能力（含定时拉取与本地同步）
- 日程 LLM 智能提醒（支持开关与提前量配置）

### 修复
- 多项 CalDAV 兼容性与事件时间解析问题

---

## [1.8.0] - 2026-04-XX

### 新增
- Notion 待办同步能力
- 每日早安播报
- 习惯提醒（洗澡/睡觉/喝水）

---

> 更早版本记录已归档，不再在此文件维护。
