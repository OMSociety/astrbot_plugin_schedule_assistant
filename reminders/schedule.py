"""
日程提醒模块 - 由 LLM 生成自然语言提醒文本

只扫描 schedule 类型的日程，habit 类型（洗澡/睡觉/喝水）由独立定时任务处理，
避免同一条目被多次提醒。
"""
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from astrbot import logger
from ..constants import LOG_PREFIX


class ScheduleReminder:
    """
    日程 LLM 提醒生成器

    注入信息：
    - 日程名称、时间、备注/描述
    - Dashboard 状态
    - 提前分钟数
    - 近期对话上下文
    """

    def __init__(self, llm_service, dashboard_service):
        self.llm = llm_service
        self.dashboard = dashboard_service

    def _build_prompt(
        self,
        item_title: str,
        item_time: str,
        item_context: str,
        minutes_ahead: int,
        dashboard_status: Dict[str, Any],
        conv_history: str,
    ) -> str:
        """构建 LLM 提醒 prompt"""

        if not isinstance(dashboard_status, dict):
            dashboard_status = {}

        if dashboard_status.get("has_dashboard"):
            dash_lines = []
            for section in ["mood", "energy", "health", "weather", "tasks"]:
                val = dashboard_status.get(section)
                if val:
                    dash_lines.append(f"  - {section}: {val}")
            dash_block = "近期状态:\n" + "\n".join(dash_lines) if dash_lines else "近期状态:（暂无数据）"
        elif dashboard_status.get("raw_text"):
            dash_block = f"近期状态:\n{dashboard_status.get('raw_text').strip()}"
        else:
            dash_block = "近期状态:（未开启 Dashboard）"

        prompt = f"""你是一个贴心的 AI 助手，正在用自然、亲切的语气提醒用户有一个日程要开始了。

日程信息：
  - 名称：{item_title}
  - 时间：{item_time}
  - 备注：{item_context or "（无）"}

{dash_block}

提前提醒时间：{minutes_ahead} 分钟

近期对话上下文：
{conv_history}

请生成一段自然、亲切的提醒文本，要求：
1. 语气像朋友在提醒，不生硬（不用"您"字）
2. 可以根据 Dashboard 状态加入关心（如"今天心情不错呀"）
3. 如果备注有具体内容，融入提醒中
4. 30~80 字以内，不要太长
5. 不要出现括号或 markdown 格式
6. 开头用 emoji 引起注意，结尾可加 ~ 或 ♪
"""
        return prompt.strip()

    async def generate_reminder_text(
        self,
        item_title: str,
        item_time: str,
        item_context: str,
        minutes_ahead: int = 10,
        conv_history: Optional[str] = None,
    ) -> str:
        """生成提醒文本（带 LLM fallback）"""

        try:
            if self.dashboard and hasattr(self.dashboard, "get_status"):
                dashboard_text = await self.dashboard.get_status()
                dashboard_status = {"raw_text": dashboard_text} if dashboard_text else {"has_dashboard": False}
            else:
                dashboard_status = {"has_dashboard": False}
        except Exception:
            dashboard_status = {"has_dashboard": False}

        conv_str = conv_history or "（无近期对话历史）"

        prompt = self._build_prompt(
            item_title=item_title,
            item_time=item_time,
            item_context=item_context,
            minutes_ahead=minutes_ahead,
            dashboard_status=dashboard_status,
            conv_history=conv_str,
        )

        try:
            resp = await self.llm.generate_llm_message(
                prompt=prompt,
                system_prompt="你是一个贴心的 AI 助手。回复内容就是提醒文本，不要加任何说明。",
                temperature=0.7,
            )
            text = resp.strip() if resp else None
            if text and len(text) > 5:
                logger.debug(f"{LOG_PREFIX} LLM 提醒生成成功: {text[:30]}...")
                return text
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} LLM 提醒生成失败: {e}")

        return f"📅 提醒：「{item_title}」即将开始，记得准备哦~"


def _parse_time(time_str: str) -> Optional[datetime]:
    """解析时间字符串为 datetime"""
    if not time_str:
        return None
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%H:%M"]:
        try:
            return datetime.strptime(time_str.strip(), fmt)
        except ValueError:
            continue
    return None


async def check_and_trigger_schedule_reminder(
    schedule_store,
    llm_service,
    dashboard_service,
    user_id: str,
    minutes_window: int = 30,
) -> List[Dict[str, Any]]:
    """
    扫描即将到来的日程（仅 schedule 类型）并生成提醒。

    habit 类型（洗澡/睡觉/喝水）由独立定时任务处理，不在此扫描，避免重复提醒。
    """
    reminder = ScheduleReminder(llm_service, dashboard_service)
    triggered = []
    now = datetime.now()

    all_items = await schedule_store.list_all_items(user_id)

    for item in all_items:
        if not item.enabled:
            continue

        # 跳过习惯类型：洗澡/睡觉/喝水已有独立定时任务，避免重复提醒
        if item.type == "habit":
            continue

        item_dt = _parse_time(item.time)

        if not item_dt:
            continue

        minutes_until = (item_dt - now).total_seconds() / 60

        # 检查是否已触发过（1小时内避免重复）
        if item.last_triggered:
            try:
                last_dt = datetime.fromisoformat(item.last_triggered)
                if (now - last_dt).total_seconds() > 3600:
                    item.last_triggered = None
            except (ValueError, TypeError):
                pass

        # 仅在窗口期内且未被触发时发送
        if 0 <= minutes_until <= minutes_window:
            if item.last_triggered:
                continue

            conv_history = schedule_store.format_history_for_prompt(
                await schedule_store.get_conversation_history(user_id)
            )

            reminder_text = await reminder.generate_reminder_text(
                item_title=item.title,
                item_time=item.time,
                item_context=item.context,
                minutes_ahead=int(minutes_until),
                conv_history=conv_history,
            )

            triggered.append({
                "item_id": item.id,
                "title": item.title,
                "reminder_text": reminder_text,
                "minutes_until": int(minutes_until),
                "type": item.type,
            })

            item.last_triggered = now.isoformat()
            await schedule_store.update_item(user_id, item)

    return triggered
