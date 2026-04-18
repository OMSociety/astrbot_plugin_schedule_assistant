# 更新日志

所有版本更新记录。

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

---

## v1.0.0

> 🎉 初始版本

### 新增
- ✅ 基础日程管理（添加/删除/查看/推迟）
- ✅ 洗澡提醒（可配置时间）
- ✅ 睡觉提醒（超时自动吐槽）
- ✅ 喝水提醒（可配置间隔和时段）
- ✅ Notion 待办同步（通过 Maton Gateway）
- ✅ Apple 日历同步（CalDAV + WebCal）
- ✅ 每日早安播报（天气 + 日历 + 日程 + 贴心建议）
