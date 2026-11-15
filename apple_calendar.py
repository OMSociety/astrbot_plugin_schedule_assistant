"""Apple iCloud CalDAV 日历同步模块
支持：日历发现 / PROPFIND读取事件 / 创建&删除事件 / 时区正确处理"""

import asyncio
import base64
import html
import ipaddress
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, tzinfo
from urllib.parse import urljoin, urlparse

import aiohttp
from astrbot.api import logger

__all__ = ["AppleCalendar"]

# CalDAV 发现入口：PROPFIND 打到该地址取回当前用户的 principal URL。
CALDAV_ENTRY_URL = "https://caldav.icloud.com/"
# 中国大陆区（云上贵州运营）的 iCloud 入口，凭据被 .com 拒绝时回退到这里。
CALDAV_CN_ENTRY_URL = "https://caldav.icloud.com.cn/"


def _escape_ics_text(text: str) -> str:
    """按 RFC 5545 转义 TEXT 值（反斜杠、分号、逗号、换行）。"""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


class AppleCalendar:
    """Apple iCloud / CalDAV 日历客户端"""

    def __init__(
        self,
        username: str | None = None,
        app_password: str | None = None,
        webcal_urls: list[str] | None = None,
        calendar_id: str | None = None,
        caldav_host: str | None = None,
        timezone: tzinfo | None = None,
    ):
        self.username = username
        self.app_password = app_password
        self.webcal_urls = webcal_urls or []
        self._tz = timezone
        self._principal_url: str | None = None
        self._caldav_base_url: str | None = None
        self._caldav_base_domain: str | None = None
        self._discovered = False
        self._discover_lock = asyncio.Lock()
        self._fetch_lock = asyncio.Lock()
        self._events_cache: dict[int, dict] = {}
        self._events_cache_ttl_seconds = 300
        self._calendars_cache: list[dict] = []
        self._calendars_cache_ttl_seconds = 300
        self._calendars_ts: float = 0.0
        self._last_ics_discovery_log_ts = 0.0
        self._last_ics_discovery_count: int | None = None
        self._calendar_id = calendar_id
        self._last_discover_reason: str | None = None
        self._caldav_host = (caldav_host or "").strip()
        self._caldav_entry_url = self._normalize_entry_url(self._caldav_host)
        self._calendars_logged = False

    @staticmethod
    def _normalize_entry_url(host: str) -> str:
        """把配置的 CalDAV 主机规范成 PROPFIND 入口 URL；空值用默认入口。"""
        host = (host or "").strip()
        if not host:
            return CALDAV_ENTRY_URL
        if "://" not in host:
            host = "https://" + host
        return host.rstrip("/") + "/"

    def _auth_header(self) -> str:
        creds = f"{self.username}:{self.app_password}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    async def _aiohttp_request_with_status(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: int = 30,
        retries: int = 3,
    ) -> tuple[str | None, int | None]:
        """异步 HTTP 请求（aiohttp），带重试，返回 (响应体文本, 状态码)。

        状态码语义（写操作调用方据此判定成败）：
        - 收到 HTTP 响应：返回 (文本, 状态码)，**包括 4xx/5xx**——响应体可能非空，
          光看"有没有响应"无法区分成功与鉴权失败/路径不存在；
        - 传输层异常（ClientError / TimeoutError）且重试耗尽：返回 (None, None)。
        """
        headers = dict(headers or {})
        headers.setdefault("User-Agent", "curl/7.88.1")
        last_error = None
        for attempt in range(retries):
            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.request(
                        method,
                        url,
                        data=data,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                        allow_redirects=False,
                    ) as resp,
                ):
                    status = resp.status
                    if 300 <= status < 400:
                        logger.warning(
                            f"[AppleCalendar] 拒绝跟随重定向 {url} -> {status}"
                        )
                        return None, status
                    if status >= 500 and attempt < retries - 1:
                        await asyncio.sleep(1 * (attempt + 1))
                        last_error = aiohttp.ClientResponseError(
                            resp.request_info, resp.history, status=status
                        )
                        continue
                    return await resp.text(encoding="utf-8", errors="replace"), status
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
        logger.debug(
            f"[AppleCalendar] 请求异常 {url}: {type(last_error).__name__}: {last_error}"
        )
        return None, None

    async def _aiohttp_request(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: int = 30,
        retries: int = 3,
    ) -> str | None:
        """异步 HTTP 请求（aiohttp），带重试，只返回响应体文本。

        调用方需要判定 HTTP 状态码（写操作）时改用 ``_aiohttp_request_with_status``。
        注意：4xx/5xx 只要收到响应就返回响应体文本（可能与成功同样非空），
        传输失败返回 None。
        """
        text, _status = await self._aiohttp_request_with_status(
            url,
            method=method,
            data=data,
            headers=headers,
            timeout=timeout,
            retries=retries,
        )
        return text

    @staticmethod
    def _truncate_for_log(text: str | None, limit: int = 200) -> str:
        """截断响应体供日志使用：保留前 limit 个字符，够排障又不淹没日志。

        iCloud 的错误页可能是整页 HTML，未截断会把大段无关内容打进日志。
        """
        raw = repr(text)
        return raw if len(raw) <= limit else f"{raw[:limit]}…(truncated)"

    @staticmethod
    def _clean_href(raw: str) -> str:
        href = html.unescape((raw or "").strip())
        href = href.replace("\u200b", "")
        href = re.sub(r"[\r\n\t]", "", href)
        href = href.strip("'" + "<>\\")
        for splitter in ('">', "'>", "<", ">"):
            if splitter in href:
                href = href.split(splitter, 1)[0]
        m = re.search(r"(https?://[^\s<>'\"]+|/[^\s<>'\"]+)", href)
        href = m.group(1) if m else href
        href = re.sub(r"\s+", "", href)
        return href

    @staticmethod
    def _extract_href(xml_text: str, parent_tag_suffix: str) -> str | None:
        if not xml_text:
            return None
        try:
            root = ET.fromstring(xml_text)
            for elem in root.iter():
                if elem.tag.endswith(parent_tag_suffix):
                    for child in elem.iter():
                        if child.tag.endswith("href") and child.text:
                            href = AppleCalendar._clean_href(child.text)
                            if href:
                                return href
        except ET.ParseError:
            pass
        return None

    @staticmethod
    def _extract_calendar_names(xml_text: str) -> dict[str, str]:
        """从 multistatus 里取出 {日历路径: 显示名}。

        displayname 是日历在 Apple 端的名称，用户据此认出要填哪个 UUID。
        """
        names: dict[str, str] = {}
        if not xml_text:
            return names
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return names
        for resp in root.iter():
            if not resp.tag.endswith("response"):
                continue
            href = None
            displayname = ""
            for child in resp.iter():
                if href is None and child.tag.endswith("href") and child.text:
                    href = AppleCalendar._clean_href(child.text)
                elif child.tag.endswith("displayname") and child.text:
                    displayname = child.text.strip()
            if href:
                names.setdefault(href, displayname)
        return names

    @staticmethod
    def _to_absolute_url(base: str, href: str) -> str | None:
        href = AppleCalendar._clean_href(href)
        if not href:
            return None
        if href.startswith(("http://", "https://")):
            candidate = href.rstrip("/")
        else:
            candidate = urljoin(base.rstrip("/") + "/", href).rstrip("/")
        parsed = urlparse(candidate)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return candidate

    def _describe_http_failure(self, status: int | None, body: str | None) -> str:
        """把 PROPFIND 的失败翻译成用户能照着做的说明。

        状态码是唯一可靠判据：iCloud 在凭据被拒时返回 403 且响应体为空，
        仅凭响应体是否为空无法区分鉴权失败、路径不存在与传输层失败。
        """
        if status is None:
            return "无法连接 Apple 服务器（网络不通或被拦截），请检查本机网络与代理"
        if status == 401:
            return "Apple 未接受凭据（HTTP 401），请确认 Apple ID 邮箱与 App 专用密码都已填写"
        if status == 403:
            return (
                "Apple 拒绝认证（HTTP 403）：App 专用密码错误或已失效。"
                "需在 appleid.apple.com 重新生成「App 专用密码」，不能用 iCloud 登录密码；"
                "若刚生成仍失败，请把这一行反馈给插件作者"
            )
        return f"PROPFIND 返回 HTTP {status}: {self._truncate_for_log(body)}"

    def _report_discover_failure(self, reason: str) -> None:
        """同一条失败原因只报一次 ERROR，之后降为 DEBUG，避免每轮同步刷屏。"""
        if reason == self._last_discover_reason:
            logger.debug(f"[AppleCalendar] CalDAV 发现失败：{reason}")
            return
        self._last_discover_reason = reason
        logger.error(f"[AppleCalendar] CalDAV 发现失败：{reason}")

    async def _discover(self) -> bool:
        """发现 principal URL 和 calendar home set URL"""
        if self._discovered or not self.username or not self.app_password:
            return bool(self._discovered)
        async with self._discover_lock:
            if self._discovered:
                return True
            body1 = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:current-user-principal/></D:prop></D:propfind>'
            headers = {
                "Authorization": self._auth_header(),
                "Content-Type": "text/xml",
            }
            resp1, status1 = await self._aiohttp_request_with_status(
                self._caldav_entry_url,
                method="PROPFIND",
                data=body1,
                headers=headers,
            )
            if status1 == 403 and self._caldav_entry_url == CALDAV_ENTRY_URL:
                # 中国大陆区的 iCloud 由云上贵州运营，入口在 caldav.icloud.com.cn：
                # .com 拒绝凭据时再试一次国区入口，通了就后续请求都走它。
                cn_resp, cn_status = await self._aiohttp_request_with_status(
                    CALDAV_CN_ENTRY_URL,
                    method="PROPFIND",
                    data=body1,
                    headers=headers,
                )
                if cn_status == 207:
                    self._caldav_entry_url = CALDAV_CN_ENTRY_URL
                    resp1, status1 = cn_resp, cn_status
                    logger.info(
                        "[AppleCalendar] caldav.icloud.com 拒绝凭据，"
                        f"已改用中国大陆区入口 {CALDAV_CN_ENTRY_URL}"
                    )
                else:
                    self._report_discover_failure(
                        self._describe_http_failure(cn_status, cn_resp)
                        + f"（已同时尝试中国大陆区入口 {CALDAV_CN_ENTRY_URL}）"
                    )
                    return False
            if status1 != 207:
                self._report_discover_failure(
                    self._describe_http_failure(status1, resp1)
                )
                return False
            principal_href = self._extract_href(resp1, "current-user-principal")
            if not principal_href:
                m = re.search(r"(/\d+/\w+)/?$", resp1)
                # 捕获组自带前导 "/"，再拼一次会得到 "//…"；urljoin 把 "//host/path"
                # 当网络路径引用（netloc=数字 ID），后续 PROPFIND 会打到错误主机
                principal_href = "/" + m.group(1).lstrip("/") if m else None
            if not principal_href:
                self._report_discover_failure("响应中没有 principal URL（HTTP 207）")
                return False
            self._principal_url = self._to_absolute_url(
                self._caldav_entry_url.rstrip("/"), principal_href
            )
            if not self._principal_url:
                self._report_discover_failure("principal URL 组装失败")
                return False
            logger.debug(f"[AppleCalendar] principal URL: {self._principal_url}")
            body2 = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><C:calendar-home-set/></D:prop></D:propfind>'
            resp2, status2 = await self._aiohttp_request_with_status(
                self._principal_url,
                method="PROPFIND",
                data=body2,
                headers=headers,
            )
            if status2 != 207:
                self._report_discover_failure(
                    self._describe_http_failure(status2, resp2)
                )
                return False
            cal_home_href = self._extract_href(resp2, "calendar-home-set")
            if not cal_home_href:
                m = re.search(r"https?://[^\s<>\"']+/calendars/", resp2)
                if m:
                    cal_home_href = m.group(0).rstrip("/")
                else:
                    m = re.search(r"/(\d+/calendars/?)", resp2)
                    if m:
                        # 同上：统一 lstrip("/") 后再补一个前导 "/"，避免 "//…"
                        cal_home_href = "/" + m.group(1).lstrip("/").rstrip("/")
            if not cal_home_href:
                self._report_discover_failure(
                    "响应中没有 calendar home set URL（HTTP 207）"
                )
                return False
            self._caldav_base_url = self._to_absolute_url(
                self._principal_url, cal_home_href
            )
            if not self._caldav_base_url:
                self._report_discover_failure("calendar home set URL 组装失败")
                return False
            self._caldav_base_domain = urlparse(self._caldav_base_url).netloc
            self._discovered = True
            self._last_discover_reason = None
            logger.info(
                f"[AppleCalendar] CalDAV 已连接: {self._caldav_entry_url.rstrip('/')}"
                f" (base={self._caldav_base_url})"
            )
            return True

    async def _caldav_fetch_with_status(
        self, cal_url: str
    ) -> tuple[list[dict], str | None]:
        """纯异步 CalDAV 抓取：PROPFIND → 并发拉 .ics → 解析。

        PROPFIND 本身不带时间窗口过滤，调用方自行按需筛选。

        Returns:
            ``(事件列表, 失败原因)``：原因非 None 表示这份列表不完整
            （PROPFIND 非 207，或有 .ics 没拉到）——此时列表里缺席的事件
            无法与"事件已被删除"区分，调用方不得据此判定删除。
        """
        body = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:href/></D:prop></D:propfind>'
        resp, status = await self._aiohttp_request_with_status(
            cal_url.rstrip("/") + "/",
            method="PROPFIND",
            data=body,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "text/xml",
                "Depth": "1",
            },
        )
        if status != 207:
            return [], (
                "抓取日历事件失败"
                f"（status={status if status is not None else '无响应'}）"
            )
        ics_urls: list[str] = []
        seen_urls: set[str] = set()
        for m in re.findall(r"<(?:D:)?href[^>]*>([^<]+)</(?:D:)?href>", resp):
            href = m.strip()
            if href.endswith(".ics"):
                if href.startswith("/"):
                    ics_url = f"https://{self._caldav_base_domain}{href}"
                elif href.startswith("https://"):
                    ics_url = href
                else:
                    ics_url = f"{cal_url.rstrip('/')}/{href}"
                if ics_url not in seen_urls:
                    seen_urls.add(ics_url)
                    ics_urls.append(ics_url)
        if not ics_urls:
            return [], None
        now_ts = time.monotonic()
        current_count = len(ics_urls)
        if (
            self._last_ics_discovery_count != current_count
            or (now_ts - self._last_ics_discovery_log_ts) >= 300
        ):
            logger.debug(f"[AppleCalendar] 发现 {current_count} 个事件文件")
            self._last_ics_discovery_count = current_count
            self._last_ics_discovery_log_ts = now_ts

        async def _fetch_one(url: str) -> str | None:
            return await self._aiohttp_request(
                url, headers={"Authorization": self._auth_header()}, timeout=10
            )

        results = await asyncio.gather(*[_fetch_one(u) for u in ics_urls])
        events: list[dict] = []
        failed = 0
        for ics_data in results:
            if ics_data:
                events.extend(self._parse_vevents(ics_data))
            else:
                failed += 1
        if failed:
            return events, f"{failed}/{len(ics_urls)} 个事件文件未拉到"
        return events, None

    async def _list_calendars_with_status(self) -> tuple[list[dict], str | None]:
        """列出所有日历，带缓存。

        Returns:
            ``(日历列表, 失败原因)``：原因非 None 表示这次列举不可信（发现失败
            或 HTTP 非 207），调用方不得据此判定日历中的事件已被删除。
        """
        now_ts = time.monotonic()
        if (
            self._calendars_cache
            and (now_ts - self._calendars_ts) < self._calendars_cache_ttl_seconds
        ):
            return list(self._calendars_cache), None
        if not await self._discover():
            return [], "CalDAV 未连接"
        resp, status = await self._aiohttp_request_with_status(
            self._caldav_base_url + "/",
            method="PROPFIND",
            data=b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:href/><D:displayname/></D:prop></D:propfind>',
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "text/xml",
                "Depth": "1",
            },
        )
        if status != 207:
            logger.warning(
                f"[AppleCalendar] 列出日历失败: "
                f"status={status if status is not None else '无响应'}, "
                f"body={self._truncate_for_log(resp)}"
            )
            return [], (
                f"列出日历失败（status={status if status is not None else '无响应'}）"
            )
        names = AppleCalendar._extract_calendar_names(resp)
        calendars = []
        seen_uuids = set()  # 去重
        for m in re.findall(r"<(?:D:)?href[^>]*>([^<]+)</(?:D:)?href>", resp):
            href = AppleCalendar._clean_href(m.strip())
            if not href:
                continue
            # 检查是否是 UUID 日历（大小写不敏感）
            uuid_match = re.search(
                r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
                href,
            )
            if uuid_match:
                cal_uuid = uuid_match.group(1)
                if cal_uuid in seen_uuids:
                    continue
                seen_uuids.add(cal_uuid)
                # 构建日历 URL（优先使用绝对 URL）
                if href.startswith("http"):
                    cal_url = href.rstrip("/")
                else:
                    # 相对路径，使用 base_url 拼接
                    cal_url = f"{self._caldav_base_url.rstrip('/')}/{cal_uuid}"
                calendars.append(
                    {
                        "href": href,
                        "url": cal_url,
                        "id": cal_uuid,
                        "name": names.get(href, ""),
                    }
                )
        self._calendars_cache = list(calendars)
        self._calendars_ts = time.monotonic()
        logger.debug(f"[AppleCalendar] 发现 {len(calendars)} 个日历")
        if calendars and not self._calendars_logged:
            self._calendars_logged = True
            logger.info(
                "[AppleCalendar] 可用日历（calendar_id 可填下列 UUID）:\n"
                + "\n".join(
                    f"  {c['name'] or '(未命名)'} → {c['id']}" for c in calendars
                )
            )
        return calendars, None

    async def find_events_by_summary(self, summary: str) -> list[tuple[dict, str]]:
        """按标题精确匹配查找各日历中的事件，返回 (事件, 日历ID) 列表。

        供删除同步等外部调用使用，避免直接依赖内部抓取方法。
        """
        if not summary:
            return []
        if not await self._discover():
            return []
        calendars, _ = await self._list_calendars_with_status()
        matches: list[tuple[dict, str]] = []
        for cal in calendars:
            events, _ = await self._caldav_fetch_with_status(cal["url"])
            for evt in events:
                if evt.get("summary") == summary:
                    matches.append((evt, cal["id"]))
        return matches

    def _parse_vevents(self, ical_data: str) -> list[dict]:
        """解析 VEVENT，正确处理 UTC 和本地时区

        iCloud ICS 格式支持:
        - DTSTART:20260422T073500Z           (UTC时间，带Z后缀)
        - DTSTART;TZID=Asia/Shanghai:...     (本地时间，带TZID)
        - DTSTART;VALUE=DATE:20260202        (全天事件)
        """
        events = []
        local_tz = self._tz or datetime.now().astimezone().tzinfo

        for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ical_data, re.DOTALL):
            summary_m = re.search(r"SUMMARY:([^\r\n]+)", ev)
            uid_m = re.search(r"UID:([^\r\n]+)", ev)
            desc_m = re.search(r"DESCRIPTION:([^\r\n]*)", ev)

            summary = summary_m.group(1).strip() if summary_m else "无标题"
            uid = uid_m.group(1).strip() if uid_m else str(uuid.uuid4())
            description = desc_m.group(1).replace("\\n", "\n").strip() if desc_m else ""

            # 解析 DTSTART
            dtstart_line = re.search(r"DTSTART[^\r\n]*", ev)
            dtstart_all_day = False
            start_time = None

            if dtstart_line:
                line = dtstart_line.group(0)

                # 全天事件检测
                if "VALUE=DATE" in line or re.search(r":\d{8}$", line):
                    dtstart_all_day = True
                    date_match = re.search(r":(\d{8})(?:T\d{6})?$", line)
                    if date_match:
                        start_time = datetime.strptime(date_match.group(1), "%Y%m%d")
                else:
                    # 提取时区信息
                    tzid_match = re.search(r"TZID=([^:]+)", line)
                    # 提取时间值
                    value_match = re.search(r":(\d{8}T\d{6})", line)

                    if value_match:
                        time_str = value_match.group(1)
                        naive = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                        if tzid_match:
                            try:
                                from dateutil import tz as dateutil_tz

                                tz_name = tzid_match.group(1)
                                tz_obj = dateutil_tz.gettz(tz_name)
                                if tz_obj:
                                    aware = naive.replace(tzinfo=tz_obj)
                                    start_time = aware.astimezone(local_tz).replace(
                                        tzinfo=None
                                    )
                                else:
                                    start_time = naive
                            except Exception:
                                start_time = naive
                        elif line.rstrip().endswith("Z"):
                            utc = naive.replace(tzinfo=timezone.utc)
                            start_time = utc.astimezone(local_tz).replace(tzinfo=None)
                        else:
                            start_time = naive

            # 解析 DTEND
            dtend_line = re.search(r"DTEND[^\r\n]*", ev)
            end_time = None

            if dtend_line and not dtstart_all_day:
                line = dtend_line.group(0)
                tzid_match = re.search(r"TZID=([^:]+)", line)
                value_match = re.search(r":(\d{8}T\d{6})", line)
                if value_match:
                    time_str = value_match.group(1)
                    naive = datetime.strptime(time_str, "%Y%m%dT%H%M%S")

                    if tzid_match:
                        try:
                            from dateutil import tz as dateutil_tz

                            tz_name = tzid_match.group(1)
                            tz_obj = dateutil_tz.gettz(tz_name)
                            if tz_obj:
                                aware = naive.replace(tzinfo=tz_obj)
                                end_time = aware.astimezone(local_tz).replace(
                                    tzinfo=None
                                )
                            else:
                                end_time = naive
                        except Exception:
                            end_time = naive
                    elif line.rstrip().endswith("Z"):
                        utc = naive.replace(tzinfo=timezone.utc)
                        end_time = utc.astimezone(local_tz).replace(tzinfo=None)
                    else:
                        end_time = naive

            if start_time:
                events.append(
                    {
                        "uid": uid,
                        "summary": summary,
                        "description": description,
                        "start": start_time.isoformat(),
                        "end": end_time.isoformat() if end_time else None,
                        "all_day": dtstart_all_day,
                    }
                )

        return events

    @staticmethod
    def _is_safe_webcal_url(url) -> bool:
        """校验 WebCal 订阅地址是否安全（仅 http/https + 公网主机）。

        防 SSRF：拒绝 localhost / 内网 / 环回 / 链路本地 / 云元数据等地址。
        主机为 IP 字面量时直接校验；否则按主机名后缀与已知元数据主机做黑名单。
        域名解析（rebinding）风险应在部署侧/README 中另行提示。

        Args:
            url: 待校验的 WebCal 地址（允许 webcal:// 前缀）

        Returns:
            True 表示可安全请求。
        """
        if not url or not isinstance(url, str):
            return False
        http_url = url.replace("webcal://", "https://").strip()
        try:
            parsed = urlparse(http_url)
        except ValueError:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        host_lower = host.lower()

        # 本地/内网主机名黑名单
        if host_lower in ("localhost", "localhost.localdomain", "broadcasthost"):
            return False
        if host_lower.endswith((".local", ".localhost", ".internal", ".home.arpa")):
            return False
        if host_lower in (
            "metadata.google.internal",
            "metadata.azure.internal",
            "instance-data",
            "instance-data.ec2.internal",
            "169.254.169.254.nip.io",
        ):
            return False

        # IP 字面量：直接校验
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return True  # 域名，已过主机名黑名单
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )

    async def fetch_webcal_with_status(self, url: str) -> tuple[list[dict], str | None]:
        """读取 WebCal 订阅源。

        Returns:
            ``(事件列表, 失败原因)``：读取成功（哪怕一个事件都没有）为
            ``(events, None)``；地址被拒或请求异常为 ``([], 原因)``。
        """
        events = []
        try:
            # 防 SSRF：WebCal 地址必须为公网 https/http，拒绝内网/本地/云元数据地址
            if not self._is_safe_webcal_url(url):
                logger.warning(f"[AppleCalendar] 拒绝不安全的 WebCal 地址: {url}")
                return events, "WebCal 地址不安全，已拒绝读取"
            http_url = url.replace("webcal://", "https://")
            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    http_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp,
            ):
                ical_data = await resp.text()
            events = self._parse_vevents(ical_data)
            logger.debug(f"[AppleCalendar] WebCal 读取成功: {len(events)} 个事件")
            return events, None
        except Exception as e:
            logger.warning(f"[AppleCalendar] WebCal 读取失败: {e}")
            return events, "WebCal 读取失败"

    def _now(self) -> datetime:
        return datetime.now(self._tz) if self._tz else datetime.now()

    def _cleanup_expired_cache(self):
        """清理过期的缓存（只保留今天的缓存）"""
        today = self._now().strftime("%Y%m%d")
        # 清理所有不以今天日期开头的缓存键（包括旧格式的整数键）
        expired_keys = [
            k for k in list(self._events_cache.keys()) if not str(k).startswith(today)
        ]
        if expired_keys:
            for k in expired_keys:
                del self._events_cache[k]
            logger.debug(
                f"[AppleCalendar] 清理了 {len(expired_keys)} 个过期缓存键: {expired_keys}"
            )

    async def get_all_events(self, days: int = 1) -> tuple[list[dict], list[str]]:
        """获取所有日历事件（带缓存，去重）。

        Returns:
            ``(事件列表, 问题列表)``：问题列表为空表示这一轮读取完整；非空
            表示有日历或订阅源没读全——此时事件列表里缺席的事件无法与
            "事件已被删除"区分，调用方不得据此判定删除。
        """
        # 缓存键包含日期，避免跨天返回错误数据
        today = self._now().strftime("%Y%m%d")
        cache_key = f"{today}_{int(days if days else 1)}"

        # 清理过期缓存
        self._cleanup_expired_cache()

        now_ts = time.monotonic()
        cached = self._events_cache.get(cache_key)
        if cached and (now_ts - cached.get("ts", 0)) < self._events_cache_ttl_seconds:
            logger.debug(
                f"[AppleCalendar] 使用缓存 key={cache_key}, 事件数={len(cached.get('events', []))}"
            )
            return list(cached.get("events", [])), list(cached.get("issues", []))

        async with self._fetch_lock:
            # 双重检查：加锁后再检查缓存（可能被其他协程填充）
            now_ts = time.monotonic()
            cached = self._events_cache.get(cache_key)
            if (
                cached
                and (now_ts - cached.get("ts", 0)) < self._events_cache_ttl_seconds
            ):
                logger.debug(
                    f"[AppleCalendar] 使用缓存(锁内) key={cache_key}, 事件数={len(cached.get('events', []))}"
                )
                return list(cached.get("events", [])), list(cached.get("issues", []))

            # 缓存不存在或已过期，重新获取
            all_events: dict[str, dict] = {}  # 用 dict 做去重，key 为 uid
            issues: list[str] = []  # 本轮没读全的地方，非空即"读取不完整"

            if self.username and self.app_password:
                calendars, list_issue = await self._list_calendars_with_status()
                if list_issue:
                    issues.append(list_issue)
                logger.debug(f"[AppleCalendar] 准备获取 {len(calendars)} 个日历的事件")
                for cal in calendars:
                    cal_events, fetch_issue = await self._caldav_fetch_with_status(
                        cal["url"]
                    )
                    if fetch_issue:
                        issues.append(f"{cal.get('name') or cal['id']}: {fetch_issue}")
                    for evt in cal_events:
                        uid = evt.get("uid")
                        if uid:
                            all_events[uid] = evt  # 去重
                    logger.debug(
                        f"[AppleCalendar] 日历 {cal.get('id', '?')} 获取到 {len(cal_events)} 个事件"
                    )

            for url in self.webcal_urls:
                webcal_events, webcal_issue = await self.fetch_webcal_with_status(url)
                if webcal_issue:
                    issues.append(webcal_issue)
                for evt in webcal_events:
                    uid = evt.get("uid")
                    if uid:
                        all_events[uid] = evt
                logger.debug(
                    f"[AppleCalendar] WebCal {url} 获取到 {len(webcal_events)} 个事件"
                )

            events_list = list(all_events.values())
            self._events_cache[cache_key] = {
                "ts": time.monotonic(),
                "events": events_list,
                "issues": list(issues),
            }
            logger.debug(
                f"[AppleCalendar] get_all_events(days={days}, cache_key={cache_key}) 返回 {len(events_list)} 个事件（去重后）"
            )
            return events_list, issues

    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime | None = None,
        calendar_id: str | None = None,
        description: str = "",
        all_day: bool = False,
        uid: str | None = None,
    ) -> str | None:
        """创建事件；``uid`` 给定时按 CalDAV 语义更新同一 UID 的事件（同 URL PUT）。

        ``uid`` 语义两种取值：
        - ``None``（缺省）：每次生成新 UID，即新建事件；
        - 非空字符串：更新该 UID 的事件（同 URL PUT 覆盖）。
        其余取值（空串/纯空白/非字符串的假值）非法——它们既不是"新建"也不是
        可用的 URL 段，却会被 ``uid or str(uuid.uuid4())`` 静默当成新建，
        让调用方以为在更新（例如误传空的 ``apple_uid`` 会写出第二条事件）。
        故直接拒绝并告警：这是 API 卫生约束，避免"更新"被静默降级成"新建"。

        Returns:
            成功（2xx，CalDAV PUT 成功为 201）返回 UID；失败或 uid 非法返回 None。
        """
        # 判据与下面的赋值保持同一口径（`uid or …`）：只要不是 None 就必须有非空内容
        if uid is not None and not (isinstance(uid, str) and uid.strip()):
            logger.warning(
                f"[AppleCalendar] create_event 收到非法 uid，拒绝执行（非 None 的空值"
                f"既非新建也非有效更新）: summary={summary} uid={uid!r}"
            )
            return None
        if not await self._discover():
            # 失败原因已由 _discover 以 ERROR 报出，这里只记录本次动作被跳过
            logger.warning("[AppleCalendar] CalDAV 未连接，无法创建事件")
            return None
        calendars, _ = await self._list_calendars_with_status()
        if not calendars:
            logger.warning("[AppleCalendar] 未找到可写日历")
            return None

        # 优先级：传入参数 > 配置的 calendar_id > 第一个日历
        resolved_id = calendar_id or self._calendar_id or calendars[0]["id"]
        if resolved_id == calendars[0]["id"] and not (calendar_id or self._calendar_id):
            logger.debug(
                f"[AppleCalendar] 未找到指定日历，使用第一个: {resolved_id[:8]}..."
            )
        cal_url = f"{self._caldav_base_url}/{resolved_id}/"
        uid = uid or str(uuid.uuid4())
        tz = self._tz
        tzid = getattr(tz, "key", None) or "UTC"
        if start.tzinfo is None and tz is not None:
            start = start.replace(tzinfo=tz)
        if end is not None and end.tzinfo is None and tz is not None:
            end = end.replace(tzinfo=tz)
        wall_start = start.astimezone(tz) if (tz and start.tzinfo) else start
        wall_end = (
            end.astimezone(tz)
            if (tz and end is not None and end.tzinfo)
            else (end or (start + timedelta(hours=1)))
        )
        created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if all_day:
            # 全天事件：VALUE=DATE，DTEND 为独占次日（RFC 5545）
            dtstart_line = f"DTSTART;VALUE=DATE:{wall_start.strftime('%Y%m%d')}"
            dtend_line = (
                f"DTEND;VALUE=DATE:"
                f"{(end or (start + timedelta(days=1))).strftime('%Y%m%d')}"
            )
        else:
            dtstart_fmt = wall_start.strftime("%Y%m%dT%H%M%S")
            dtend_fmt = wall_end.strftime("%Y%m%dT%H%M%S")
            dtstart_line = f"DTSTART;TZID={tzid}:{dtstart_fmt}"
            dtend_line = f"DTEND;TZID={tzid}:{dtend_fmt}"
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{created}",
            dtstart_line,
            dtend_line,
            f"SUMMARY:{_escape_ics_text(summary)}",
        ]
        esc_desc = _escape_ics_text(description)
        if esc_desc:
            lines.append(f"DESCRIPTION:{esc_desc}")
        lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        vevent = ("\r\n".join(lines) + "\r\n").encode()
        event_url = f"{cal_url}{uid}.ics"
        resp, status = await self._aiohttp_request_with_status(
            event_url,
            method="PUT",
            data=vevent,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "text/calendar",
            },
        )
        # CalDAV 写操作必须看状态码：4xx（鉴权失败/路径不存在）与重试耗尽的 5xx
        # 同样会带回响应体，只判断"有没有响应"会把失败当成成功，
        # 进而把不存在的 UID 写进本地库（下轮同步按 UID 差集静默删除该日程）。
        if status is not None and 200 <= status < 300:
            logger.info(
                f"[AppleCalendar] 创建事件成功: {summary} (UID={uid}, status={status})"
            )
            return uid
        logger.warning(
            f"[AppleCalendar] 创建事件失败: {summary} (UID={uid}, "
            f"status={status if status is not None else '无响应'}, "
            f"body={self._truncate_for_log(resp)})"
        )
        return None

    async def delete_event(self, uid: str, calendar_id: str | None = None) -> bool:
        """删除事件，仅在 2xx（CalDAV DELETE 成功为 204）时返回 True。"""
        if not await self._discover():
            return False
        calendars, _ = await self._list_calendars_with_status()
        if not calendars:
            return False
        resolved_id = calendar_id or self._calendar_id or calendars[0]["id"]
        cal_url = f"{self._caldav_base_url}/{resolved_id}/"
        event_url = f"{cal_url}{uid}.ics"
        resp, status = await self._aiohttp_request_with_status(
            event_url, method="DELETE", headers={"Authorization": self._auth_header()}
        )
        # DELETE 成功响应体为空串，与 4xx 的响应体都可能为 ""，必须按状态码判定
        if status is not None and 200 <= status < 300:
            logger.info(f"[AppleCalendar] 删除事件成功: UID={uid} (status={status})")
            return True
        logger.warning(
            f"[AppleCalendar] 删除事件失败: UID={uid}, "
            f"status={status if status is not None else '无响应'}, "
            f"body={self._truncate_for_log(resp)}"
        )
        return False

    async def close(self):
        pass
