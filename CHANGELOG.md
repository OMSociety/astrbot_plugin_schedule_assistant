# Changelog

## [1.0.3] - 2026-09-01

### 🐛 Bug 修复

- **修复早安播报默认模板中条件式占位符未求值的问题**：`DEFAULT_PROMPT_MORNING` 里的 `{weather_forecast if weather_forecast else "暂无"}` 是 format 风格写法，但 `render_prompt` 用 `.replace` 替换、无法求值，会导致播报原文中直接出现这段代码文字。改为 `{weather_forecast}`，兜底文案交给调用方（`weather_forecast or "暂无"`）

## [1.0.2] - 2026-09-01

### ✨ 新功能

- **提醒 Prompt 全部配置化**：早安播报、洗澡 / 睡觉 / 喝水提醒、日程提醒的 LLM 提示词模板改为可配置项（配置 `prompt_settings` 分组下的 `prompt_morning` / `prompt_bath` / `prompt_sleep` / `prompt_water` / `prompt_schedule`），支持 `{占位符}` 变量替换，无需改代码即可定制提醒语气
- 内置 `prompt_config.py` 集中存放默认模板（配置留空时使用内置默认，老用户零影响）
- 新增时间格式辅助：`_format_time_label`（把 `2026-09-01 14:30` 转成 `14:30`）、`_format_ahead_label`（把提前分钟数转成"10 分钟后开始"）

### ⚠️ 行为变化

- 日程提醒提示词**从旧版僵化模板改为自然口语新版**（15~30 字、像朋友随口一句），并新增时间解析；LLM 失败时的 fallback 文案不变
- 配置默认值留空（`""`）→ 走内置默认模板；用户填了配置则用配置模板

## [1.0.1] - 2026-08-16

### 🐛 Bug 修复

- **修复 QQ 官方平台主动推送（早安播报/习惯提醒等定时消息）显示 Markdown 源码的问题**：AstrBot 的 QQ 官方适配器 `send_by_session`（主动推送链路）不支持 `use_markdown_` 标志，只发送纯文本 content，导致 `####`/`**` 等 md 符号原样暴露给用户。现对 QQ 官方主动推送降级为 QQ 友好排版（标题转【】、去除加粗、表格转"键：值"），不再显示 md 源码
- 被动回复（对话中提问触发的回复）不受影响，仍走原生 Markdown 渲染

### 🧪 测试

- 新增 4 个主动推送降级测试（QQ 官方降级 / 被动回复保留 native / webchat strip 不受影响 / markdown 关闭时维持原文），共 33 个用例

### ⚠️ 行为变化

- QQ 官方平台收到的定时播报：从"带 `####`/`**` 符号的 md 原文"变为"QQ 友好排版的干净文本"（如 `【📅 早安播报】`）；webchat 等其他平台行为不变
