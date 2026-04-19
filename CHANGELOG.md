# 更新日志

所有版本更新记录。

---

## v1.5.2

> 🧩 体检修复版本 — 触发闭环 + 配置校验 + 文档对齐

### 关键修复
- 🐛 修复日程扫描判定：改为“最近65分钟窗口”扫描，非整点日程可稳定触发
- 🐛 打通 `snooze_schedule` 生效链路：扫描逻辑消费 `snoozed_until`，到点触发后自动清空
- 🐛 单次日程触发后自动禁用，避免重复提醒

### 稳定性
- ✨ 新增配置合法性校验与回退（时间格式、`water_interval` 范围、白名单标准化）

### 清理与一致性
- 🗑️ 清理 `AppleCalendar` 在 WebCal 模式下未使用的 CalDAV 字段/逻辑
- 🗑️ 删除未使用的 `get_dashboard_status_sync` 同步接口
- 🔧 统一版本号到 `v1.5.2`（`metadata.yaml` / `main.py` / `__init__.py`）
- 📝 更新 README 工具边界说明，文档与实现保持一致

---

## v1.5.1

> 🐛 修复版本 — 喝水任务重复触发

### 修复
- 🐛 `replace_existing=True` 对 `date` 触发器无效，喝水提醒每次重启堆积一个（现已显式 `remove_job` 清理）

---

## v1.5.0

> 🏗️ 架构重构版本 — 消除双入口 + 补闭环 + 资源释放

### 架构修复
- 🐛 `_notion_ddl_check` 改用实例方法 `self.notion.get_pending_transactions()`（原模块级函数从未初始化，DDL检查从未生效）
- 🗑️ 删除废弃的模块级函数（`_module_config`/`notion_get_pending_async` 等约120行死代码）

### 资源管理
- ✨ `on_unload` 新增 Notion 和日历会话关闭，修复连接泄漏
- ✨ `AppleCalendar` 新增 `close()` 方法（空实现，保持接口一致性）

### 功能闭环
- ✨ 新增日程定时扫描任务（每小时01分执行，到期触发私信提醒）
- ✨ `ScheduleStore` 新增 `update_item()` 方法，支持日程状态持久化

### P2 优化（架构健康）
- 🏗️ `notion_client.py` 单入口：只保留 `NotionClient` 类，删除冗余模块级函数

---

## v1.4.1

> 🐛 修复版本 — 播报正确性与智能化修复

### 播报修复
- 🐛 日历播报只显示今日日程（原拉取7天数据导致串台，现改为days=2+今日过滤）
- 🐛 Notion 待办显示 DDL 倒计时（原无截止时间，现显示「还剩N天/今天截止/已逾期N天」）
- 🐛 `_send_to_user` 过滤表情标签（&&tag&&），避免标签被当作正文发送

### 智能化增强
- ✨ 早安播报新增熬夜检测（查询今日00:00-06:00苹果日历事件，判断昨晚是否熬夜）
- ✨ prompt 规则更新：熬夜检测替代废弃的「设备显示熬夜」逻辑

### 代码质量
- 🔧 prompt typo 修复（「温和温和催促」→「温和催促」）

---

## v1.4.0

> 🐛 修复版本 — 功能正确性修复 + 稳定性提升

### 功能修复
- 🐛 `_fetch_calendar_events` 缺少 `await`，日历数据无法获取（现已修复）
- 🐛 `_notion_ddl_check` 只写日志不发消息，DDL 私信提醒功能现已生效
- 🐛 `skip_water` 与喝水提醒逻辑闭环，读取上次喝水时间计算真实间隔

### 逻辑一致性
- `_fetch_local_schedules` 更名为"获取本地所有日程"，消除歧义
- `AppleCalendar.fetch_webcal_async(days=...)` 参数现已正确生效，早报展示未来7天日历

### 稳定性提升
- `NotionClient` 改为实例隔离，`_config`/`_pending_cache` 不再跨实例污染
- 所有 aiohttp 请求统一封装：状态码分类处理（401/403/404/429）、最多3次重试、超时控制
- `NotionClient` 实例级 session 复用，减少连接开销

---

## v1.3.0

> 🎨 重构版本 — 代码全面优化

### 新增
- `repo` 字段接入 AstrBot 面板，可一键跳转 GitHub

### 优化
- 🎨 重构代码架构，删除死代码约 300 行
- ⚡ 统一为纯异步实现，提升响应性能
- 🔧 修复 LLM 工具描述不一致问题（snooze/日_notion/list_schedules）
- 📊 `list_schedules` 输出显示具体周期（每天/每周/每月）

### 清理
- 删除 `backup_before_refactor/` 历史备份目录
- 删除未使用的 `PREFERENCE_KEY` 常量
- 删除 `requirements.txt` 中未使用的 `icalendar`、`pytz` 依赖
- `apple_calendar.py` 删除 8 个死方法，改为纯异步
- `notion_client.py` 删除同步包装函数，统一为 async/await
- `main.py` 删除死方法 `_generate_morning_advice`

---

## v1.2.0

> 🔧 维护版本 — 数据持久化重构

### 新增
- `temp_override_habit` 工具 — 临时修改习惯提醒时间，仅当天生效
- 喝水提醒增加防重入机制，避免重复触发
- 每日凌晨自动清理过期的临时修改

### 优化
- 喝水提醒智能计算首次触发时间，支持重启后立即续期
- `schedule_store.py` 全面重构，迁移至 AstrBot Preference API
- 早安播报支持 Live Dashboard 设备状态感知

---

## v1.1.0

> ⚡ 性能与体验优化

### 新增
- `skip_water` 工具 — 跳过本次喝水提醒
- `get_notion_tasks` 工具 — 直接查看 Notion 待办列表
- `snooze_schedule` 工具 — 推迟日程或习惯提醒
- 洗澡/睡觉提醒可单独开关（`enable_bath_reminder` 等配置）

### 优化
- 日程列表输出增加 🔄 标记显示重复周期
- Notion 任务过滤逻辑优化，只显示已过期或一周内的任务
- LLM 提醒文案生成质量提升
