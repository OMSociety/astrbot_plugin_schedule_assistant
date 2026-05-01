# 代码重构报告 — B 类（需确认）

以下问题涉及功能/行为变更，未直接修改代码，需要确认后再处理。

---

## 1. `_water_reminder` 重调度逻辑可能多跳一个周期 ✅ **【用户确认：需修复，喝水提醒间隔翻倍问题】**

**文件**: `main.py:780-794`（重构后行号）

**问题**: 水提醒重调度时传入 `datetime.now() + timedelta(minutes=water_interval)` 作为 `_get_water_next_trigger` 的 `now` 参数。该函数内部会计算 `(elapsed // interval_min + 1) * interval_min`，即已经在 `now` 基础上 +1 个周期。两者叠加可能导致实际间隔为 `2 * water_interval` 而非预期的 `water_interval`。

**建议方案**: 改为传入 `datetime.now()` 作为 `now`，让 `_get_water_next_trigger` 自然计算下一个对齐时间点。

**不改原因**: 改变喝水提醒的触发频率，属于行为变更。

---

## 3. `sync_from_apple_calendar` 直接构造原始 dict 而非使用 `ScheduleItem`

**文件**: `schedule_store.py:282-296`

**问题**: 新增 Apple 日历事件时直接构造 `dict`，而不是使用 `ScheduleItem` dataclass。这导致数据结构与 `ScheduleItem` 的字段定义存在隐式耦合，如果 `ScheduleItem` 新增字段，此处需要手动同步。

**建议方案**: 使用 `ScheduleItem(...).to_dict()` 替代手动构造。

**不改原因**: 改动序列化路径，需确认对已有数据的兼容性。

---

## 4. `LLMService` 使用模块级全局变量做断路器 ✅ **【用户确认：需修复，断路器形同虚设】**

**文件**: `services/llm.py:11-12`

**问题**: `_llm_failure_time` 是模块级全局变量，多个 `LLMService` 实例共享同一断路器状态。当前只有一个实例，但设计上不干净。此外，断路器变量声明了但实际未在 `generate_llm_message` 中做检查（只在成功时重置、失败时设置，但没有"熔断期间跳过调用"的逻辑）。

**修复方案**: 将断路器改为实例变量，并补充熔断检查逻辑（如 5 分钟内失败则直接返回 fallback）。

---

## 5. `habits.py` 的 `_setup_llm_template` 在 `__init__` 中设置 fallback 模板

**文件**: `reminders/habits.py:55-57`

**问题**: `HabitReminder.__init__` 调用 `_setup_llm_template()`，在初始化时就设置了 LLM 的 fallback 模板。但 `LLMService` 此时可能尚未完全初始化（provider 未就绪）。此外 `SleepReminder._build_prompt` 每次调用时会重新设置 fallback 模板（根据是否超晚），与初始化时的设置冲突。

**建议方案**: 将 fallback 模板设置移到 `generate()` 方法中（生成前设置），而非 `__init__`。

**不改原因**: 改变 fallback 模板的设置时机，可能影响其他提醒类型的 fallback 行为。

---

## 6. `AppleCalendar._request` 使用同步 `urllib.request` 阻塞调用

**文件**: `apple_calendar.py:54-86`

**问题**: `_request` 方法使用同步的 `urllib.request`，通过 `_async_request` 的 `run_in_executor` 包装为异步。但 `ThreadPoolExecutor` 在 `_caldav_fetch_sync` 中以 `max_workers=10` 创建，每次调用都新建线程池，开销较大。

**建议方案**: 将 `_request` 改为纯 `aiohttp` 实现，或复用持久化线程池。

**不改原因**: 改变网络 I/O 策略，需要充分测试 CalDAV 兼容性。

---

## 7. `BasicDashboardService._fetch_dashboard_status` 同步读取文件

**文件**: `services/dashboard.py:71`

**问题**: 使用 `open()` 同步读取配置文件，在异步上下文中可能阻塞事件循环。

**建议方案**: 使用 `aiofiles` 或 `loop.run_in_executor` 包装。

**不改原因**: 配置文件很小（几 KB），阻塞时间可忽略。改动引入额外依赖。
