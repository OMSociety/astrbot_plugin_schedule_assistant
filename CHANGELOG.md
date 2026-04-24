# 更新日志

---

## v2.0.0

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

## v1.9.0

### 新增
- 注册 4 个 LLM 日程管理工具：`create_schedule` / `delete_schedule` / `list_schedules` / `update_schedule`。
- 支持自然语言时间解析与标题关键词匹配。

### 修复
- 修复 Apple 日历 UTC/TZID 时间解析相关问题。

---

## v1.8.0

### 新增
- Apple iCloud 日历同步能力（含定时拉取与本地同步）。
- 日程 LLM 智能提醒（支持开关与提前量配置）。

### 修复
- 多项 CalDAV 兼容性与事件时间解析问题。

---

> 更早版本记录已归档，不再在此文件维护，以避免过时信息造成误解。
