# Changelog

> 本项目仍处于活跃维护中。

---

## [2.5.0] - 2026-08-15

### 🧹 代码清理（全量检查）
- **移除约 1100 行死代码与残留文件**：
  - 删除「视奸面板」功能残留 `services/payload_client.py`、`services/app_descriptions.py`（无任何引用，且 payload_client 还依赖未声明的 httpx）
  - 删除无引用的 `config_validator.py`（ConfigValidator/ConfigMigration）及对应 `tests/`
  - 删除空壳转发目录 `utils/` 与无人使用的 `services/config_parser.py`、`services/time_formatter.py`
  - 删除调试残留 `apple_calendar_request_section.txt`、占位文件 `TIMESTAMP.txt`
  - 删除误提交的 AstrBot 系统配置 `data/cmd_config.json` 与无引用的 `data/t2i_templates/` 模板
  - 清理 `constants.py` 中 5 个未使用常量

### 🐛 Bug 修复
- **LLM 熔断器生效**（`services/llm.py`）：此前断路器只记录失败时间、从不检查，形同虚设；改为实例级熔断状态 + 5 分钟内失败直接回退模板，避免反复请求故障接口
- **习惯提醒 fallback 互相覆盖**（`reminders/habits.py`）：洗澡/睡觉/喝水共享同一 LLM 服务，睡觉提醒会改写全局 fallback 导致其他提醒 LLM 失败时用错文案；改为每次生成前按提醒类型设置
- **服务初始化并发竞态**（`main.py`）：`_ensure_services` 初始化代码原先在锁外，热重载时可能并发重复创建 Notion 连接；整体移入锁内
- **工具注册防重复**（`main.py`）：工具注册失败时先置位标志，避免热重载后重复挂载工具
- **配置默认值对齐**（`_conf_schema.json`）：喝水时段默认值修正为 `09:30`/`21:30`（与代码、README 一致），`weather_city` 默认 `杭州`
- **QQ 官方原生 Markdown 真正生效**（`markdown.py`）：此前 `qq_official` 平台被无条件转为 QQ 排版纯文本，`qq_markdown_enabled` 配置形同虚设；现默认直发原生 md（表格原生渲染），仅当 `qq_markdown_enabled=false` 时降级为 QQ 排版纯文本。非原生平台（如 Onebot）仍自动 strip 降级

### 🔧 代码质量提升
- `BROADCAST_MD_OVERRIDE` 三处重复定义收敛到 `constants.py` 统一引用
- Apple 日历同步新增日程改用 `ScheduleItem` dataclass 序列化，消除手写 dict 与字段定义的隐式耦合
- 日程提醒扫描复用插件已创建的 `ScheduleReminder` 实例，不再每轮新建
- `NotionClient._relevant` 冗余条件化简
- `_extract_sender_name` 增加 `get_sender_id` 防御性调用
- 作者统一为 `OMSociety`（metadata / `__init__.py` / README）
- `requirements.txt` 补充 markdownify / markdown-it-py 可选依赖说明

---

## [2.4.0] - 2026-08-06

### ✨ 新增功能
- **通用定时消息引擎**：新增 `engine.py`，将定时触发与内容生成/发送解耦，支持 CronTrigger / HH:MM / interval:N 多种触发方式
- **Markdown 渲染管线**：新增 `markdown.py`，两级降级策略（平台原生直发 / strip 纯文本），QQ 原生表格自动渲染
- **多平台适配**：QQ 全面开放 markdown 后移除纯文本输出约束，表格在 QQ 上原生渲染

### ⚙️ 新增配置项
- `admin_uids`：管理员用户 ID 列表
- `markdown_enabled`：全局 Markdown 渲染开关
- `markdown_native_platforms`：追加原生解析 md 的平台 ID
- `qq_markdown_enabled`：QQ 平台 md 开关（留空跟随全局，false 强制关闭）

### 🐛 Bug 修复
- **插件加载失败修复**：恢复 `_conf_schema.json` 中 `apple_calendar` 缺失的嵌套 `items` 结构，解决 AstrBot 启动时 `KeyError: 'items'` 导致的插件无法加载

### 🔧 代码质量提升
- 早安播报 / 日程 / 习惯提醒统一走渲染链路，6 场景全量测试通过
- 清理 habits / schedule 中的过时纯文本约束，修正 `_conf_schema.json` 过时 hint
- 清理配置 hint 与文档中的硬编码用户 ID 示例（`admin_uids` / `user_platform_bindings`），README 配置说明对齐 schema

---

## [2.3.0] - 2026-04-27

### 🐛 Bug 修复
- **早安播报称呼问题**：修复早安播报强制使用系统用户名的问题，现在根据人格自动决定称呼方式
- **人格注入统一**：统一使用 Persona v3 API，确保所有提醒（早安/习惯/日程）的人格正确加载
- **Apple 日历重复问题**：
  - 添加 UID 去重逻辑，防止 Apple 返回的重复 RRULE 实例被多次添加
  - 优化删除逻辑：过期/远期日程不再保留在 UID 列表中，允许清理旧数据
  - **一次性清理了 247 个重复日程**（561 → 314）
- **Apple 日历时间过滤**：只同步未来 7 天内的日程，避免积累大量历史数据

### ✨ 新增功能
- **用户昵称配置**：新增 `user_nickname` 配置项，留空时播报称呼为「主人」

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
-   - 丰富的黑名单机制（用户/群组/信息黑名单）
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
