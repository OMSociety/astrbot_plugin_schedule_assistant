"""
Notion Client - 通过 Maton Gateway 异步获取未完成任务

只保留 get_pending_transactions()，其他方法已确认在日程助手中未被使用。
所有网络请求统一封装，支持重试、状态码检查和会话复用。
"""

import time
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

GATEWAY = "https://gateway.maton.ai/notion/v1"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3


class NotionClient:
    """通过 Maton Gateway 获取未完成任务（纯异步）"""

    def __init__(self, api_key: str = "", transaction_db_id: str = "", reading_db_id: str = ""):
        self._api_key = api_key
        self._db_ids: Dict[str, str] = {}
        if transaction_db_id:
            self._db_ids["事务"] = transaction_db_id
        if reading_db_id:
            self._db_ids["阅读"] = reading_db_id

        # 实例级缓存，TTL 5 分钟
        self._pending_cache: Dict[str, Any] = {"data": None, "timestamp": 0, "ttl": 300}
        self._http_session: Optional[aiohttp.ClientSession] = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, retries: int = MAX_RETRIES
    ) -> Dict:
        url = f"{GATEWAY}/{endpoint}"
        last_error = None
        for attempt in range(retries):
            try:
                sess = await self._get_http_session()
                async with sess.request(
                    method, url, headers=self._headers(), json=data,
                    timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        await asyncio.sleep(int(resp.headers.get("Retry-After", "5")))
                        continue
                    else:
                        text = await resp.text()
                        return {"error": f"HTTP {resp.status}: {text[:200]}"}
            except Exception as e:
                last_error = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
        return {"error": f"请求失败（已重试{retries}次）: {last_error}"}

    def _relevant(self, ddl: Optional[str]) -> bool:
        if not ddl:
            return True
        try:
            due = datetime.fromisoformat(ddl.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            return due <= datetime.now() or due <= datetime.now() + timedelta(days=7)
        except Exception:
            return True

    async def get_pending_transactions(self, use_cache: bool = True) -> List[Dict]:
        """获取所有未完成任务（带 5 分钟缓存）"""
        if use_cache and self._pending_cache["data"] and \
           (time.time() - self._pending_cache["timestamp"]) < self._pending_cache["ttl"]:
            return self._pending_cache["data"]

        results: List[Dict] = []
        for db_name, db_id in self._db_ids.items():
            results.extend(await self._query_db(db_id, db_name))

        self._pending_cache = {"data": results, "timestamp": time.time(), "ttl": 300}
        return results

    async def _query_db(self, db_id: str, db_name: str) -> List[Dict]:
        results: List[Dict] = []
        cursor = None
        while True:
            body: Dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = await self._request("POST", f"databases/{db_id}/query", body)
            if "error" in resp:
                break
            for page in resp.get("results", []):
                props = page.get("properties", {})
                status = props.get("进度", {}).get("status", {}).get("name", "未开始")
                if status in ("已完成", "已搁置"):
                    continue
                # 根据数据库类型取标题字段
                if db_name == "阅读":
                    title_field = props.get("书目", {}).get("title", [])
                else:
                    title_field = props.get("内容", {}).get("title", [])
                title = "".join(t.get("plain_text", "") for t in title_field) or "(无标题)"
                ddl = None
                if db_name == "事务":
                    ddl = props.get("截止日", {}).get("date", {}).get("start")
                    if not self._relevant(ddl):
                        continue
                results.append({"page_id": page["id"], "db_name": db_name, "title": title, "status": status, "ddl": ddl})
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results
