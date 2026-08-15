# Changelog

> 本项目仍处于活跃维护中。

---

## [2.0.0] - 2026-08-15（当前版本）

> 版本说明：v2.1.0~v2.5.0 的中间迭代已归档（详见 Git 历史），
> 版本号重定为 2.0.0。本次为全量检查后的重构版本，包含以下全部改动：

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

### ⚙️ 配置变更
- `whitelist_qq_ids` 与 `target_user_ids` 合并为 **`user_ids`**（用户名单 ID 列表，每行一个接收自动提醒的用户 ID，支持 UMO 格式）；旧键已删除，不再兼容读取
- 移除 **`broadcast_to_all_known_users`**（历史活跃用户开关）：日程扫描 / Apple 同步等任务本就固定覆盖历史活跃用户，该开关不受其控制，删除后行为不变
- 移除 **`user_platform_bindings`**（用户平台绑定配置）：`user_ids` 中的 UMO 条目（`平台ID:会话类型:用户ID`）会在名单解析时自动注册平台路由，无需单独配置；纯 ID 用户由会话记忆 + 全局 `send_platform_id` 自动路由
- 移除 **`default_session_type` / `send_platform_id`**：会话类型固定为私聊 FriendMessage（UMO 条目可自带 session_type）；平台路由由 UMO 条目 + 会话记忆 + 可用平台自动完成，无需全局默认平台
- **`user_ids` 移入「基础设置」分组**（原「消息推送」分组删除），与人格/称呼放在一起
- 移除 **`admin_uids`**（管理员配置）：`_is_admin` 判定方法无任何调用者，插件无需要权限校验的命令/操作，属死配置

### 🔧 代码质量提升
- `BROADCAST_MD_OVERRIDE` 三处重复定义收敛到 `constants.py` 统一引用
- Apple 日历同步新增日程改用 `ScheduleItem` dataclass 序列化，消除手写 dict 与字段定义的隐式耦合
- 日程提醒扫描复用插件已创建的 `ScheduleReminder` 实例，不再每轮新建
- `NotionClient._relevant` 冗余条件化简
- `_extract_sender_name` 增加 `get_sender_id` 防御性调用
- 作者统一为 `OMSociety`（metadata / `__init__.py` / README）
- `requirements.txt` 补充 markdownify / markdown-it-py 可选依赖说明
