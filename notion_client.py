"""
Notion Client - 通过 Maton Gateway 异步调用 Notion API

使用 aiohttp 实现完全异步，兼容 AstrBot 的异步环境。
"""

import time
import json
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

__all__ = ['NotionClient', 'notion_get_pending_async']

# ============ 常量定义 ============
GATEWAY = "https://gateway.maton.ai/notion/v1"

# 全局缓存（300秒TTL）
_pending_cache: Dict[str, Any] = {
    "data": None,
    "timestamp": 0,
    "ttl": 300
}

# ============ 配置（运行时由实例提供）============
_config: Dict[str, str] = {
    "maton_api_key": "",
    "transaction_db_id": "",
    "reading_db_id": ""
}


def _update_config(api_key: str = "", transaction_db_id: str = "", reading_db_id: str = ""):
    """更新全局配置（由 NotionClient.__init__ 调用）"""
    if api_key:
        _config["maton_api_key"] = api_key
    if transaction_db_id:
        _config["transaction_db_id"] = transaction_db_id
    if reading_db_id:
        _config["reading_db_id"] = reading_db_id


def _get_headers() -> Dict[str, str]:
    """获取请求头"""
    api_key = _config.get("maton_api_key", "")
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }


async def _async_request(method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
    """发送异步请求到 Maton Gateway

    Args:
        method: HTTP 方法 (GET, POST, PATCH)
        endpoint: API 端点
        data: 请求体数据

    Returns:
        解析后的 JSON 响应
    """
    url = f"{GATEWAY}/{endpoint}"
    headers = _get_headers()

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, headers=headers, timeout=timeout) as resp:
                    return await resp.json()
            elif method == "POST":
                async with session.post(url, headers=headers, json=data, timeout=timeout) as resp:
                    return await resp.json()
            elif method == "PATCH":
                async with session.patch(url, headers=headers, json=data, timeout=timeout) as resp:
                    return await resp.json()
            else:
                return {"error": f"Unsupported method: {method}"}
    except aiohttp.ClientError as e:
        return {"error": f"Client error: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}


def _is_task_relevant(ddl: Optional[str]) -> bool:
    """判断任务是否相关（已过期或一周内）

    过滤规则：
    - 已过期的任务：显示
    - 一周内的任务：显示
    - 超过一周且未过期的任务：过滤掉
    - 没有截止日期的任务（如阅读）：保持原样
    """
    if not ddl:
        return True

    try:
        due_date = datetime.fromisoformat(ddl.replace('Z', '+00:00'))
        due_date_local = due_date.astimezone().replace(tzinfo=None)
        now = datetime.now()
        one_week_later = now + timedelta(days=7)

        if due_date_local <= now:
            return True
        elif due_date_local <= one_week_later:
            return True
        else:
            return False
    except Exception:
        return True


# ============ NotionClient 类 ============
class NotionClient:
    """Notion API 客户端封装（纯异步）"""

    def __init__(
        self,
        api_key: str = "",
        transaction_db_id: str = "",
        reading_db_id: str = ""
    ):
        """初始化 Notion 客户端（配置统一从 AstrBot 传入）"""
        _update_config(api_key, transaction_db_id, reading_db_id)

        self._db_ids: Dict[str, str] = {}
        if transaction_db_id:
            self._db_ids["事务"] = transaction_db_id
        if reading_db_id:
            self._db_ids["阅读"] = reading_db_id

    def get_db_id(self, db_name: str = "事务") -> str:
        """获取数据库ID"""
        return self._db_ids.get(db_name, "")

    async def query_database(
        self,
        db_id: Optional[str] = None,
        filter: Optional[Dict] = None
    ) -> Dict:
        """查询数据库"""
        db_id = db_id or self.get_db_id("事务")
        return await _async_request("POST", f"databases/{db_id}/query", {"filter": filter} if filter else {})

    async def create_page(
        self,
        parent_db_id: Optional[str] = None,
        properties: Optional[Dict] = None
    ) -> Dict:
        """创建新页面"""
        parent_db_id = parent_db_id or self.get_db_id("事务")
        return await _async_request("POST", "pages", {
            "parent": {"database_id": parent_db_id},
            "properties": properties or {}
        })

    async def update_page(self, page_id: str, properties: Dict) -> Dict:
        """更新页面属性"""
        return await _async_request("PATCH", f"pages/{page_id}", {"properties": properties})

    async def get_pending_transactions(self, use_cache: bool = True) -> List[Dict]:
        """获取所有未完成任务"""
        return await notion_get_pending_async(use_cache)

    async def mark_done(self, page_id: str) -> Dict:
        """标记任务为已完成"""
        return await _async_request("PATCH", f"pages/{page_id}", {
            "进度": {"status": {"name": "已完成"}}
        })


# ============ 模块级异步函数 ============
async def notion_get_pending_async(use_cache: bool = True) -> List[Dict]:
    """异步获取所有未完成任务（只返回已过期或一周内的任务）

    过滤规则：
    - 已过期的任务：显示
    - 一周内的任务：显示
    - 超过一周且未过期的任务：过滤掉
    - 没有截止日期的任务（如阅读）：保持原样
    """
    global _pending_cache

    # 检查缓存
    if use_cache and _pending_cache["data"] and (time.time() - _pending_cache["timestamp"]) < _pending_cache["ttl"]:
        return _pending_cache["data"]

    results: List[Dict] = []

    if not _config.get("transaction_db_id") and not _config.get("reading_db_id"):
        return results

    # 查询事务库
    if _config.get("transaction_db_id"):
        db_id = _config["transaction_db_id"]
        cursor = None
        while True:
            data: Dict = {"page_size": 100}
            if cursor:
                data["start_cursor"] = cursor

            resp = await _async_request("POST", f"databases/{db_id}/query", data)
            if "error" in resp:
                break

            for page in resp.get("results", []):
                props = page.get("properties", {})
                status = props.get("进度", {}).get("status", {}).get("name", "未开始")
                if status in ["已完成", "已搁置"]:
                    continue

                title_list = props.get("内容", {}).get("title", [])
                title = "".join([t.get("plain_text", "") for t in title_list]) or "(无标题)"

                date_prop = props.get("截止日", {}).get("date")
                ddl = date_prop.get("start") if date_prop else None

                if not _is_task_relevant(ddl):
                    continue

                results.append({
                    "page_id": page["id"],
                    "db_name": "事务",
                    "title": title,
                    "status": status,
                    "ddl": ddl
                })

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

    # 查询阅读库（阅读任务没有截止日期，不过滤）
    if _config.get("reading_db_id"):
        db_id = _config["reading_db_id"]
        cursor = None
        while True:
            data: Dict = {"page_size": 100}
            if cursor:
                data["start_cursor"] = cursor

            resp = await _async_request("POST", f"databases/{db_id}/query", data)
            if "error" in resp:
                break

            for page in resp.get("results", []):
                props = page.get("properties", {})
                status = props.get("进度", {}).get("status", {}).get("name", "未开始")
                if status in ["已完成", "已搁置"]:
                    continue

                title_list = props.get("书目", {}).get("title", [])
                title = "".join([t.get("plain_text", "") for t in title_list]) or "(无标题)"

                results.append({
                    "page_id": page["id"],
                    "db_name": "阅读",
                    "title": title,
                    "status": status,
                    "ddl": None
                })

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

    # 更新缓存
    _pending_cache["data"] = results
    _pending_cache["timestamp"] = time.time()
    return results
