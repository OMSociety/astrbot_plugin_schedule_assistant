"""天气服务 - 心知天气 API，带 30 分钟缓存"""

from __future__ import annotations

import asyncio
import time as _time

import aiohttp


class WeatherService:
    CACHE_TTL = 1800

    def __init__(self, api_key: str, city: str = "北京"):
        self.api_key = api_key
        self.city = city or "北京"
        self._cache: tuple[str, str] = ("", "")
        self._cache_at = 0.0

    async def fetch(self) -> tuple[str, str]:
        if not self.api_key:
            return "", ""
        if (self._cache[0] or self._cache[1]) and (
            _time.time() - self._cache_at < self.CACHE_TTL
        ):
            return self._cache[0], self._cache[1]

        current, forecast = "", ""
        try:
            async with aiohttp.ClientSession() as session:
                now_params = {
                    "key": self.api_key,
                    "location": self.city,
                    "language": "zh-Hans",
                    "unit": "c",
                }
                async with session.get(
                    "https://api.seniverse.com/v3/weather/now.json",
                    params=now_params,
                    timeout=20,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            now = results[0].get("now", {})
                            current = (
                                f"{now.get('text', '未知')}, "
                                f"{now.get('temperature', '?')}°C"
                            )
                daily_params = {
                    "key": self.api_key,
                    "location": self.city,
                    "language": "zh-Hans",
                    "unit": "c",
                }
                async with session.get(
                    "https://api.seniverse.com/v3/weather/daily.json",
                    params=daily_params,
                    timeout=20,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            daily = results[0].get("daily", [])
                            if daily:
                                today = daily[0]
                                forecast = (
                                    f"白天{today.get('text_day', '未知')} / "
                                    f"夜间{today.get('text_night', '未知')}, "
                                    f"{today.get('low', '?')}~"
                                    f"{today.get('high', '?')}°C, "
                                    f"降水概率{today.get('precip', '0')}%"
                                )
        except asyncio.TimeoutError:
            current = "获取超时"
        except Exception:
            current = "获取失败"
        self._cache = (current, forecast)
        self._cache_at = _time.time()
        return current, forecast
