"""
Live Dashboard 状态获取模块

提供异步和同步两种方式获取 Live Dashboard 设备状态，
用于结合用户当前状态生成智能提醒。
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import aiohttp

from astrbot import logger


async def get_dashboard_status() -> str:
    """
    获取 Live Dashboard 设备状态（异步版本）
    
    从 dashboard 配置读取 URL 和认证信息，调用 API 获取当前设备状态。
    
    Returns:
        格式化的设备状态描述字符串，如：
        "设备名: 在线，正在使用: 应用名，电量80%"
        或错误提示如 "（未配置 Dashboard）"
    """
    try:
        # 读取 dashboard 配置
        config_path = Path("/AstrBot/data/config/astrbot_plugin_live_dashboard_config.json")
        if not config_path.exists():
            return "（未配置 Dashboard）"
        
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
        
        base_url = config.get("base_url", "").rstrip("/")
        auth_token = config.get("auth_token", "")
        
        if not base_url:
            return "（未配置 Dashboard URL）"
        
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
                    return _format_dashboard(data)
                else:
                    return f"（Dashboard 请求失败: {resp.status}）"
    except aiohttp.ClientError as e:
        logger.warning(f"[Dashboard] 请求失败: {e}")
        return "（获取 Dashboard 状态失败）"
    except Exception as e:
        logger.warning(f"[Dashboard] 获取状态异常: {e}")
        return "（获取 Dashboard 状态失败）"


def get_dashboard_status_sync() -> str:
    """
    获取 Live Dashboard 设备状态（同步版本，供遗留调用）
    
    注意：此方法在新版本中不推荐使用，优先使用异步版本。
    内部通过线程池在异步环境中运行。
    
    Returns:
        格式化的设备状态描述字符串
    """
    try:
        # 检查是否在异步事件循环中
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在异步环境中，使用线程池运行
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, get_dashboard_status())
                    return future.result(timeout=10)
            else:
                # 不在运行中的事件循环，直接运行
                return loop.run_until_complete(get_dashboard_status())
        except RuntimeError:
            # 没有事件循环，创建临时循环
            return asyncio.run(get_dashboard_status())
    except Exception as e:
        logger.warning(f"[Dashboard] 同步获取失败: {e}")
        return "（获取 Dashboard 状态失败）"


def _format_dashboard(data: dict) -> str:
    """
    格式化 Dashboard 数据为文本描述
    
    Args:
        data: Dashboard API 返回的原始数据
        
    Returns:
        格式化的状态描述字符串
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
            status_text = {
                "online": "在线",
                "offline": "离线",
                "busy": "使用中"
            }.get(status, status)
            
            line = f"{name}: {status_text}"
            if app:
                line += f"，正在使用: {app}"
            if battery is not None:
                line += f"，电量{battery}%"
            
            lines.append(line)
        
        return "；".join(lines)
    except Exception as e:
        logger.warning(f"[Dashboard] 数据解析失败: {e}")
        return "（Dashboard 数据解析失败）"
