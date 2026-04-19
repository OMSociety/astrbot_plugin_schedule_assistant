"""
Notion Client - 通过 Maton Gateway 异步调用 Notion API

使用 aiohttp 实现完全异步，兼容 AstrBot 的异步环境。
所有网络请求统一封装，支持重试、状态码检查和会话复用。
"""

import time
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

__all__ = ['NotionClient', 'notion_get_pending_async']

# ============ 常量定义 ============
GATEWAY = "https://gateway.maton.ai/notion/v1"
DEFAULT_TIMEOUT = 30  # 秒
MAX_RETRIES = 3


# ============ NotionClient 类（实例化后使用）============
class NotionClient:
    """Notion API 客户端封装（纯异步，实例隔离）"""

    def __init__(
        self,
        api_key: str = "",
        transaction_db_id: str = "",
        reading_db_id: str = ""
    ):
        """初始化 Notion 客户端（配置统一从 AstrBot 传入）"""
        self._api_key = api_key
        self._db_ids: Dict[str, str] = {}
        if transaction_db_id:
            self._db_ids["事务"] = transaction_db_id
        if reading_db_id:
            self._db_ids["阅读"] = reading_db_id
        
        # 实例级缓存（多用户不串数据）
        self._pending_cache: Dict[str, Any] = {
            "data": None,
            "timestamp": 0,
            "ttl": 300
        }
        # 实例级 session 复用
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建复用的 aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _async_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        retries: int = MAX_RETRIES
    ) -> Dict:
        """发送异步请求到 Maton Gateway（带重试）

        Args:
            method: HTTP 方法 (GET, POST, PATCH)
            endpoint: API 端点
            data: 请求体数据
            retries: 最大重试次数

        Returns:
            解析后的 JSON 响应
        """
        url = f"{GATEWAY}/{endpoint}"
        headers = self._get_headers()
        last_error = None

        for attempt in range(retries):
            try:
                session = await self._get_session()
                timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=data,
                    timeout=timeout
                ) as resp:
                    # 处理常见 HTTP 错误
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 401:
                        return {"error": "Unauthorized: 请检查 Maton API Key"}
                    elif resp.status == 403:
                        return {"error": "Forbidden: 无权限访问该数据库"}
                    elif resp.status == 404:
                        return {"error": "Not Found: 数据库ID不存在"}
                    elif resp.status == 429:
                        # 限流，等待后重试
                        retry_after = resp.headers.get("Retry-After", "5")
                        await asyncio.sleep(int(retry_after))
                        continue
                    else:
                        text = await resp.text()
                        return {"error": f"HTTP {resp.status}: {text[:200]}"}
            except aiohttp.ClientError as e:
                last_error = f"Client error: {str(e)}"
            except Exception as e:
                last_error = str(e)

            # 非致命错误，稍后重试
            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))

        return {"error": f"请求失败（已重试{retries}次）: {last_error}"}

    def _get_db_id(self, db_name: str = "事务") -> str:
        """获取数据库ID"""
        return self._db_ids.get(db_name, "")

    def _is_task_relevant(self, ddl: Optional[str]) -> bool:
        """判断任务是否相关（已过期或一周内）"""
        if not ddl:
            return True
        try:
            due_date = datetime.fromisoformat(ddl.replace('Z', '+00:00'))
            due_date_local = due_date.astimezone().replace(tzinfo=None)
            now = datetime.now()
            one_week_later = now + timedelta(days=7)
            return due_date_local <= now or due_date_local <= one_week_later
        except Exception:
            return True

    async def query_database(
        self,
        db_id: Optional[str] = None,
        filter: Optional[Dict] = None
    ) -> Dict:
        """查询数据库"""
        db_id = db_id or self._get_db_id("事务")
        return await self._async_request("POST", f"databases/{db_id}/query", {"filter": filter} if filter else {})

    async def create_page(
        self,
        parent_db_id: Optional[str] = None,
        properties: Optional[Dict] = None
    ) -> Dict:
        """创建新页面"""
        parent_db_id = parent_db_id or self._get_db_id("事务")
        return await self._async_request("POST", "pages", {
            "parent": {"database_id": parent_db_id},
            "properties": properties or {}
        })

    async def update_page(self, page_id: str, properties: Dict) -> Dict:
        """更新页面属性"""
        return await self._async_request("PATCH", f"pages/{page_id}", {"properties": properties})

    async def get_pending_transactions(self, use_cache: bool = True) -> List[Dict]:
        """获取所有未完成任务"""
        return await self._get_pending(use_cache)

    async def mark_done(self, page_id: str) -> Dict:
        """标记任务为已完成"""
        return await self._async_request("PATCH", f"pages/{page_id}", {
            "进度": {"status": {"name": "已完成"}}
        })

    async def _get_pending(self, use_cache: bool = True) -> List[Dict]:
        """内部：获取未完成任务（带实例缓存）"""
        if use_cache and self._pending_cache["data"] and \
           (time.time() - self._pending_cache["timestamp"]) < self._pending_cache["ttl"]:
            return self._pending_cache["data"]

        results: List[Dict] = []
        transaction_db_id = self._db_ids.get("事务", "")
        reading_db_id = self._db_ids.get("阅读", "")

        if not transaction_db_id and not reading_db_id:
            return results

        # 查询事务库
        if transaction_db_id:
            results.extend(await self._query_db_with_pagination(transaction_db_id, is_reading=False))

        # 查询阅读库
        if reading_db_id:
            results.extend(await self._query_db_with_pagination(reading_db_id, is_reading=True))

        # 更新实例缓存
        self._pending_cache["data"] = results
        self._pending_cache["timestamp"] = time.time()
        return results

    async def _query_db_with_pagination(self, db_id: str, is_reading: bool) -> List[Dict]:
        """分页查询数据库"""
        results: List[Dict] = []
        cursor = None

        while True:
            data: Dict = {"page_size": 100}
            if cursor:
                data["start_cursor"] = cursor

            resp = await self._async_request("POST", f"databases/{db_id}/query", data)
            if "error" in resp:
                break

            for page in resp.get("results", []):
                props = page.get("properties", {})
                status = props.get("进度", {}).get("status", {}).get("name", "未开始")
                if status in ["已完成", "已搁置"]:
                    continue

                if is_reading:
                    title_list = props.get("书目", {}).get("title", [])
                    title = "".join([t.get("plain_text", "") for t in title_list]) or "(无标题)"
                    results.append({
                        "page_id": page["id"],
                        "db_name": "阅读",
                        "title": title,
                        "status": status,
                        "ddl": None
                    })
                else:
                    title_list = props.get("内容", {}).get("title", [])
                    title = "".join([t.get("plain_text", "") for t in title_list]) or "(无标题)"
                    date_prop = props.get("截止日", {}).get("date")
                    ddl = date_prop.get("start") if date_prop else None
                    if not self._is_task_relevant(ddl):
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

        return results

