"""
日程提醒模块 - 由 LLM 生成自然语言提醒文本
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
        item_type: str,
        minutes_ahead: int,
        dashboard_status: Dict[str, Any],
        conv_history: str,
    ) -> str:
        """构建 LLM 提醒 prompt"""
        
        if item_type == "habit":
            label = "习惯"
            time_display = f"设定时间 {item_time}"
        else:
            label = "日程"
            time_display = f"时间 {item_time}"
        
        if dashboard_status.get("has_dashboard"):
            dash_lines = []
            for section in ["mood", "energy", "health", "weather", "tasks"]:
                val = dashboard_status.get(section)
                if val:
                    dash_lines.append(f"  - {section}: {val}")
            dash_block = "近期状态:\n" + "\n".join(dash_lines) if dash_lines else "近期状态:（暂无数据）"
        else:
            dash_block = "近期状态:（未开启 Dashboard）"
        
        prompt = f"""你是一个贴心的 AI 助手，正在用自然、亲切的语气提醒用户有一个{label}要开始了。

{label}信息：
  - 名称：{item_title}
  - {time_display}
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
        item_type: str,
        minutes_ahead: int = 10,
        conv_history: Optional[str] = None,
    ) -> str:
        """生成提醒文本（带 LLM fallback）"""
        
        try:
            dashboard_status = {"has_dashboard": False}
        except Exception:
            dashboard_status = {"has_dashboard": False}
        
        conv_str = conv_history or "（无近期对话历史）"
        
        prompt = self._build_prompt(
            item_title=item_title,
            item_time=item_time,
            item_context=item_context,
            item_type=item_type,
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
            logger.warning(f"{LOG_PREFIX} LLM 提醒生成失败: {e}")
        
        if item_type == "habit":
            return f"🔔 提醒：该{item_title}的时间到啦~"
        else:
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
    minutes_window: int = 80,
) -> List[Dict[str, Any]]:
    """
    扫描即将到来的日程并生成提醒
    """
    reminder = ScheduleReminder(llm_service, dashboard_service)
    triggered = []
    now = datetime.now()
    
    all_items = await schedule_store.list_all_items(user_id)
    
    for item in all_items:
        if not item.enabled:
            continue
        
        if item.type == "habit":
            effective_time = await schedule_store.get_effective_time(user_id, item.title, item.time)
            item_dt = _parse_time(effective_time)
            if item_dt:
                item_dt = now.replace(hour=item_dt.hour, minute=item_dt.minute, second=0, microsecond=0)
        else:
            item_dt = _parse_time(item.time)
        
        if not item_dt:
            continue
        
        minutes_until = (item_dt - now).total_seconds() / 60
        
        if item.last_triggered:
            try:
                last_dt = datetime.fromisoformat(item.last_triggered)
                if (now - last_dt).total_seconds() > 3600:
                    item.last_triggered = None
            except (ValueError, TypeError):
                pass
        
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
                item_type=item.type,
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
