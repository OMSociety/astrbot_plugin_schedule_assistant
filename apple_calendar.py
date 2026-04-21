"""
Apple iCloud CalDAV 日历同步模块
支持：日历发现 / PROPFIND读取事件 / 创建&删除事件 / 时区正确处理
"""
import urllib.request
import urllib.error
import base64
import re
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from astrbot import logger

__all__ = ["AppleCalendar"]


class AppleCalendar:
    """Apple iCloud / CalDAV 日历客户端"""

    def __init__(
        self,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        webcal_urls: Optional[List[str]] = None,
    ):
        self.username = username
        self.app_password = app_password
        self.webcal_urls = webcal_urls or []
        self._principal_url: Optional[str] = None
        self._caldav_base_url: Optional[str] = None
        self._caldav_base_domain: Optional[str] = None
        self._calendars: Optional[List[Dict]] = None
        self._discovered = False

    # ── 认证 ───────────────────────────────────────────────────────────────

    def _auth_header(self) -> str:
        creds = f"{self.username}:{self.app_password}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    def _request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[bytes] = None,
        headers: Optional[Dict] = None,
        timeout: int = 15,
    ) -> Optional[str]:
        headers = dict(headers or {})
        headers.setdefault("User-Agent", "curl/7.88.1")
        req = urllib.request.Request(url, headers=headers, data=data, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            logger.warning(f"[AppleCalendar] HTTP {e.code}: {body[:300]}")
            return None
        except Exception as e:
            logger.debug(f"[AppleCalendar] 请求异常 {url}: {e}")
            return None

    # ── CalDAV 发现 ───────────────────────────────────────────────────────

    async def _discover(self) -> bool:
        """发现 principal URL 和 calendar home set URL"""
        if self._discovered or not self.username or not self.app_password:
            return bool(self._discovered)

        # Step 1: 获取 principal URL
        body1 = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:current-user-principal/></D:prop></D:propfind>'
        resp1 = self._request(
            "https://caldav.icloud.com/",
            method="PROPFIND",
            data=body1,
            headers={"Authorization": self._auth_header(), "Content-Type": "text/xml"},
        )
        if not resp1:
            logger.error("[AppleCalendar] CalDAV 发现失败，无法连接 iCloud")
            return False

        # 兼容有无命名空间前缀
        m = re.search(r"<current-user-principal[^>]*>(.*?)</[^>]+>", resp1, re.DOTALL)
        if not m:
            m = re.search(r"href>([^<]+)<", resp1)
        principal_href = m.group(1).strip() if m else None

        if not principal_href:
            logger.error("[AppleCalendar] 无法解析 principal URL")
            return False

        if principal_href.startswith("https://"):
            self._principal_url = principal_href.rstrip("/")
        else:
            self._principal_url = f"https://caldav.icloud.com{principal_href}".rstrip("/")

        # Step 2: 获取 calendar home set
        body2 = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><C:calendar-home-set/></D:prop></D:propfind>'
        resp2 = self._request(
            self._principal_url,
            method="PROPFIND",
            data=body2,
            headers={"Authorization": self._auth_header(), "Content-Type": "text/xml"},
        )
        if not resp2:
            logger.error("[AppleCalendar] principal URL 无响应")
            return False

        m2 = re.search(r"calendar-home-set[^>]*>(.*?)(?:</calendar-home-set>|/>)", resp2, re.DOTALL)
        cal_home_block = m2.group(1) if m2 else ""
        m3 = re.search(r"href[^>]*>([^<]+)<", cal_home_block)
        cal_home_href = m3.group(1).strip() if m3 else None

        if not cal_home_href:
            logger.error("[AppleCalendar] 无法解析 calendar home set URL")
            return False

        if cal_home_href.startswith("https://"):
            self._caldav_base_url = cal_home_href.rstrip("/")
            self._caldav_base_domain = cal_home_href.split("/")[2]
        else:
            self._caldav_base_domain = "p218-caldav.icloud.com.cn:443"
            self._caldav_base_url = f"https://{self._caldav_base_domain}{cal_home_href}".rstrip("/")

        self._discovered = True
        logger.info(f"[AppleCalendar] CalDAV 发现成功: base={self._caldav_base_url}")
        return True

    # ── 日历列表 ─────────────────────────────────────────────────────────

    def _propfind(self, url: str, depth: str = "1") -> Optional[str]:
        body = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:href/></D:prop></D:propfind>'
        return self._request(
            url,
            method="PROPFIND",
            data=body,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "text/xml",
                "Depth": depth,
            },
        )

    async def _list_calendars(self) -> List[Dict]:
        """列出所有日历"""
        if not await self._discover():
            return []

        resp = self._propfind(self._caldav_base_url + "/")
        if not resp:
            return []

        calendars = []
        for pattern in [
            r"<D:href[^>]*>([^<]+)</D:href>",
            r"<href[^>]*>([^<]+)</href>",
            r"<(?:D:)?href[^>]*>([^<]+)</(?:D:)?href>",
        ]:
            for m in re.findall(pattern, resp):
                href = m.strip()
                if not href:
                    continue
                if re.search(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/$", href):
                    path_parts = [p for p in href.strip("/").split("/") if p]
                    last = path_parts[-1] if path_parts else ""
                    if re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", last):
                        cal_id = last
                        cal_url = f"{self._caldav_base_url}/{cal_id}"
                        calendars.append({"href": href, "url": cal_url, "id": cal_id, "name": ""})

        self._calendars = calendars
        logger.info(f"[AppleCalendar] 发现 {len(calendars)} 个日历")
        return calendars

    # ── 读取事件（PROPFIND + GET .ics）────────────────────────────────

    def _fetch_ics_sync(self, ics_url: str) -> Optional[str]:
        """并发获取单个 .ics 文件"""
        return self._request(
            ics_url,
            headers={"Authorization": self._auth_header()},
            timeout=10,
        )

    def _caldav_fetch_sync(self, cal_url: str) -> List[Dict]:
        """iCloud 不支持 calendar-query REPORT，用 PROPFIND + 并发 GET .ics"""
        resp = self._propfind(cal_url.rstrip("/") + "/")
        if not resp:
            return []

        ics_urls = []
        for pattern in [
            r"<D:href[^>]*>([^<]+)</D:href>",
            r"<href[^>]*>([^<]+)</href>",
            r"<(?:D:)?href[^>]*>([^<]+)</(?:D:)?href>",
        ]:
            for m in re.findall(pattern, resp):
                href = m.strip()
                if href.endswith(".ics"):
                    if href.startswith("/"):
                        ics_url = f"https://{self._caldav_base_domain}{href}"
                    elif href.startswith("https://"):
                        ics_url = href
                    else:
                        ics_url = f"{cal_url.rstrip('/')}/{href}"
                    ics_urls.append(ics_url)

        if not ics_urls:
            return []

        logger.info(f"[AppleCalendar] 发现 {len(ics_urls)} 个事件文件")
        events = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(self._fetch_ics_sync, url): url for url in ics_urls}
            for future in as_completed(futures):
                ics_data = future.result()
                if ics_data:
                    evts = self._parse_vevents(ics_data)
                    events.extend(evts)

        return events

    async def _caldav_fetch(self, cal_url: str, days: int = 30) -> List[Dict]:
        """异步封装，在线程池执行同步 IO"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._caldav_fetch_sync, cal_url)

    # ── VEVENT 解析 ───────────────────────────────────────────────────────

    def _parse_vevents(self, ical_data: str) -> List[Dict]:
        """解析 VEVENT，有 TZID 标记的 DTSTART 不做 UTC 转换"""
        events = []
        local_tz = datetime.now().astimezone().tzinfo

        for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ical_data, re.DOTALL):
            summary_m = re.search(r"SUMMARY:([^\r\n]+)", ev)
            dtstart_m = re.search(r"DTSTART(?:;[^:]*)?:([\dT]+)", ev)
            dtend_m = re.search(r"DTEND(?:;[^:]*)?:([\dT]+)", ev)
            uid_m = re.search(r"UID:([^\r\n]+)", ev)
            desc_m = re.search(r"DESCRIPTION:([^\r\n]*)", ev)

            summary = summary_m.group(1).strip() if summary_m else "无标题"
            uid = uid_m.group(1).strip() if uid_m else str(uuid.uuid4())
            description = desc_m.group(1).replace(r"\n", "\n").strip() if desc_m else ""

            dtstart_raw = dtstart_m.group(0) if dtstart_m else ""
            has_tzid = bool(re.search(r"TZID=", dtstart_raw))
            dtstart_str = dtstart_m.group(1) if dtstart_m else ""
            dtstart_all_day = bool(
                re.search(r"VALUE=DATE", dtstart_raw) or (dtstart_str and len(dtstart_str) == 8)
            )

            def parse_dt(ds: str, is_all_day: bool = False, has_tz: bool = False) -> Optional[datetime]:
                if not ds:
                    return None
                ds = ds.strip()
                try:
                    if len(ds) == 8:
                        return datetime.strptime(ds, "%Y%m%d")
                    elif len(ds) >= 15:
                        naive = datetime.strptime(ds[:15], "%Y%m%dT%H%M%S")
                        if has_tz:
                            return naive
                        utc = naive.replace(tzinfo=timezone.utc)
                        return utc.astimezone(local_tz).replace(tzinfo=None)
                except ValueError:
                    try:
                        return datetime.strptime(ds[:8], "%Y%m%d")
                    except ValueError:
                        pass
                return None

            start_time = parse_dt(dtstart_str, dtstart_all_day, has_tzid)
            end_time = None
            if dtend_m:
                dtend_str = dtend_m.group(1)
                has_tzid_end = bool(re.search(r"TZID=", dtend_m.group(0)))
                end_time = parse_dt(dtend_str, False, has_tzid_end)

            if start_time:
                events.append({
                    "uid": uid,
                    "summary": summary,
                    "description": description,
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat() if end_time else None,
                    "all_day": dtstart_all_day,
                })

        return events

    # ── WebCal ────────────────────────────────────────────────────────────

    async def fetch_webcal_async(self, url: str, days: int = 30) -> List[Dict]:
        events = []
        try:
            http_url = url.replace("webcal://", "https://")
            import aiohttp
            timeout_ = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    http_url,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "text/calendar,*/*"},
                    timeout=timeout_,
                ) as resp:
                    ical_data = await resp.text()
            events = self._parse_vevents(ical_data)
            logger.info(f"[AppleCalendar] WebCal 读取成功: {len(events)} 个事件")
        except Exception as e:
            logger.error(f"[AppleCalendar] WebCal 读取失败: {e}")
        return events

    # ── 统一获取 ─────────────────────────────────────────────────────────

    async def get_all_events(self, days: int = 1) -> List[Dict]:
        all_events = []
        if self.username and self.app_password:
            calendars = await self._list_calendars()
            for cal in calendars:
                cal_events = await self._caldav_fetch(cal["url"], days)
                all_events.extend(cal_events)
        for url in self.webcal_urls:
            all_events.extend(await self.fetch_webcal_async(url, days))
        return all_events

    # ── 可写操作 ─────────────────────────────────────────────────────────

    async def _resolve_calendar_id(self, calendar_id: Optional[str] = None) -> Optional[str]:
        """解析日历 ID，返回日历 UUID"""
        calendars = await self._list_calendars()
        if not calendars:
            logger.error("[AppleCalendar] 未找到可写日历")
            return None
        if not calendar_id:
            return calendars[0]["id"]
        for c in calendars:
            if c["id"] == calendar_id or c["name"] == calendar_id:
                return c["id"]
        for c in calendars:
            if calendar_id.lower() in c["name"].lower():
                return c["id"]
        logger.warning(f"[AppleCalendar] 日历「{calendar_id}」未找到，使用第一个日历")
        return calendars[0]["id"]

    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: Optional[datetime] = None,
        calendar_id: Optional[str] = None,
        description: str = "",
    ) -> Optional[str]:
        """创建日历事件，写入时带上 ;TZID=Asia/Shanghai"""
        if not await self._discover():
            logger.error("[AppleCalendar] CalDAV 未连接，无法创建事件")
            return None

        resolved_id = await self._resolve_calendar_id(calendar_id)
        if not resolved_id:
            return None

        cal_url = f"{self._caldav_base_url}/{resolved_id}/"
        uid = str(uuid.uuid4())

        dtstart_fmt = start.strftime("%Y%m%dT%H%M%S")
        dtend_fmt = (end or (start + timedelta(hours=1))).strftime("%Y%m%dT%H%M%S")
        created = datetime.now().strftime("%Y%m%dT%H%M%S")

        vevent = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Schedule Assistant//AstrBot//
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{created}
DTSTART;TZID=Asia/Shanghai:{dtstart_fmt}
DTEND;TZID=Asia/Shanghai:{dtend_fmt}
SUMMARY:{summary}
DESCRIPTION:{description}
END:VEVENT
END:VCALENDAR
""".encode()

        event_url = f"{cal_url}{uid}.ics"
        resp = self._request(
            event_url,
            method="PUT",
            data=vevent,
            headers={
                "Authorization": self._auth_header(),
                "User-Agent": "curl/7.88.1",
                "Content-Type": "text/calendar; charset=utf-8",
                "If-None-Match": "*",
            },
            timeout=15,
        )

        if resp is not None:
            logger.info(f"[AppleCalendar] 创建事件成功: {summary} (UID={uid})")
            return uid
        else:
            logger.error(f"[AppleCalendar] 创建事件失败（请检查网络）")
            return None

    async def delete_event(self, uid: str, calendar_id: Optional[str] = None) -> bool:
        """删除指定 UID 的事件"""
        if not await self._discover():
            return False
        resolved_id = await self._resolve_calendar_id(calendar_id)
        if not resolved_id:
            return False
        cal_url = f"{self._caldav_base_url}/{resolved_id}/"
        event_url = f"{cal_url}{uid}.ics"
        resp = self._request(
            event_url,
            method="DELETE",
            headers={"Authorization": self._auth_header(), "User-Agent": "curl/7.88.1"},
            timeout=15,
        )
        if resp is not None:
            logger.info(f"[AppleCalendar] 删除事件成功: UID={uid}")
            return True
        return False

    async def close(self):
        """清理资源"""
        pass

    async def get_late_night_events(self) -> List[Dict]:
        """获取今晚 0 点到次日 6 点的深夜事件"""
        events = await self.get_all_events(days=1)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        late_night_end = today + timedelta(hours=6)
        late_night = []
        for e in events:
            start_str = e.get("start", "")
            if not start_str:
                continue
            try:
                start = datetime.fromisoformat(start_str)
                if start.hour == 0 and start.minute == 0 and start.second == 0:
                    continue
                if today <= start < late_night_end:
                    late_night.append(e)
            except ValueError:
                continue
        return late_night
