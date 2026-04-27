# Changelog

> 本项目仍处于活跃维护中。

---

## [2.3.0] - 2026-04-27

### 🔧 代码质量提升
- **全面代码审查与修复**：对全项目 5203 行代码逐条审查，修复以下问题：
  - `import uuid` 移至文件顶部，符合 PEP8 规范
  - 修复 `main.py:793` 中 `conf.get` 的未定义变量引用
  - 清理 185 处 ruff 警告（未使用 import / 变量重命名 / 空格缩进等）
- **ruff 格式化统一**：全项目通过 ruff 0.15+ 格式化，统一引号、缩进、import 排序等风格
- **错误处理增强**：补充多处 try/except 兜底，确保单点异常不导致整个定时任务崩溃
- **持久化路径规范化**：确认所有数据存储使用 AstrBot preference 系统，不依赖插件自身目录，防止更新覆盖

### 🧪 测试与验证
- **语法验证 14/14 文件全部通过**：覆盖 `main.py`、`schedule_store.py`、`apple_calendar.py`、`commands.py`、`messaging.py`、`notion_client.py`、`constants.py` 等全部 Python 模块
- **ruff check 零 Warning**：全项目 lint 检查通过

### 📝 文档重写
- **README 重构**：仿照社区最佳实践重新组织文档结构，增加功能概览、快速开始、配置表格、LLM 工具表等模块
- **CHANGELOG 重构**：采用语义化版本格式，emoji 分类呈现，更新历史可追溯

---

## [2.2.0] - 2026-04-25

### 🐛 Bug 修复
- **Apple 日历日程提醒失效**：日程提醒扫描现在正确覆盖 Apple 同步过来的日程，不再依赖同步时机
- **扫描间隔优化**：日程提醒扫描改为可配置间隔（默认5分钟），避免1分钟高频扫描的资源浪费
- **即时补扫机制**：Apple 同步到新增日程后，30秒后触发一次即时扫描，确保临近日程不会被错过
- **时间解析增强**：支持 ISO 格式（带时区后缀如 `+08:00`、`Z`）的时间字符串解析

### ✨ 新增功能
- `schedule_reminder_check_interval`：日程提醒扫描间隔配置，默认5分钟，最小2分钟

---

## [2.1.0] - 2026-04-25

### ✨ 新增功能
- **Live Dashboard 视奸面板功能**：合并自 [astrbot_plugin_live_dashboard](https://github.com/DBJD-CR/astrbot_plugin_live_dashboard)
  - 支持 `/视奸` `/live` `/dashboard` `/设备状态` 命令查询设备状态
  - LLM 工具 `query_live_dashboard_status`，支持对话中自动调用
  - 丰富的黑名单机制（用户/群组/信息黑名单）
  - 可配置显示项（平台/应用名/标题/电量/音乐/最后活跃时间等）
- 配置项重构：Live Dashboard 配置独立成区块，与日程、Apple日历等配置分类管理

### 🐛 Bug 修复
- 修复 LLM 工具 schema 中可选参数校验问题（nullable + required: []）

---

## [2.0.0] - 2026-04-23

### ✨ 新增功能
- 注册 4 个 LLM 日程管理工具：`create_schedule` / `delete_schedule` / `list_schedules` / `update_schedule`
- 支持自然语言时间解析与标题关键词匹配

### 🐛 Bug 修复
- 修复 Apple 日历 UTC/TZID 时间解析相关问题

---

## [1.9.0] - 2026-04-XX

### ✨ 新增功能
- Apple iCloud 日历同步能力（含定时拉取与本地同步）
- 日程 LLM 智能提醒（支持开关与提前量配置）

### 🐛 Bug 修复
- 多项 CalDAV 兼容性与事件时间解析问题

---

## [1.8.0] - 2026-04-XX

### ✨ 新增功能
- Notion 待办同步能力
- 每日早安播报
- 习惯提醒（洗澡/睡觉/喝水）

---

> 更早版本记录已归档，不再在此文件维护。
