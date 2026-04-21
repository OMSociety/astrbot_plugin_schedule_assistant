"""Dashboard 服务"""
import time
import aiohttp

_cached_status = None
_cache_timestamp = 0
_CACHE_TTL = 300


class DashboardService:
    def __init__(self):
        self.func = get_dashboard_status


async def get_dashboard_status() -> str:
    global _cached_status, _cache_timestamp
    now = time.time()
    if _cached_status is not None and (now - _cache_timestamp) < _CACHE_TTL:
        return _cached_status
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:3000/api/status", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    device = (data.get("devices") or [{}])[0]
                    status = device.get("status", "offline")
                    app = device.get("currentApp", "未知")
                    battery = device.get("batteryLevel")
                    parts = []
                    if app and app != "未知":
                        parts.append(f"正在用{app}")
                    if status == "active" and battery is not None:
                        parts.append(f"屏幕亮着，电量{battery}%")
                    elif status == "idle":
                        parts.append("屏幕空闲中")
                    elif status == "sleeping":
                        parts.append("可能已睡觉")
                    elif status == "locked":
                        parts.append("设备已锁屏")
                    _cached_status = "，".join(parts) if parts else "在线"
                    _cache_timestamp = now
                    return _cached_status
    except Exception:
        pass
    _cached_status = ""
    return ""
