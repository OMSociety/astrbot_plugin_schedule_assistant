# AGENTS.md

本文件写给在此仓库工作的 Agent。只写工具管不住、但可判定的约定；不描述状态，不列变更历史。

## 项目定位

AstrBot 插件（Star），提供早安播报、习惯提醒、日程提醒与 LLM 日程管理，可同步 Apple 日历与 Notion 待办。
Python 3.10+，宿主为 AstrBot 4.29.4（稳定 API）；测试与 lint 使用宿主虚拟环境。

## 目录职责

- `main.py`：Star 生命周期与装配，只做 wiring，不承载调度或文案逻辑。
- `scheduling.py`：唯一的调度入口。注册 basic job、扫描日程、预注册喝水与推送 job。
- `prompts.py`：五类内置提示词与 `render()`。
- `notices.py`：把数据拼成推送文本（时间标签、日程与待办格式）。
- `briefing.py`：早安播报的数据组装（天气、24 小时日程、Notion）。
- `calendar_sync.py`：Apple 日历同步与删除保护。
- `schedule_store.py`：唯一的本地持久化层。
- `apple_calendar.py`、`notion_client.py`、`weather.py`：外部服务客户端。
- `time_parser.py`：自然语言时间解析。
- `tools/schedule_tools.py`：4 个 LLM 工具。
- `tests/`：pytest 测试。

## 架构边界

- 发送只走框架主动 Agent：`add_active_job(payload={"session": umo, "note": note}, run_once=True, run_at=...)`。插件不得直接调用 `context.send_message` 或平台适配器发送。
- 调度只在 `scheduling.py` 内完成；`main.py` 不得注册 cron job。
- 持久化只经 `schedule_store.py`。KV 键只允许 `schedules_<umo>`，不得新增其他 KV 键。
- 推送文本只在 `notices.py` 组装，提示词模板只在 `prompts.py`。`scheduling.py` 不拼长文案。
- LLM 工具只从 `context.context.event.unified_msg_origin` 取当前会话，不缓存身份。
- 时区只取 `Settings.timezone`；不得在业务代码里硬编码 `Asia/Shanghai`。
- 所有推送为纯文本；不得引入 Markdown 渲染或平台降级分支。

## 生命周期与调度

- `initialize()` 装配服务并启动调度；`terminate()` 停止调度、关闭 Notion 与 Apple 客户端。
- 插件创建的 job 名必须以 `日程助手` 开头（`settings.JOB_PREFIX`）。
- basic job 一律 `persistent=False`；一次性推送用 `run_once=True` + `run_at` + `persistent=False`。
- 启动时先删除所有前缀 job，再按 `settings.target_umos` 重新注册，避免重启后残留任务重复触发。
- 目标会话只来自 `settings.target_umos`，经 `parse_target()` 校验为完整 UMO；非法项告警一次并跳过。

## 外部契约

- UMO 形如 `platform:message_type:session`；只接受 `FriendMessage` 与 `GroupMessage` 两种消息类型。
- 群聊按独立会话处理，群内共享一份日程，并接收全部推送。
- AstrBot 4.29.4 的主动 Agent 路径：cron manager 构造 `CronMessageEvent`，主 Agent 按会话人格与历史生成正文，并调用 `send_message_to_user` 发送。
- 4.30 计划提供 `ctx.agent`（`AgentService.run_turn`，默认由 Core 发送）。迁移时替换 `scheduling.py` 的任务说明组装，保留 `schedule_store.py` 与工具；在 4.29.4 上不得引用该接口。

## 验证

提交前依次通过：

```powershell
python -m ruff format .
python -m ruff check .
python -m pytest tests -q
```

涉及调度、配置或生命周期的改动，另在宿主实例热重载后确认：日志无异常、`list_jobs` 只有前缀匹配的 job、目标会话能收到推送。

## 禁止

- 不引入 `requests`、`apscheduler`。
- 不新增 persona、昵称、Markdown 相关配置。
- 不自动修改 `metadata.yaml` 的版本号、不打 tag、不发 Release；发版需明确指令。
- 不把用户配置、密钥或运行时数据写入仓库。
