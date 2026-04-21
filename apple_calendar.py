"""
Apple iCloud Calendar (CalDAV) 适配器

支持两种认证方式：
1. WebCal 公共订阅（只读，无需认证）
2. iCloud CalDAV（读写，需要 Apple ID + App Password）

双向同步使用 iCloud CalDAV API，参考：
https://developer.apple.com/documentation/cloudkit sign-in with apple id
"""

import uuid
import re
import base64
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from astrbot import logger

__all__ = ['AppleCalendar']


class AppleCalendar:
    """Apple 日历客户端（支持 WebCal 只读 + iCloud CalDAV 读写）"""

    def __init__(
        self,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        webcal_urls: Optional[List[str]] = None
    ):
        self.webcal_urls = webcal_urls or []
        self.username = username
        self.app_password = app_password

        # CalDAV 发现信息（按需获取）
        self._principal_url: Optional[str] = None
        self._caldav_base_url: Optional[str] = None
        self._caldav_base_domain: Optional[str] = None
        self._calendars: Optional[List[Dict]] = None
        self._discovered = False

    async def _discover(self) -> bool:
        """CalDAV 服务发现：获取 principal URL 和 calendar home set"""
        if self._discovered or not self.username or not self.app_password:
            return bool(self._discovered)

        auth = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
            "Content-Type": "text/xml; charset=utf-8",
        }

        propfind_body = b"""<?xml version="1.0" encoding="UTF-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:current-user-principal/>
    <C:calendar-home-set xmlns:C="urn:ietf:params:xml:ns:caldav"/>
  </D:prop>
</D:propfind>"""

        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: Get principal URL
                resp = await session.request(
                    "PROPFIND", "https://caldav.icloud.com/",
                    headers={**headers, "Depth": "0"},
                    data=propfind_body,
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                text = await resp.text()

                if resp.status != 207:
                    logger.error(f"[AppleCalendar] CalDAV 发现失败 HTTP {resp.status}")
                    return False

                # 解析 principal URL
                m = re.search(r'<current-user-principal xmlns="DAV:"><href xmlns="DAV:">([^<]+)</href>', text)
                if not m:
                    m = re.search(r'<D:current-user-principal>.*?<D:href>([^<]+)</D:href>', text, re.DOTALL)
                principal_href = m.group(1).strip() if m else None
                if not principal_href:
                    logger.error("[AppleCalendar] 无法解析 principal URL")
                    return False

                if principal_href.startswith("/"):
                    self._principal_url = f"https://caldav.icloud.com{principal_href}"
                else:
                    self._principal_url = principal_href

                # Step 2: Get calendar home set from principal
                resp2 = await session.request(
                    "PROPFIND", self._principal_url,
                    headers={**headers, "Depth": "0"},
                    data=propfind_body,
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                text2 = await resp2.text()

                m2 = re.search(r'<C:calendar-home-set[^>]*>.*?<D:href[^>]*>([^<]+)</D:href>', text2, re.DOTALL)
                if not m2:
                    m2 = re.search(r'calendar-home-set[^>]*>[^<]*<[^>]*href[^>]*>([^<]+)<', text2, re.DOTALL)

                cal_home_href = m2.group(1).strip() if m2 else None
                if not cal_home_href:
                    logger.error("[AppleCalendar] 无法解析 calendar home set URL")
                    return False

                # 解析域名（icloud.com.cn 或 caldav.icloud.com）
                if cal_home_href.startswith("https://"):
                    self._caldav_base_url = cal_home_href.rstrip("/")
                    self._caldav_base_domain = cal_home_href.split("/")[2]
                else:
                    # relative path
                    self._caldav_base_domain = "caldav.icloud.com"
                    self._caldav_base_url = f"https://{self._caldav_base_domain}{cal_home_href.rstrip('/')}"

                self._discovered = True
                logger.info(f"[AppleCalendar] CalDAV 发现成功: principal={self._principal_url}, base={self._caldav_base_url}")
                return True

        except Exception as e:
            logger.error(f"[AppleCalendar] CalDAV 发现异常: {e}")
            return False

    async def _list_calendars(self) -> List[Dict]:
        """获取用户日历列表（ID + 显示名）"""
        if not await self._discover():
            return []

        auth = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
            "Content-Type": "text/xml; charset=utf-8",
        }

        propfind_body = b"""<?xml version="1.0" encoding="UTF-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:href/>
    <D:displayname/>
    <D:resourcetype/>
  </D:prop>
</D:propfind>"""

        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.request(
                    "PROPFIND", self._caldav_base_url + "/",
                    headers={**headers, "Depth": "1"},
                    data=propfind_body,
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                text = await resp.text()

                calendars = []
                # 提取所有日历路径
                # namespace prefix causes <D:href> pattern; use looser regex and strip
                raw_hrefs = re.findall(r'href>([^<]+)<', text)
                for raw in raw_hrefs:
                    href = raw.strip()
                    if not href or href == "/17170844336/calendars/":
                        continue
                    # 判断是否为日历（包含 UUID 格式路径，不是系统文件夹）
                    if any(frag in href for frag in ["/inbox/", "/outbox/", "/notification/"]):
                        continue
                    # UUID 格式的路径才是日历
                    path_parts = [p for p in href.strip("/").split("/") if p]
                    if len(path_parts) >= 2 and re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}', path_parts[-1]):
                        # href like /17170844336/calendars/UUID/ → strip the user-prefix part
                        # base = https://p218-caldav.icloud.com.cn/17170844336/calendars
                        # href = /17170844336/calendars/UUID/ → just use UUID
                        cal_id = path_parts[-1]
                        cal_url = self._caldav_base_url + "/" + cal_id
                        calendars.append({
                            "href": href,
                            "url": cal_url,
                            "id": cal_id,
                            "name": "",
                        })

                # 对每个日历单独查询 displayname
                for cal in calendars:
                    resp2 = await session.request(
                        "PROPFIND", cal["url"],
                        headers={**headers, "Depth": "0"},
                        data=propfind_body,
                        timeout=aiohttp.ClientTimeout(total=10)
                    )
                    if resp2.status == 207:
                        text2 = await resp2.text()
                        m = re.search(r'<D:displayname>([^<]*)</D:displayname>', text2)
                        cal["name"] = m.group(1).strip() if m else ""

                self._calendars = calendars
                logger.info(f"[AppleCalendar] 发现 {len(calendars)} 个日历")
                for c in calendars:
                    logger.info(f"  - {c['name'] or '(无名称)'} ({c['id']}) -> {c['url']}")
                return calendars

        except Exception as e:
            logger.error(f"[AppleCalendar] 获取日历列表失败: {e}")
            return []

    async def _caldav_fetch(self, cal_url: str, days: int = 30) -> List[Dict]:
        """通过 CalDAV 获取指定日历的事件"""
        auth = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
            "Content-Type": "text/xml; charset=utf-8",
        }

        # 计算日期范围
        now = datetime.now()
        range_start = now - timedelta(days=1)
        range_end = now + timedelta(days=days)

        calquery_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:href/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:time-range start="{range_start.strftime('%Y%m%dT%H%M%S')}" end="{range_end.strftime('%Y%m%dT%H%M%S')}"/>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>""".encode()

        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.request(
                    "REPORT", cal_url,
                    headers={**headers, "Depth": "1"},
                    data=calquery_body,
                    timeout=aiohttp.ClientTimeout(total=30)
                )
                text = await resp.text()

                events = self._parse_vevents(text)
                logger.info(f"[AppleCalendar] CalDAV 读取成功: {len(events)} 个事件 ({cal_url})")
                return events

        except Exception as e:
            logger.error(f"[AppleCalendar] CalDAV 读取失败 ({cal_url}): {e}")
            return []

    def _parse_vevents(self, ical_data: str) -> List[Dict]:
        """解析 VEVENT 为事件字典"""
        events = []
        local_tz = datetime.now().astimezone().tzinfo

        vevents = re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', ical_data, re.DOTALL)
        for ev in vevents:
            summary_match = re.search(r'SUMMARY:([^\r\n]+)', ev)
            dtstart_match = re.search(r'DTSTART(?:;[^=]+)?:?([\dT]+)', ev)
            dtend_match = re.search(r'DTEND(?:;[^=]+)?:?([\dT]+)', ev)
            uid_match = re.search(r'UID:([^\r\n]+)', ev)

            summary = summary_match.group(1).strip() if summary_match else "无标题"
            uid = uid_match.group(1).strip() if uid_match else str(uuid.uuid4())

            def parse_dt(ds: str) -> Optional[datetime]:
                if not ds:
                    return None
                ds = ds.strip()
                try:
                    if len(ds) == 8:
                        return datetime.strptime(ds, "%Y%m%d")
                    elif len(ds) >= 15:
                        utc_time = datetime.strptime(ds[:15], "%Y%m%dT%H%M%S")
                        utc_time = utc_time.replace(tzinfo=timezone.utc)
                        return utc_time.astimezone(local_tz).replace(tzinfo=None)
                except ValueError:
                    try:
                        return datetime.strptime(ds[:8], "%Y%m%d")
                    except ValueError:
                        pass
                return None

            start_time = parse_dt(dtstart_match.group(1) if dtstart_match else "")
            end_time = parse_dt(dtend_match.group(1) if dtend_match else "")

            if start_time:
                events.append({
                    "uid": uid,
                    "summary": summary,
                    "description": "",
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat() if end_time else None,
                    "all_day": len(dtstart_match.group(1)) == 8 if dtstart_match else False,
                })

        return events

    async def fetch_webcal_async(self, url: str, days: int = 30) -> List[Dict]:
        """异步读取 WebCal 公共日历（只读，无需认证）"""
        events = []
        try:
            http_url = url.replace("webcal://", "https://")
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    http_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
                        'Accept': 'text/calendar,text/x-vcalendar,*/*'
                    },
                    timeout=timeout
                ) as resp:
                    ical_data = await resp.text()

            events = self._parse_vevents(ical_data)
            logger.info(f"[AppleCalendar] WebCal 读取成功: {len(events)} 个事件")
        except Exception as e:
            logger.error(f"[AppleCalendar] WebCal 读取失败: {e}")

        return events

    async def get_all_events(self, days: int = 1) -> List[Dict]:
        """获取所有日历事件（自动选择 WebCal 或 CalDAV）"""
        all_events = []

        # 优先使用 CalDAV（读写）
        if self.username and self.app_password:
            calendars = await self._list_calendars()
            for cal in calendars:
                cal_events = await self._caldav_fetch(cal["url"], days)
                all_events.extend(cal_events)
            return all_events

        # 回退到 WebCal（只读）
        for url in self.webcal_urls:
            all_events.extend(await self.fetch_webcal_async(url, days))

        return all_events

    async def _resolve_calendar_id(self, calendar_id: Optional[str] = None) -> Optional[str]:
        """将配置中的 calendar_id（UUID 或名称）解析为实际 UUID"""
        calendars = await self._list_calendars()
        if not calendars:
            logger.error("[AppleCalendar] 未找到可写日历")
            return None

        # 不指定 → 默认第一个
        if not calendar_id:
            return calendars[0]["id"]

        # UUID 或完整名称精确匹配
        for c in calendars:
            if c["id"] == calendar_id or c["name"] == calendar_id:
                return c["id"]

        # 名称模糊匹配（如配置"日程"，匹配"我的日程"）
        for c in calendars:
            if calendar_id.lower() in c["name"].lower():
                return c["id"]

        # 没找到 → 用默认第一个并记录警告
        logger.warning(f"[AppleCalendar] 日历「{calendar_id}」未找到，使用第一个日历")
        return calendars[0]["id"]

    async def create_event(self, summary: str, start: datetime, end: Optional[datetime] = None, calendar_id: Optional[str] = None, description: str = "") -> Optional[str]:
        """在 iCloud 日历中创建事件，返回事件 UID 或 None"""
        if not await self._discover():
            logger.error("[AppleCalendar] CalDAV 未连接，无法创建事件")
            return None

        # 选择日历（支持 UUID 或名称）
        resolved_id = await self._resolve_calendar_id(calendar_id)
        if not resolved_id:
            return None

        cal_url = self._caldav_base_url + "/" + resolved_id + "/"
        uid = str(uuid.uuid4())

        # 构建 VEVENT
        dtstart_fmt = start.strftime("%Y%m%dT%H%M%S")
        dtend_fmt = (end or (start + timedelta(hours=1))).strftime("%Y%m%dT%H%M%S")
        created = datetime.now().strftime("%Y%m%dT%H%M%S")

        vevent = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Schedule Assistant//AstrBot//
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{created}
DTSTART:{dtstart_fmt}
DTEND:{dtend_fmt}
SUMMARY:{summary}
DESCRIPTION:{description}
END:VEVENT
END:VCALENDAR
""".encode()

        auth = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
            "Content-Type": "text/calendar; charset=utf-8",
            "If-None-Match": "*",
        }

        try:
            async with aiohttp.ClientSession() as session:
                event_url = f"{cal_url}{uid}.ics"
                resp = await session.put(
                    event_url,
                    headers=headers,
                    data=vevent,
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                if resp.status in (200, 201, 204):
                    logger.info(f"[AppleCalendar] 创建事件成功: {summary} (UID={uid})")
                    return uid
                else:
                    body = await resp.text()
                    logger.error(f"[AppleCalendar] 创建事件失败 HTTP {resp.status}: {body[:200]}")
                    return None
        except Exception as e:
            logger.error(f"[AppleCalendar] 创建事件异常: {e}")
            return None

    async def delete_event(self, uid: str, calendar_id: Optional[str] = None) -> bool:
        """删除 iCloud 日历中的事件"""
        if not await self._discover():
            return False

        resolved_id = await self._resolve_calendar_id(calendar_id)
        if not resolved_id:
            return False
        cal_url = self._caldav_base_url + "/" + resolved_id + "/"
        event_url = f"{cal_url}{uid}.ics"

        auth = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
        }

        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.delete(
                    event_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                )
                if resp.status in (200, 204):
                    logger.info(f"[AppleCalendar] 删除事件成功: UID={uid}")
                    return True
                else:
                    logger.error(f"[AppleCalendar] 删除事件失败 HTTP {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"[AppleCalendar] 删除事件异常: {e}")
            return False

    async def close(self):
        """关闭日历会话（无持久连接）"""
        pass

    async def get_late_night_events(self) -> List[Dict]:
        """获取今日凌晨(00:00-06:00)的事件，用于判断是否熬夜"""
        events = await self.get_all_events(days=1)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        late_night_end = today.replace(hour=6)

        late_night = []
        for e in events:
            start_str = e.get("start", "")
            if not start_str:
                continue
            try:
                start = datetime.fromisoformat(start_str)
                if start.hour == 0 and start.minute == 0 and start.second == 0:
                    continue  # 排除全天日程
                if today <= start < late_night_end:
                    late_night.append(e)
            except ValueError:
                continue

        return late_night
