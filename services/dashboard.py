"""
Live Dashboard 状态获取模块

提供异步方式获取 Live Dashboard 设备状态，用于结合用户当前状态生成智能提醒。
"""
import json
import time as _time
import aiohttp
from pathlib import Path

from astrbot import logger

_cached_status = None
_cache_timestamp = 0
_CACHE_TTL = 300


class DashboardService:
    """Dashboard 服务封装"""
    def __init__(self):
        self._cached_status: str | None = None
        self._cache_timestamp: float = 0
        self._CACHE_TTL = 300

    async def get_status(self) -> str:
        """获取 Dashboard 状态（带缓存的异步调用）"""
        global _cached_status, _cache_timestamp
        
        now = _time.time()
        if self._cached_status is not None and (now - self._cache_timestamp) < self._CACHE_TTL:
            return self._cached_status
        
        status = await _get_dashboard_status()
        self._cached_status = status
        self._cache_timestamp = now
        return status


async def _get_dashboard_status() -> str:
    """获取 Live Dashboard 设备状态（异步版本）"""
    global _cached_status, _cache_timestamp
    
    now = _time.time()
    if _cached_status is not None and (now - _cache_timestamp) < _CACHE_TTL:
        return _cached_status
    
    try:
        # 读取 dashboard 配置
        config_path = Path("/AstrBot/data/config/astrbot_plugin_live_dashboard_config.json")
        if not config_path.exists():
            _cached_status = "（未配置 Dashboard）"
            _cache_timestamp = now
            return _cached_status
        
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
        
        base_url = config.get("base_url", "").rstrip("/")
        auth_token = config.get("auth_token", "")
        
        if not base_url:
            _cached_status = "（未配置 Dashboard URL）"
            _cache_timestamp = now
            return _cached_status
        
        # 调用 API 获取状态
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/api/current",
                headers=headers,
                timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _cached_status = _format_dashboard(data)
                    _cache_timestamp = now
                    return _cached_status
                else:
                    _cached_status = f"（Dashboard 请求失败: {resp.status}）"
                    _cache_timestamp = now
                    return _cached_status
    except aiohttp.ClientError as e:
        logger.debug(f"[Dashboard] 请求失败: {e}")
        _cached_status = "（获取 Dashboard 状态失败）"
        _cache_timestamp = now
        return _cached_status
    except Exception as e:
        logger.debug(f"[Dashboard] 获取状态异常: {e}")
        _cached_status = "（获取 Dashboard 状态失败）"
        _cache_timestamp = now
        return _cached_status


def _format_dashboard(data: dict) -> str:
    """格式化 Dashboard 数据为文本描述"""
    try:
        devices = data.get("devices", [])
        if not devices:
            return "（当前无设备在线）"
        
        lines = []
        for device in devices[:5]:  # 最多显示5个设备
            name = device.get("name", "未知设备")
            status = device.get("status", "unknown")
            app = device.get("current_app", "")
            battery = device.get("battery", None)
            
            # 状态映射
            status_text = {
                "online": "在线",
                "offline": "离线",
                "busy": "使用中",
                "active": "活跃",
                "idle": "空闲",
                "sleeping": "可能已睡觉",
                "locked": "已锁屏",
            }.get(status, status)
            
            line = f"{name}: {status_text}"
            if app:
                line += f"，正在用 {app}"
            if battery is not None:
                line += f"，电量 {battery}%"
            
            lines.append(line)
        
        return "；".join(lines) if lines else "设备在线"
    except Exception as e:
        logger.debug(f"[Dashboard] 数据解析失败: {e}")
        return "（Dashboard 数据解析失败）"


async def get_dashboard_status() -> str:
    """兼容性别名"""
    return await _get_dashboard_status()
