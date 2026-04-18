"""
Apple iCloud Calendar (CalDAV) 适配器

当前仅支持 WebCal 公共日历订阅，使用 aiohttp 实现完全异步。
"""

import uuid
import re
import base64
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from astrbot import logger

__all__ = ['AppleCalendar']


class AppleCalendar:
    """Apple 日历客户端（当前仅支持 WebCal 公共日历订阅）"""

    CALDAV_SERVERS = {
        'icloud': 'https://caldav.icloud.com',
        'icloud_cn': 'https://caldav.icloud.com.cn',
        '163': 'https://caldav.163.com',
    }

    def __init__(
        self,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        webcal_urls: Optional[List[str]] = None
    ):
        self.username = username
        self.app_password = app_password
        self.webcal_urls = webcal_urls or []

        self.auth = None
        self.BASE_URL = None
        if username and app_password:
            credentials = f"{username}:{app_password}"
            self.auth = base64.b64encode(credentials.encode()).decode()
            self.BASE_URL = self._detect_server(username)
            logger.info(f"[AppleCalendar] 使用服务器: {self.BASE_URL}")

    def _detect_server(self, username: str) -> str:
        if "@163.com" in username:
            return self.CALDAV_SERVERS.get('icloud_cn', self.CALDAV_SERVERS['icloud'])
        return self.CALDAV_SERVERS['icloud']

    async def fetch_webcal_async(self, url: str, days: int = 30) -> List[Dict]:
        """异步读取 WebCal 公共日历

        Args:
            url: WebCal 订阅 URL
            days: 向前获取的天数

        Returns:
            事件列表，每项包含 uid, summary, description, start, end, all_day
        """
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

            vevents = re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', ical_data, re.DOTALL)

            local_tz = datetime.now().astimezone().tzinfo
            now = datetime.now().replace(tzinfo=None)
            # 根据 days 参数计算日期范围
            range_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            range_end = range_start + timedelta(days=days)

            for ev in vevents:
                summary_match = re.search(r'SUMMARY:([^\r\n]+)', ev)
                dtstart_match = re.search(r'DTSTART(?:;[\w=]+)?:?([\dT]+)', ev)
                dtend_match = re.search(r'DTEND(?:;[\w=]+)?:?([\dT]+)', ev)
                uid_match = re.search(r'UID:([^\r\n]+)', ev)

                summary = summary_match.group(1).strip() if summary_match else "无标题"
                uid = uid_match.group(1).strip() if uid_match else str(uuid.uuid4())

                start_time = None
                if dtstart_match:
                    ds = dtstart_match.group(1).strip()
                    if len(ds) == 8:
                        start_time = datetime.strptime(ds, "%Y%m%d")
                    elif len(ds) >= 15:
                        try:
                            from datetime import timezone
                            utc_time = datetime.strptime(ds[:15], "%Y%m%dT%H%M%S")
                            utc_time = utc_time.replace(tzinfo=timezone.utc)
                            start_time = utc_time.astimezone(local_tz).replace(tzinfo=None)
                        except ValueError:
                            start_time = datetime.strptime(ds[:8], "%Y%m%d")

                end_time = None
                if dtend_match:
                    ds = dtend_match.group(1).strip()
                    if len(ds) == 8:
                        end_time = datetime.strptime(ds, "%Y%m%d")
                    elif len(ds) >= 15:
                        try:
                            from datetime import timezone
                            utc_time = datetime.strptime(ds[:15], "%Y%m%dT%H%M%S")
                            utc_time = utc_time.replace(tzinfo=timezone.utc)
                            end_time = utc_time.astimezone(local_tz).replace(tzinfo=None)
                        except ValueError:
                            end_time = datetime.strptime(ds[:8], "%Y%m%d")

                if start_time:
                    if start_time < range_start or start_time >= range_end:
                        continue
                    events.append({
                        "uid": uid,
                        "summary": summary,
                        "description": "",
                        "start": start_time.isoformat(),
                        "end": end_time.isoformat() if end_time else None,
                        "all_day": len(dtstart_match.group(1).strip()) == 8 if dtstart_match else False
                    })

            logger.info(f"[AppleCalendar] WebCal读取成功: {len(events)} 个事件")
        except Exception as e:
            logger.error(f"[AppleCalendar] WebCal读取失败: {e}")

        return events

    async def get_all_events(self, days: int = 1) -> List[Dict]:
        """获取所有日历事件（异步）

        Args:
            days: 获取的天数

        Returns:
            合并后的所有事件列表
        """
        all_events = []
        for url in self.webcal_urls:
            all_events.extend(await self.fetch_webcal_async(url, days))
        return all_events
