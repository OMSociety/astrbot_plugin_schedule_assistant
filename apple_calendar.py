"""Apple iCloud CalDAV 日历同步模块"""
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

    async def _discover(self) -> bool:
        if self._discovered or not self.username or not self.app_password:
            return bool(self._discovered)

        body1 = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:current-user-principal/></D:prop></D:propfind>'
        resp1 = self._request(
            "https://caldav.icloud.com/",
            method="PROPFIND",
            data=body1,
            headers={"Authorization": self._auth_header(), "Content-Type": "text/xml"},
        )
        if not resp1:
            logger.debug("[AppleCalendar] CalDAV 发现失败，未配置 Apple 日历")
            return False

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

        body2 = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><C:calendar-home-set/></D:prop></D:propfind>'
        resp2 = self._request(
            self._principal_url,
            method="PROPFIND",
            data=body2,
            headers={"Authorization": self._auth_header(), "Content-Type": "text/xml"},
        )
        if not resp2:
            logger.debug("[AppleCalendar] principal URL 无响应，跳过日历发现")
            return False

        m2 = re.search(r"calendar-home-set[^>]*>(.*?)(?:</calendar-home-set>|/>)", resp2, re.DOTALL)
        cal_home_block = m2.group(1) if m2 else ""
        m3 = re.search(r"href[^>]*>([^<]+)<", cal_home_block)
        cal_home_href = m3.group(1).strip() if m3 else None

        if not cal_home_href:
            logger.error("[AppleCalendar] 无法解析 calendar home set URL")
            return False

        if cal_home_href.startswith("/"):
            self._caldav_base_url = f"https://caldav.icloud.com{cal_home_href}".rstrip("/")
        else:
            self._caldav_base_url = cal_home_href.rstrip("/")

        self._caldav_base_domain = "/".join(self._caldav_base_url.split("/")[:3])
        self._discovered = True
        logger.info("[AppleCalendar] CalDAV 发现完成")
        return True

    async def list_calendars(self) -> List[Dict]:
        if not await self._discover():
            return []

        body = b'<?xml version="1.0" encoding="UTF-8"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:allprop/></D:propfind>'
        resp = self._request(
            self._caldav_base_url,
            method="PROPFIND",
            data=body,
            headers={"Authorization": self._auth_header(), "Content-Type": "text/xml"},
        )
        if not resp:
            return []

        calendars = []
        for m in re.finditer(r"<D:response>(.*?)</D:response>", resp, re.DOTALL):
            block = m.group(1)
            href_m = re.search(r"<D:href[^>]*>([^<]+)<", block)
            if not href_m:
                continue
            href = href_m.group(1).strip()
            cal_url = f"{self._caldav_base_domain}{href}"

            displayname_m = re.search(r"<D:displayname[^>]*>([^<]+)<", block)
            displayname = displayname_m.group(1).strip() if displayname_m else href

            ctag_m = re.search(r"<C:getctag[^>]*>([^<]+)<", block)
            ctag = ctag_m.group(1).strip() if ctag_m else None

            calendars.append({
                "id": href,
                "url": cal_url,
                "name": displayname,
                "ctag": ctag,
            })

        return calendars

    async def list_events(self, calendar_id: Optional[str] = None, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[Dict]:
        if not await self._discover():
            return []

        calendars = await self.list_calendars()
        if not calendars:
            return []

        if calendar_id:
            calendars = [c for c in calendars if calendar_id in c["url"]]

        if not calendars:
            return []

        now = datetime.now(timezone.utc)
        start = start or (now - timedelta(days=7))
        end = end or (now + timedelta(days=30))

        events = []
        for cal in calendars:
            cal_events = await self._fetch_calendar_events(cal["url"], start, end)
            events.extend(cal_events)

        return events

    def _fetch_calendar_events(self, cal_url: str, start: datetime, end: datetime) -> List[Dict]:
        body = f'''<?xml version="1.0" encoding="UTF-8"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:href/><C:calendar-data/></D:prop><C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT"><C:time-range start="{start.strftime('%Y%m%dT%H%M%SZ')}" end="{end.strftime('%Y%m%dT%H%M%SZ')}"/></C:comp-filter></C:comp-filter></C:filter></C:calendar-query>'''.encode()

        resp = self._request(
            cal_url,
            method="POST",
            data=body,
            headers={"Authorization": self._auth_header(), "Content-Type": "text/xml"},
        )

        if not resp:
            return []

        events = []
        for vevent_m in re.finditer(r"BEGIN:VEVENT(.*?)END:VEVENT", resp, re.DOTALL):
            vevent = vevent_m.group(1)
            uid_m = re.search(r"^UID:(.+)$", vevent, re.MULTILINE)
            summary_m = re.search(r"^SUMMARY:(.+)$", vevent, re.MULTILINE)
            dtstart_m = re.search(r"^DTSTART(?:;[^:]*)?:(.+)$", vevent, re.MULTILINE)
            dtend_m = re.search(r"^DTEND(?:;[^:]*)?:(.+)$", vevent, re.MULTILINE)
            desc_m = re.search(r"^DESCRIPTION:(.*?)(?=^[^ \t]|^$)", vevent, re.MULTILINE | re.DOTALL)

            uid = uid_m.group(1).strip() if uid_m else None
            summary = summary_m.group(1).strip() if summary_m else ""
            start_str = dtstart_m.group(1).strip() if dtstart_m else ""
            end_str = dtend_m.group(1).strip() if dtend_m else ""
            description = desc_m.group(1).strip() if desc_m else ""

            events.append({
                "uid": uid,
                "summary": summary,
                "start": start_str,
                "end": end_str,
                "description": description,
            })

        return events

    async def create_event(self, calendar_id: str, summary: str, start: datetime, end: datetime, description: str = "") -> Optional[str]:
        if not await self._discover():
            return None

        uid = str(uuid.uuid4())
        dt_format = "%Y%m%dT%H%M%SZ"
        vevent = f"""BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//ScheduleAssistant//iCloud//EN\nBEGIN:VEVENT\nUID:{uid}\nDTSTART:{start.strftime(dt_format)}\nDTEND:{end.strftime(dt_format)}\nSUMMARY:{summary}\nDESCRIPTION:{description}\nEND:VEVENT\nEND:VCALENDAR\n"""

        resp = self._request(
            calendar_id,
            method="PUT",
            data=vevent.encode(),
            headers={"Authorization": self._auth_header(), "Content-Type": "text/calendar; charset=utf-8"},
        )

        if resp is not None:
            return uid
        return None

    async def delete_event(self, calendar_id: str, uid: str) -> bool:
        event_url = f"{calendar_id.rstrip('/')}/{uid}.ics"
        resp = self._request(
            event_url,
            method="DELETE",
            headers={"Authorization": self._auth_header()},
        )
        return resp is not None
