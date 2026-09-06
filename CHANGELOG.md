# Changelog

本项目所有重要更改都会记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.6] - 2026-09-06

### 🐛 修复

- 修复 LLM 熔断期内提醒文案串用的问题：兜底文案改为随每次生成显式传入，习惯提醒的兜底不再可能被早安播报/日程提醒复用。
- 修复按日程 ID 删除时不同步删除 Apple 日历同名事件的问题（此前仅按关键词删除会同步，被删日程会在下次同步时被拉回）。
- 修正 Apple Calendar 兜底解析路径中的 4 处正则转义错误（此前匹配"反斜杠+字母"而非预期字符类，导致解析失败）。

### ⚙️ 变更

- 升级使用框架 `get_using_provider_async` 接口（原同步接口已标记废弃）。
- 移除五个已无调用的遗留方法与读取不存在配置键的死分支，清理过程性日志级别（行为不变）。

## [1.0.5] - 2026-09-02

### 🐛 修复

- **Apple 日历 `create_event` 补全 DESCRIPTION 与 ICS 转义**：此前创建事件时不写入备注（`description`），且 `SUMMARY` 未做 RFC 5545 转义，标题含分号/逗号/换行时会导致 ICS 解析错乱。现补 `DESCRIPTION` 行，并对 SUMMARY/DESCRIPTION 做 `\` `;` `,` 换行转义

## [1.0.4] - 2026-09-01

### 🔒 安全

- **WebCal 订阅地址增加 SSRF 校验**：`webcal_urls` 此前直接丢给 aiohttp 请求且无地址校验。现校验仅允许公网 `https://`（`webcal://` 自动转 `https://`），拒绝 `localhost`、内网（`192.168.x` / `10.x`）、云元数据（`169.254.169.254`）等地址；README 补充说明

## [1.0.3] - 2026-09-01

### 🐛 修复

- **修复早安播报默认模板中条件式占位符未求值的问题**：`DEFAULT_PROMPT_MORNING` 里的 `{weather_forecast if weather_forecast else "暂无"}` 是 format 风格写法，但 `render_prompt` 用 `.replace` 替换、无法求值，会导致播报原文中直接出现这段代码文字。改为 `{weather_forecast}`，兜底文案交给调用方（`weather_forecast or "暂无"`）

## [1.0.2] - 2026-09-01

### ✨ 新增

- **提醒 Prompt 全部配置化**：早安播报、洗澡 / 睡觉 / 喝水提醒、日程提醒的 LLM 提示词模板改为可配置项（配置 `prompt_settings` 分组下的 `prompt_morning` / `prompt_bath` / `prompt_sleep` / `prompt_water` / `prompt_schedule`），支持 `{占位符}` 变量替换，无需改代码即可定制提醒语气
- 内置 `prompt_config.py` 集中存放默认模板（配置留空时使用内置默认，老用户零影响）
- 新增时间格式辅助：`_format_time_label`（把 `2026-09-01 14:30` 转成 `14:30`）、`_format_ahead_label`（把提前分钟数转成"10 分钟后开始"）

### ⚙️ 变更

- 日程提醒提示词**从旧版僵化模板改为自然口语新版**（15~30 字、像朋友随口一句），并新增时间解析；LLM 失败时的 fallback 文案不变
- 配置默认值留空（`""`）→ 走内置默认模板；用户填了配置则用配置模板

## [1.0.1] - 2026-08-16

### 🐛 修复

- **修复 QQ 官方平台主动推送（早安播报/习惯提醒等定时消息）显示 Markdown 源码的问题**：AstrBot 的 QQ 官方适配器 `send_by_session`（主动推送链路）不支持 `use_markdown_` 标志，只发送纯文本 content，导致 `####`/`**` 等 md 符号原样暴露给用户。现对 QQ 官方主动推送降级为 QQ 友好排版（标题转【】、去除加粗、表格转"键：值"），不再显示 md 源码
- 被动回复（对话中提问触发的回复）不受影响，仍走原生 Markdown 渲染

### ✨ 新增

- 新增 4 个主动推送降级测试（QQ 官方降级 / 被动回复保留 native / webchat strip 不受影响 / markdown 关闭时维持原文），共 33 个用例

### ⚙️ 变更

- QQ 官方平台收到的定时播报：从"带 `####`/`**` 符号的 md 原文"变为"QQ 友好排版的干净文本"（如 `【📅 早安播报】`）；webchat 等其他平台行为不变
