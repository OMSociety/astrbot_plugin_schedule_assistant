"""
Live Dashboard 状态获取模块

提供异步方式获取 Live Dashboard 设备状态，用于结合用户当前状态生成智能提醒。

使用实例方法缓存，消除全局变量，支持多个 DashboardService 实例独立运行。
"""
import json
import time
import aiohttp
from pathlib import Path
from typing import Optional

from astrbot import logger

from ..constants import LOG_PREFIX


class DashboardService:
    """
    Dashboard 服务封装

    提供带缓存（TTL 300秒）的 Dashboard 状态获取功能。
    纯实例方法，无全局状态，可安全创建多个实例。
    """

    def __init__(self, cache_ttl: int = 300):
        """
        初始化 Dashboard 服务

        Args:
            cache_ttl: 缓存时间（秒），默认 300 秒
        """
        self._cached_status: Optional[str] = None
        self._cache_timestamp: float = 0
        self._cache_ttl: int = cache_ttl
        self._config_path: Path = Path("/AstrBot/data/config/astrbot_plugin_live_dashboard_config.json")

    async def get_status(self) -> str:
        """
        获取 Dashboard 状态（带缓存）

        Returns:
            str: 格式化的设备状态描述
        """
        now = time.time()

        # 检查缓存
        if self._cached_status is not None and (now - self._cache_timestamp) < self._cache_ttl:
            return self._cached_status

        # 从 Dashboard API 获取
        status = await self._fetch_dashboard_status()
        self._cached_status = status
        self._cache_timestamp = now
        return status

    async def _fetch_dashboard_status(self) -> str:
        """从 Dashboard API 获取状态（内部方法）"""
        try:
            # 读取配置
            if not self._config_path.exists():
                return "（未配置 Dashboard）"

            with open(self._config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)

            base_url = config.get("base_url", "").rstrip("/")
            auth_token = config.get("auth_token", "")

            if not base_url:
                return "（未配置 Dashboard URL）"

            # 调用 API
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
                        return self._format_dashboard(data)
                    else:
                        return f"（Dashboard 请求失败: {resp.status}）"

        except aiohttp.ClientError as e:
            logger.debug(f"{LOG_PREFIX} Dashboard 请求失败: {e}")
            return "（获取 Dashboard 状态失败）"
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} Dashboard 获取异常: {e}")
            return "（获取 Dashboard 状态失败）"

    @staticmethod
    def _format_dashboard(data: dict) -> str:
        """
        格式化 Dashboard 数据为文本描述

        Args:
            data: Dashboard API 返回的原始数据

        Returns:
            str: 格式化后的设备状态描述
        """
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
                status_map = {
                    "online": "在线",
                    "offline": "离线",
                    "busy": "使用中",
                    "active": "活跃",
                    "idle": "空闲",
                    "sleeping": "可能已睡觉",
                    "locked": "已锁屏",
                }
                status_text = status_map.get(status, status)

                line = f"{name}: {status_text}"
                if app:
                    line += f"，正在用 {app}"
                if battery is not None:
                    line += f"，电量 {battery}%"

                lines.append(line)

            return "；".join(lines) if lines else "设备在线"

        except Exception as e:
            logger.debug(f"{LOG_PREFIX} Dashboard 数据解析失败: {e}")
            return "（Dashboard 数据解析失败）"


# 兼容旧代码的全局函数（已废弃，建议使用 DashboardService 实例）
async def get_dashboard_status() -> str:
    """
    兼容性别名（已废弃）

    创建临时实例并获取状态。建议改为持有 DashboardService 实例并调用 get_status()。
    """
    service = DashboardService()
    return await service.get_status()
