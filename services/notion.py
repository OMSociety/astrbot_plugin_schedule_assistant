"""Notion 服务 - 封装 NotionClient，添加格式化功能"""
import time
from datetime import datetime
from typing import List, Dict, Optional
from ..notion_client import NotionClient


class NotionService:
    """Notion 服务，封装 NotionClient，提供格式化输出"""

    def __init__(self, notion_client: Optional[NotionClient]):
        self.notion = notion_client
        self._failure_time = 0.0  # 断路器：记录最近失败时间
        self._CIRCUIT_BREAKER_TTL = 300  # 5分钟

    @staticmethod
    def format_ddl(ddl_str: str) -> str:
        """格式化截止日期显示"""
        if not ddl_str:
            return ""
        try:
            due = datetime.fromisoformat(ddl_str.replace("Z", "+00:00"))
            due_local = due.astimezone().replace(tzinfo=None)
            diff = (due_local.date() - datetime.now().date()).days
            if diff < 0:
                return f"已逾期{-diff}天"
            elif diff == 0:
                return "今天截止"
            elif diff == 1:
                return "还剩1天"
            else:
                return f"还剩{diff}天"
        except Exception:
            return ""

    async def get_pending_tasks(self) -> List[Dict]:
        """获取未完成任务列表（带断路器保护）"""
        if not self.notion:
            return []
        if self._failure_time and (time.time() - self._failure_time) < self._CIRCUIT_BREAKER_TTL:
            return []
        return await self.notion.get_pending_transactions()


    async def get_pending_str(self) -> str:
        """获取未完成任务字符串（带断路器保护）"""
        if not self.notion:
            return "暂无待办"
        if self._failure_time and (time.time() - self._failure_time) < self._CIRCUIT_BREAKER_TTL:
            return "暂无待办"
        try:
            pending = await self.notion.get_pending_transactions()
            if not pending:
                return "暂无待办"
            lines = []
            for t in pending[:5]:
                ddl = self.format_ddl(t.get("ddl", ""))
                if ddl:
                    lines.append(f"- {ddl} | {t['title']}")
                else:
                    lines.append(f"- {t['title']} ({t['status']})")
            return "\n".join(lines)
        except Exception:
            self._failure_time = time.time()
            return "暂无待办"
