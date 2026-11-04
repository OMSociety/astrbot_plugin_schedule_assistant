# Changelog

本项目的更改记录在此文件。

All notable changes to this project are documented in this file.

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.1] - 2026-11-04

### 新增

- **读取不完整时不再删除本地日程**：读取日历事件这一步会一并交回问题列表，日历发现失败、列出日历返回非 207、某个日历抓取失败、单个事件文件没拉到、WebCal 订阅读取失败都会记入其中；只有问题列表为空（这一轮确实读全了）才允许删除 Apple 端已不存在的本地日程。
- **读取不完整的提示**：同一原因只报一次 WARNING（写明本轮只做新增与更新、不删除本地日程），之后降为 DEBUG。

### 变更

- 本地日程的删除最多推迟一轮同步（默认 30 分钟）：等待下一轮读取完整再删。

### 修复

- **读取不完整时的静默删除**：此前某个日历抓取失败（或同时配置了 WebCal）会让该日历下带 Apple UID 的本地日程被判为「Apple 端已删除」并静默移除，用户只能看到日程消失。

### Added

- **Local schedules are no longer deleted when a read is incomplete**: the event read now also returns a list of problems — a failed discovery, a non-207 calendar listing, a failed per-calendar fetch, an individual event file that could not be retrieved, or a failed WebCal subscription read all land in it. Deletion of local schedules whose Apple event is gone happens only when that list is empty (the round really read everything).
- **A notice for incomplete reads**: the same reason is logged as WARNING once (stating that this round only adds and updates, without deleting local schedules), then downgraded to DEBUG.

### Changed

- Deleting a local schedule is postponed by at most one sync round (30 minutes by default) while waiting for a complete read.

### Fixed

- **Silent deletion on an incomplete read**: a failed per-calendar fetch (or a configured WebCal feed) used to make local schedules carrying an Apple UID look like events deleted on the Apple side, and they were removed silently — the user only saw the schedule disappear.

## [1.3.0] - 2026-11-04

### 新增

- **CalDAV 服务器地址可配置**（`calendar_sync_settings.apple_calendar.caldav_host`）：留空使用 `caldav.icloud.com`，可填 `caldav.icloud.com.cn`，或账号自己的分区主机（`pXX-caldav.icloud.com.cn`）。
- **默认入口被拒绝认证时自动回退中国大陆区入口**：同一份凭据会再试 `caldav.icloud.com.cn` 一次，生效的入口写进日志；自行指定了 `caldav_host` 时不回退。
- **日志给出可用日历清单**：发现成功后按「日历名 → UUID」列出一次，`calendar_id` 照此填写即可。

### 修复

- **CalDAV 写入失败的提示改为按状态码给出可行动原因**：凭据被拒（403 且响应体为空）、网络不通与响应异常此前报出的都是同一句「CalDAV 未连接，无法创建事件」，发现阶段还会误报「未配置 Apple 日历」。现按 401（凭据未填全）/ 403（App 专用密码错误或失效）/ 无法连接网络 / 响应中没有 principal URL 分别说明，同一原因只报一次 ERROR。
- **发现路径只认 207 状态码**：带错误页正文的 4xx 响应不再被正则降级当成发现成功。
- **列出日历失败时记录状态码**：`_list_calendars` 在非 207 响应下不再静默返回空列表。

### 变更

- 创建日程时的「CalDAV 未连接，无法创建事件」由 ERROR 降为 WARNING（原因已在发现阶段以 ERROR 报出）。
- `apple_calendar.calendar_id` 的填写说明改指向日志里的日历清单。

### Added

- **Configurable CalDAV server address** (`calendar_sync_settings.apple_calendar.caldav_host`): leave blank for `caldav.icloud.com`, set `caldav.icloud.com.cn`, or your account's partition host (`pXX-caldav.icloud.com.cn`).
- **Automatic fallback to the Mainland China entry point** when the default entry refuses authentication: the same credentials are retried once against `caldav.icloud.com.cn`, and the entry in effect is written to the log; a user-specified `caldav_host` is never switched.
- **Calendar list in the log**: once calendars are discovered, each is listed as `name → UUID`, which is what `calendar_id` takes.

### Fixed

- **CalDAV write failures now report an actionable reason derived from the status code**: a refused credential (403 with an empty body), an unreachable network and an unexpected response all produced the same `CalDAV 未连接，无法创建事件` line before, while discovery misreported it as `未配置 Apple 日历`. Reasons are now distinguished per 401 (credentials incomplete) / 403 (app-specific password wrong or expired) / network unreachable / no principal URL in the response, and the same reason is logged as ERROR only once.
- **Discovery accepts nothing but status 207**: a 4xx response whose body happens to contain a principal path is no longer downgraded into a successful discovery.
- **Listing calendars now logs the status code**: `_list_calendars` no longer returns an empty list silently on a non-207 response.

### Changed

- The `CalDAV 未连接，无法创建事件` line on event creation is now a WARNING (the reason itself is reported as ERROR during discovery).
- The `apple_calendar.calendar_id` hint now points at the calendar list in the log.

## [1.2.1] - 2026-09-25

### 修复

- **Apple 日历写操作按 HTTP 状态码判定成败**：此前 4xx（凭据失效、日历只读）会被当作成功并写入无效 UID，下一轮同步再据此把本地日程静默删除。
- 创建成功的提示只在真正写入 Apple 日历后出现。
- 修改带 UID 的日程会把改动写回同一个日历事件，不再被下一轮同步用 Apple 旧值还原；写回失败时改为脱离 Apple 同步，避免用户改期被静默还原。
- **提醒的防重标记改为确认送达后才写入**：此前发送失败（含发送函数返回 `False` 的常见路径）也会落标记，导致该日程本期永久不再提醒。
- 修正 iCloud 降级提取路径的 principal 与 calendar-home 地址拼接（此前多一个斜杠会把账号 ID 当成主机名）。
- 日程工具对 LLM 显式传入的 `null` 参数不再抛内部异常；`days` 的边界值回落到默认窗口。
- Apple 日历的失败日志不再整段打印响应体（截断并保留状态码）。

### 变更

- 提醒未送达时会记录告警并保留重试机会；窗口内的重试会重新生成提醒文案（同一条提醒最多数次，窗口过后不再触发）。
- Apple 写回失败时该日程会脱离 Apple 同步：本地改动得以保留，代价是 Apple 侧的旧事件可能在下轮同步中作为新事件拉回，形成一条重复日程。

### Fixed

- **Apple Calendar write operations now judge success by the HTTP status code**: previously a 4xx (expired credentials, read-only calendar) was treated as success and an invalid UID was written, which the next sync then used to silently delete the local schedule.
- The creation-success notice now appears only after the event has actually been written to Apple Calendar.
- Editing a schedule that has a UID now writes the change back to the same calendar event, and it is no longer reverted by the next sync from the stale Apple value; when the write-back fails, the item detaches from Apple sync instead, so the user's reschedule is not silently reverted.
- **The reminder dedup marker is now written only after delivery is confirmed**: previously a failed send (including the common path where the send function returns `False`) still set the marker, so that schedule was never reminded about again for the current period.
- Fixed the principal and calendar-home URL concatenation in the iCloud fallback discovery path (an extra slash previously made the account ID be treated as a hostname).
- The schedule tools no longer raise an internal exception for a `null` argument passed explicitly by the LLM; out-of-range `days` values fall back to the default window.
- Apple Calendar failure logs no longer print the whole response body (it is truncated and the status code is kept).

### Changed

- When a reminder is not delivered, a warning is logged and the retry opportunity is kept; a retry within the window regenerates the reminder text (the same reminder fires at most a few times, and no longer triggers once the window has passed).
- When the Apple write-back fails, the schedule detaches from Apple sync: local changes are preserved, at the cost that the stale Apple-side event may be pulled back as a new event on the next sync, producing a duplicate schedule.

## [1.2.0] - 2026-09-23

### 新增

- **日程支持时间区间与全天**：创建 / 修改日程可写「明天9点到11点」（区间）、「明天全天」或纯日期（全天）；两端纯日期的区间（「明天到后天」）按全天处理，多日取开始日。工具新增 `end_datetime_str`（create_schedule）与 `new_end_datetime`（update_schedule）参数。
- **全天事件写入 Apple 日历为全天事件**（`DTSTART;VALUE=DATE` + 次日结束）；日程列表与今日日程的时间标签支持区间（`15:00-16:30`）与全天（`📅 全天`）。

### 修复

- **修复日程提醒扫描与 Apple 定时同步整体不执行**：锁获取写法 `asyncio.wait_for(lock.acquire(), timeout=0)` 在该语义下必超时（空闲锁也一样），两条定时链路每轮都直接返回、从未真正运行；现改为非阻塞抢锁，锁被占用时跳过本轮。
- 修复提前量窗口漏提醒：判定由「开始前 N 分钟 ±2 分钟」的窄窗口改为「开始前 N 分钟内均触发」（窗口含上边界，扫描间隔不大于提前提醒分钟数时必达）。
- 修复长提前量下同一事件重复提醒：防重标记此前 1 小时后自动失效，提前量大于约 1 小时时事件会在开始前 5 分钟兜底窗口被再次提醒；现防重标记持续有效（事件改期时重置，改期重新提醒）。
- 修复日程列表对纯日期时间串的解析：此前仅认 `%Y-%m-%d %H:%M`，date-only 条目会被静默跳过（全天日程现按日期范围纳入列表）。
- 修复通过工具创建日程时未记录 Apple 事件 UID 的问题：此前下一轮同步会把同一事件当成新事件再入库一份，早安播报里会出现两行。
- 修复「明天下午3点」这类带时段词的口语时间表达解析失败的问题。

### 变更

- 提醒文案的时间标签支持区间（`14:30-16:30`）；日程提醒扫描前先刷新一次 Apple 同步，Apple 事件新增或改期后也会触发一次即时补扫。
- Apple→本地同步在无变化时不再写盘；同步结果新增结束时间与全天标记，改期会重新提醒一次。

## [1.1.0] - 2026-09-13

### 新增

- **WebUI 四语本地化**：新增 `zh-CN` / `en-US` / `ru-RU` / `ja-JP` 四份 i18n 文件（`.astrbot-plugin/i18n/`），插件名、简介与全部 84 条配置项文案在四种界面语言下均正确显示；中文文案与配置 schema 保持逐字镜像。Notion 数据库前缀示例（`事务:` / `阅读:`）为必须保留的字面量，各语言维持原文。
- README 新增多语言版本（English / Русский / 日本語），顶部提供语言导航。

## [1.0.7] - 2026-09-08

### 变更

- 移除 QQ 官方平台主动推送的降级分支：上游 AstrBot ([#9914](https://github.com/AstrBotDevs/AstrBot/pull/9914)) 已支持 QQ 官方 `send_by_session` 主动推送的原声 Markdown，此前为避免 `####`/`**` 源码暴露而做的「QQ 友好排版降级」不再需要。主动推送（早安播报/习惯提醒等）现直接走原生 Markdown 渲染，与被动回复行为一致。
- 显式配置 `qq_markdown_enabled=False` 时，仍保留 QQ 友好排版兜底（该配置项行为不变）。

## [1.0.6] - 2026-09-06

### 修复

- 修复 LLM 熔断期内提醒文案串用的问题：兜底文案改为随每次生成显式传入，习惯提醒的兜底不再可能被早安播报/日程提醒复用。
- 修复按日程 ID 删除时不同步删除 Apple 日历同名事件的问题（此前仅按关键词删除会同步，被删日程会在下次同步时被拉回）。
- 修正 Apple Calendar 兜底解析路径中的 4 处正则转义错误（此前匹配"反斜杠+字母"而非预期字符类，导致解析失败）。

### 变更

- 升级使用框架 `get_using_provider_async` 接口（原同步接口已标记废弃）。
- 移除五个已无调用的遗留方法与读取不存在配置键的死分支，清理过程性日志级别（行为不变）。

## [1.0.5] - 2026-09-02

### 修复

- **Apple 日历 `create_event` 补全 DESCRIPTION 与 ICS 转义**：此前创建事件时不写入备注（`description`），且 `SUMMARY` 未做 RFC 5545 转义，标题含分号/逗号/换行时会导致 ICS 解析错乱。现补 `DESCRIPTION` 行，并对 SUMMARY/DESCRIPTION 做 `\` `;` `,` 换行转义

## [1.0.4] - 2026-09-01

### 安全

- **WebCal 订阅地址增加 SSRF 校验**：`webcal_urls` 此前直接丢给 aiohttp 请求且无地址校验。现校验仅允许公网 `https://`（`webcal://` 自动转 `https://`），拒绝 `localhost`、内网（`192.168.x` / `10.x`）、云元数据（`169.254.169.254`）等地址；README 补充说明

## [1.0.3] - 2026-09-01

### 修复

- **修复早安播报默认模板中条件式占位符未求值的问题**：`DEFAULT_PROMPT_MORNING` 里的 `{weather_forecast if weather_forecast else "暂无"}` 是 format 风格写法，但 `render_prompt` 用 `.replace` 替换、无法求值，会导致播报原文中直接出现这段代码文字。改为 `{weather_forecast}`，兜底文案交给调用方（`weather_forecast or "暂无"`）

## [1.0.2] - 2026-09-01

### 新增

- **提醒 Prompt 全部配置化**：早安播报、洗澡 / 睡觉 / 喝水提醒、日程提醒的 LLM 提示词模板改为可配置项（配置 `prompt_settings` 分组下的 `prompt_morning` / `prompt_bath` / `prompt_sleep` / `prompt_water` / `prompt_schedule`），支持 `{占位符}` 变量替换，无需改代码即可定制提醒语气
- 内置 `prompt_config.py` 集中存放默认模板（配置留空时使用内置默认，老用户零影响）
- 新增时间格式辅助：`_format_time_label`（把 `2026-09-01 14:30` 转成 `14:30`）、`_format_ahead_label`（把提前分钟数转成"10 分钟后开始"）

### 变更

- 日程提醒提示词**从旧版僵化模板改为自然口语新版**（15~30 字、像朋友随口一句），并新增时间解析；LLM 失败时的 fallback 文案不变
- 配置默认值留空（`""`）→ 走内置默认模板；用户填了配置则用配置模板

## [1.0.1] - 2026-08-16

### 修复

- **修复 QQ 官方平台主动推送（早安播报/习惯提醒等定时消息）显示 Markdown 源码的问题**：AstrBot 的 QQ 官方适配器 `send_by_session`（主动推送链路）不支持 `use_markdown_` 标志，只发送纯文本 content，导致 `####`/`**` 等 md 符号原样暴露给用户。现对 QQ 官方主动推送降级为 QQ 友好排版（标题转【】、去除加粗、表格转"键：值"），不再显示 md 源码
- 被动回复（对话中提问触发的回复）不受影响，仍走原生 Markdown 渲染

### 新增

- 新增 4 个主动推送降级测试（QQ 官方降级 / 被动回复保留 native / webchat strip 不受影响 / markdown 关闭时维持原文），共 33 个用例

### 变更

- QQ 官方平台收到的定时播报：从"带 `####`/`**` 符号的 md 原文"变为"QQ 友好排版的干净文本"（如 `【📅 早安播报】`）；webchat 等其他平台行为不变
