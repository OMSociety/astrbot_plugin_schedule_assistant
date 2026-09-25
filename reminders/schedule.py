"""
日程提醒模块 - 由 LLM 生成自然语言提醒文本

只扫描 schedule 类型的日程，habit 类型（洗澡/睡觉/喝水）由独立定时任务处理，
避免同一条目被多次提醒。prompt 配置化（prompt_settings.prompt_schedule）。
"""

from datetime import datetime
from typing import Any

from astrbot.api import logger

from ..constants import BROADCAST_MD_OVERRIDE, LOG_PREFIX
from ..prompt_config import DEFAULT_PROMPT_SCHEDULE, render_prompt
from ..time_parser import is_all_day_event, parse_item_time


class ScheduleReminder:
    """
    日程 LLM 提醒生成器

    注入信息：
    - 日程名称、时间、备注/描述
    - 提前分钟数
    - 近期对话上下文
    """

    def __init__(self, llm_service, config: dict | None = None):
        self.llm = llm_service
        self.config = config or {}

    def _build_prompt(
        self,
        item_title: str,
        item_time: str,
        item_context: str,
        minutes_ahead: int,
        conv_history: str,
        item_end_time: str | None = None,
    ) -> str:
        """构建 LLM 提醒 prompt（config 化，默认自然口语模板）"""

        time_label = self._format_time_label(item_time, item_end_time)
        ahead_label = self._format_ahead_label(minutes_ahead)
        template = self.config.get("prompt_schedule") or DEFAULT_PROMPT_SCHEDULE

        return render_prompt(
            template,
            {
                "item_title": item_title,
                "time_label": time_label,
                "ahead_label": ahead_label,
                "item_context": item_context or "",
                "conv_history": conv_history or "（无近期对话历史）",
            },
        )

    @staticmethod
    def _format_time_label(item_time: str, end_time: str | None = None) -> str:
        """时间标签：区间为 '14:30-16:30'，单点为 '14:30'，解析失败则原样返回"""
        start_dt = parse_item_time(item_time)
        if not start_dt:
            return item_time or ""
        end_dt = parse_item_time(end_time) if end_time else None
        if end_dt:
            return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
        return start_dt.strftime("%H:%M")

    @staticmethod
    def _format_ahead_label(minutes_ahead: int) -> str:
        """把提前分钟数转成通顺表述"""
        try:
            m = int(minutes_ahead)
        except (ValueError, TypeError):
            return "即将"
        if m <= 0:
            return "马上开始"
        if m < 60:
            return f"{m} 分钟后开始"
        h, rem = divmod(m, 60)
        if rem == 0:
            return f"{h} 小时后开始"
        return f"{h}小时{rem}分后开始"

    async def generate_reminder_text(
        self,
        item_title: str,
        item_time: str,
        item_context: str,
        minutes_ahead: int = 10,
        conv_history: str | None = None,
        user_id: str | None = None,
        item_end_time: str | None = None,
    ) -> str:
        """生成提醒文本（带 LLM fallback）"""

        conv_str = conv_history or "（无近期对话历史）"

        prompt = self._build_prompt(
            item_title=item_title,
            item_time=item_time,
            item_context=item_context,
            minutes_ahead=minutes_ahead,
            conv_history=conv_str,
            item_end_time=item_end_time,
        )

        try:
            # prompt 已含 conv_history，不再额外传 history= 避免重复注入
            resp = await self.llm.generate(
                prompt, umo=user_id, extra_system=BROADCAST_MD_OVERRIDE
            )
            text = resp.strip() if resp else None
            if text and len(text) > 5:
                logger.debug(f"{LOG_PREFIX} LLM 提醒生成成功: {text[:30]}...")
                return text
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} LLM 提醒生成失败: {e}")

        return f"📅 提醒：「{item_title}」即将开始，记得准备哦~"


async def check_and_trigger_schedule_reminder(
    schedule_store,
    llm_service,
    user_id: str,
    minutes_before: int = 15,
    reminder: "ScheduleReminder | None" = None,
) -> list[dict[str, Any]]:
    """
    扫描即将到来的日程（仅 schedule 类型）并生成提醒。

    habit 类型（洗澡/睡觉/喝水）由独立定时任务处理，不在此扫描，避免重复提醒。

    提醒时机：日程开始前 minutes_before 分钟内触发一次（窗口含上边界；<=0 时不触发）；
    全天事件不触发提前提醒。防重标记 last_triggered 持久有效，事件改期时由同步层
    （schedule_store.sync_from_apple_calendar）或工具层（update_schedule）重置。

    防重标记的落盘由调用方在**确认提醒发送成功后**调用本模块的
    ``mark_schedule_reminder_triggered`` 完成（见该函数 docstring）。
    本函数只负责筛出到点的日程并生成文案：LLM 文案生成在落盘责任之外，
    文案生成失败也不丢提醒。
    """
    # 复用调用方已创建的实例，避免每轮扫描重复构造
    reminder = reminder or ScheduleReminder(llm_service)
    triggered = []
    now = datetime.now()

    all_items = await schedule_store.list_all_items(user_id)

    for item in all_items:
        if not item.enabled:
            continue

        # 跳过习惯类型：洗澡/睡觉/喝水已有独立定时任务，避免重复提醒
        if item.type == "habit":
            continue

        # 跳过全天事件（提前提醒不适用）
        if is_all_day_event(item):
            continue

        item_dt = parse_item_time(item.time)

        if not item_dt:
            continue

        minutes_until = (item_dt - now).total_seconds() / 60

        # 防重：last_triggered 持久有效（改期由同步层/工具层重置），同一事件只提醒一次
        if item.last_triggered:
            continue

        # 提前提醒窗口：开始前 minutes_before 分钟内（含上边界）
        if not 0 < minutes_until <= minutes_before:
            continue

        trigger_minutes = int(minutes_until)

        conv_history = schedule_store.format_history_for_prompt(
            await schedule_store.get_conversation_history(user_id)
        )

        reminder_text = await reminder.generate_reminder_text(
            item_title=item.title,
            item_time=item.time,
            item_context=item.context,
            minutes_ahead=trigger_minutes,
            conv_history=conv_history,
            user_id=user_id,
            item_end_time=item.end_time,
        )

        # 不在这里落 last_triggered：发送由调用方完成，先落盘会在发送失败时
        # 让该日程本期（乃至永久）不再提醒
        triggered.append(
            {
                "item_id": item.id,
                "user_id": user_id,
                "title": item.title,
                "reminder_text": reminder_text,
                "minutes_until": trigger_minutes,
                "type": item.type,
            }
        )

    return triggered


async def mark_schedule_reminder_triggered(
    schedule_store, user_id: str, item_id: str, triggered_at: datetime | None = None
) -> bool:
    """发送成功后落防重标记 last_triggered，返回是否写入成功。

    调用方必须在**确认提醒已送达**之后再调用；标记写入失败（返回 False）
    时该日程仍是未提醒状态，下轮扫描会重试——重复提醒优于永久丢失。

    幂等：已有 last_triggered 时不覆盖（防重标记一旦成立即代表"已提醒过"，
    重复调用不应把时间戳往前推；改期由同步层/工具层显式清空该字段重置）。
    """
    timestamp = (triggered_at or datetime.now()).isoformat()
    for item in await schedule_store.list_all_items(user_id):
        if item.id != item_id:
            continue
        if item.last_triggered:
            return True
        item.last_triggered = timestamp
        return await schedule_store.update_item(user_id, item)
    logger.warning(f"{LOG_PREFIX} 防重标记跳过：未找到日程 item_id={item_id}")
    return False
