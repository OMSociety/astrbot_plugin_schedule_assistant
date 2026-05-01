# Schedule Assistant 插件 Bug 排查报告

排查日期: 2026-04-29
排查范围: 全部 .py 文件（27 个文件）

---

## 一、已修复的 Bug

### 1. `reminders/briefing.py:73` - return 后有不可达死代码

**问题**: `generate_full_report()` 方法中 `return await self.llm_service.generate(prompt)` 之后还有一行 `_nl = "\n"`，永远不会执行。

**修复**: 删除了死代码行。

### 2. `reminders/schedule.py:114` - 对话历史重复注入

**问题**: `generate_reminder_text()` 在调用 `llm.generate()` 时传了 `history=conv_str`，但 prompt 已经通过 `_build_prompt()` 把 `conv_history` 嵌入了 prompt 文本中。`llm.generate()` 又会把 history 追加到 system_prompt 的 `【近期对话】` 段落，导致同一条历史被注入两次，浪费 token 且可能干扰 LLM 输出。

**修复**: 移除了 `history=conv_str` 参数，改为 `await self.llm.generate(prompt)`。

### 3. `reminders/schedule.py:125-145` - `_parse_time` 时区后缀匹配脆弱

**问题**: 原实现用 `strptime` 拼接时区后缀（如 `+08:00`、`-05:00`）来匹配 ISO 时间字符串。`strptime` 将 `+08:00` 视为字面量，只对这一个固定值有效，其他时区偏移（`+05:30`、`-05:00` 等）会静默失败并尝试下一个格式。UTC 后缀 `Z` 也因为同样的原因无法正确匹配（格式串中的 `Z` 是字面量，但实际输入的 `Z` 在数字之后）。

**修复**: 改用 `datetime.fromisoformat()` 作为首选解析器（Python 原生支持 ISO 8601 含时区），`strptime` 仅作为普通格式的兜底。

### 4. `apple_calendar.py` - 异步方法中使用阻塞 I/O

**问题**: `_discover()`、`_list_calendars()`、`create_event()`、`delete_event()` 都是 async 方法，但直接调用了同步的 `_request()`（内部使用 `urllib.request.urlopen` + `time.sleep`），会阻塞事件循环，影响 AstrBot 整体响应性。

**修复**:
- 新增 `_async_request()` 方法，通过 `loop.run_in_executor()` 将阻塞调用放到线程池
- 新增 `_async_propfind()` 异步版本
- 更新 `_discover()`、`_list_calendars()`、`create_event()`、`delete_event()` 使用异步版本
- 同步方法 `_propfind()`、`_fetch_ics_sync()` 保留不动（它们本身在 `ThreadPoolExecutor` 中调用）

---

## 二、需要确认的问题（歧义 / 设计层面）

### 5. `commands.py` - 命令 Stub 不触发实际功能

**问题**: `_handle_morning()`、`_handle_water()`、`_handle_bath()`、`_handle_sleep()` 只返回占位消息（如"早安播报已生成~"），没有实际调用 `main.py` 中的 `_morning_briefing()`、`_water_reminder()` 等方法。

用户发送"早安"或"/早安"时，只收到一句"早安播报已生成~"，但实际的天气+日程+待办播报并未执行。喝水/洗澡/睡觉提醒同理。

**影响**: 这些快捷命令对用户来说是"假的"——看起来响应了，但没做任何事。

**建议**: 需要确认这是未完成的 TODO 还是有意为之。如果需要真正触发，`CommandHandler` 需要持有 `ScheduleAssistant` 的引用或通过回调机制调用。

### 6. `schedule_store.py:299` - Apple 日历同步时删除逻辑 ✅ **【用户确认：需修复】**

**问题**: `sync_from_apple_calendar()` 中，当 `apple_events` 为空列表时（如 API 调用失败、网络超时等），`apple_uids` 为空集，过滤条件 `not s.get("apple_uid") or s["apple_uid"] in apple_uids` 会删除所有从 Apple 同步过来的日程。

```python
# 当 apple_uids 为空时：
# - 本地日程（无 apple_uid）：保留 ✓
# - Apple 同步日程（有 apple_uid）：删除 ✗
schedules = [s for s in schedules if not s.get("apple_uid") or s["apple_uid"] in apple_uids]
```

**影响**: 如果 `_caldav_fetch` 因网络问题返回空，所有已同步的 Apple 日历事件会被误删。

**修复方案**: 在 `apple_events` 为空时跳过删除逻辑，或区分"API 返回空"和"API 调用失败"。

### 7. `commands.py:132-136` - 未知命令不传递给 LLM

**问题**: `_handle_command()` 对未识别的斜杠命令返回"未知命令"并 `return True`，阻止消息继续传递给 LLM 处理。用户发送非预设的斜杠命令时，既不会得到 LLM 回复，也不会被记录到对话历史。

**建议**: 未匹配的命令应 `return False` 让消息继续流转，或明确文档化这是设计决策。

---

## 三、代码质量建议

### 8. `services/config_parser.py` 与 `utils/config_parser.py` 完全重复

两个文件内容 100% 相同（4 个函数：`get_text_value`、`get_bool_value`、`parse_list_config`、`get_int_value`）。`services/dashboard.py` 和 `services/message_renderer.py` 从 `services/` 版本导入，`services/dashboard_service.py` 和 `services/payload_client.py` 从 `utils/` 版本导入。

**建议**: 保留一份（建议 `utils/`），另一份改为从 `utils` 导入或删除。

### 9. `services/time_formatter.py` 与 `utils/time_formatter.py` 完全重复

同上，两个文件内容 100% 相同。`services/message_renderer.py` 从 `services/` 导入。

**建议**: 合并为一份。

### 10. `main.py:897` - `asyncio.create_task()` 无异常保护

```python
asyncio.create_task(self._delayed_schedule_reminder_scan())
```

如果 task 抛出异常，只有在 GC 时才会被 logged（`Task exception was never retrieved`），容易被忽略。

**建议**: 用 `self._schedule_task()` 包装，或显式 add_done_callback。

### 11. `habits.py:57` - `_setup_llm_template` 只设置 water 的 fallback

`HabitReminder._setup_llm_template()` 在 `__init__` 时调用 `self.llm_service.set_fallback_template()`。但 `SleepReminder._build_prompt()` 每次又重新 `set_fallback_template()`（根据是否超晚切换），说明初始设置可能不必要或存在竞态。

**建议**: 各子类自行管理 fallback 模板，不在基类 `__init__` 中设置。

### 12. `apple_calendar.py:71` - 使用 `urllib.request` 而非 `aiohttp`

插件开发规范要求"异步用 aiohttp/httpx，禁用 requests"。虽然 `apple_calendar.py` 的阻塞 I/O 已通过 `run_in_executor` 修复，但根本原因是使用了 `urllib.request` 而非 `aiohttp`。

**建议**: 长期重构为纯 `aiohttp` 实现，彻底消除线程池开销。
