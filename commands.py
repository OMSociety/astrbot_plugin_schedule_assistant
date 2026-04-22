"""
日程命令处理模块

统一处理私聊消息中的普通命令和斜杠命令。
回复统一走 MessagingService（内含三层兜底），命令路由与业务逻辑分离。

与 main.py 的分工：
- main.py：插件生命周期、定时任务调度、LLM 提醒触发
- 本模块：用户命令解析与执行、日程增删改查
"""
import re
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from .schedule_store import ScheduleItem
from .constants import SCHEDULES_KEY, LOG_PREFIX
from astrbot import logger

if TYPE_CHECKING:
    from .messaging import MessagingService
    from .schedule_store import ScheduleStore


class CommandHandler:
    """
    日程命令处理器

    负责处理私聊消息中的普通命令和斜杠命令。
    所有回复统一走 messaging.reply_to_event（含三层兜底）。
    """

    # /日程帮助 文本（避免重复定义）
    HELP_TEXT = """📌 日程小贴士使用指南

📝 添加日程：添加 14:30 开会
📋 查看日程：查看 / 日程列表
🗑️ 删除日程：删除 #1
⏭️ 跳过提醒：跳过喝水
⏰ 修改习惯时间：修改时间 喝水 10:30

💡 快捷命令：
/喝水 - 立即提醒喝水
/早安 - 生成早安播报
/洗澡 - 立即提醒洗澡
/睡觉 - 立即提醒睡觉

✨ 也可以直接用自然语言管理日程：
"帮我加个明天9点开组会"
"看看这周有什么安排"
"删除明天的读书会"
"""

    def __init__(
        self,
        store: "ScheduleStore",
        messaging: "MessagingService",
    ):
        """
        初始化命令处理器

        Args:
            store: ScheduleStore 实例（日程数据存储）
            messaging: MessagingService 实例（消息发送服务）
        """
        self.store = store
        self.messaging = messaging

    # ============ 主入口 ============

    async def handle_message(self, event: AiocqhttpMessageEvent, user_id: str, msg_text: str) -> bool:
        """
        处理普通消息文本命令

        Args:
            event: 消息事件
            user_id: 用户ID
            msg_text: 消息文本

        Returns:
            bool: 是否处理了命令（True=已消费，False=未匹配）
        """
        msg_text = msg_text.strip()

        # 斜杠命令
        if msg_text.startswith("/"):
            return await self._handle_command(event, user_id, msg_text)

        # 自然语言命令路由
        if msg_text.startswith("添加") or msg_text.startswith("新增"):
            return await self._handle_add(event, user_id, msg_text)
        elif msg_text.startswith("删除") or msg_text.startswith("取消"):
            return await self._handle_delete(event, user_id, msg_text)
        elif msg_text.startswith("查看") or msg_text.startswith("列表"):
            return await self._handle_list(event, user_id)
        elif msg_text.startswith("跳过"):
            return await self._handle_skip(event, user_id, msg_text)
        elif msg_text.startswith("修改时间"):
            return await self._handle_modify_time(event, user_id, msg_text)
        elif msg_text in ("帮助", "help"):
            return await self._handle_help(event)
        elif msg_text in ("早安", "天气"):
            return await self._handle_morning(event)
        elif msg_text == "喝水":
            return await self._handle_water(event)
        return False

    # ============ 斜杠命令路由 ============

    async def _handle_command(self, event: AiocqhttpMessageEvent, user_id: str, cmd: str) -> bool:
        """处理斜杠命令（顶层路由）"""
        cmd = cmd.strip()

        if cmd.startswith("/日程"):
            sub = cmd[3:].strip()
            return await self._handle_schedule_sub(event, user_id, sub)
        elif cmd == "/喝水":
            return await self._handle_water(event)
        elif cmd in ("/早安", "/天气"):
            return await self._handle_morning(event)
        elif cmd == "/洗澡":
            return await self._handle_bath(event)
        elif cmd == "/睡觉":
            return await self._handle_sleep(event)
        else:
            await self.messaging.reply_to_event(event, "未知命令，输入「帮助」查看可用命令~")
            return True

    async def _handle_schedule_sub(self, event: AiocqhttpMessageEvent, user_id: str, sub: str) -> bool:
        """处理 /日程 子命令"""
        if sub in ("", "列表", "查看"):
            return await self._handle_list(event, user_id)
        elif sub.startswith("添加") or sub.startswith("新增"):
            return await self._handle_add(event, user_id, sub)
        elif sub.startswith("删除") or sub.startswith("取消"):
            return await self._handle_delete(event, user_id, sub)
        elif sub.startswith("跳过"):
            return await self._handle_skip(event, user_id, sub)
        elif sub.startswith("修改时间"):
            return await self._handle_modify_time(event, user_id, sub)
        elif sub == "帮助":
            return await self._handle_help(event)
        else:
            await self.messaging.reply_to_event(event, "未知命令，输入「帮助」查看可用命令~")
            return True

    # ============ 日程 CRUD ============

    async def _handle_add(self, event: AiocqhttpMessageEvent, user_id: str, text: str) -> bool:
        """
        处理添加日程命令

        格式支持：「添加 14:30 开会」「新增 14:30开会」「14:30 开会」
        不含时间时引导用户输入。
        """
        time_match = re.search(r"(\d{1,2})[:：时](\d{0,2})", text)
        if not time_match:
            await self.messaging.reply_to_event(event, "请告诉我时间哦~ 比如「添加 14:30 开会」")
            return True

        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "0")
        content = re.sub(r"(\d{1,2})[:：时](\d{0,2})", "", text).strip()
        content = content.replace("添加", "").replace("新增", "").strip()

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await self.messaging.reply_to_event(event, "时间格式有误，请检查~ (小时 0-23，分钟 0-59)")
            return True

        item = ScheduleItem(
            type="schedule",
            title=content or "待办",
            time=datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M"),
        )
        await self.store.add_item(user_id, item)
        await self.messaging.reply_to_event(event, f"日程已添加：{content or '待办'} @ {hour:02d}:{minute:02d}")
        return True

    async def _handle_delete(self, event: AiocqhttpMessageEvent, user_id: str, text: str) -> bool:
        """处理删除日程命令，格式：「删除 #1」"""
        idx_match = re.search(r"#?(\d+)", text)
        if not idx_match:
            await self.messaging.reply_to_event(event, "请告诉我要删除的编号~ 比如「删除 #1」")
            return True

        idx = int(idx_match.group(1)) - 1
        schedules = await self._get_user_schedules(user_id)

        if not (0 <= idx < len(schedules)):
            await self.messaging.reply_to_event(event, "编号超出范围~")
            return True

        item = schedules[idx]
        await self.store.remove_item(user_id, item.id)
        await self.messaging.reply_to_event(event, f"已删除：{item.title}")
        return True

    async def _handle_list(self, event: AiocqhttpMessageEvent, user_id: str) -> bool:
        """处理查看日程命令"""
        schedules = await self._get_user_schedules(user_id)

        if not schedules:
            await self.messaging.reply_to_event(event, "暂无日程安排，输入「添加 14:30 开会」来添加~")
            return True

        lines = ["📅 你的日程："]
        for i, item in enumerate(schedules, 1):
            time_str = item.time[:16] if item.time else "未定"
            lines.append(f"{i}. {item.title} @ {time_str}")

        await self.messaging.reply_to_event(event, "\n".join(lines))
        return True

    async def _handle_skip(self, event: AiocqhttpMessageEvent, user_id: str, text: str) -> bool:
        """处理跳过提醒命令"""
        reminder_type = text.replace("跳过", "").strip()
        if reminder_type in ("喝水", "bath", "洗澡", "睡觉"):
            await self.messaging.reply_to_event(event, f"已跳过本次{reminder_type}提醒~")
        else:
            await self.messaging.reply_to_event(event, "请告诉我跳过什么~ 如「跳过喝水」")
        return True

    async def _handle_modify_time(self, event: AiocqhttpMessageEvent, user_id: str, text: str) -> bool:
        """处理修改习惯时间命令，格式：「修改时间 喝水 10:30」"""
        parts = text.replace("修改时间", "").strip().split(" ")
        if len(parts) >= 2:
            habit_name = parts[0]
            new_time = parts[1]
            success = await self.store.set_temp_override(user_id, habit_name, new_time)
            if success:
                await self.messaging.reply_to_event(event, f"已临时修改{habit_name}时间为 {new_time}~（仅今天生效）")
            else:
                await self.messaging.reply_to_event(event, "不支持的 habit 类型，支持：喝水/洗澡/睡觉")
        else:
            await self.messaging.reply_to_event(event, "格式不对哦~ 如「修改时间 喝水 10:30」")
        return True

    async def _handle_help(self, event: AiocqhttpMessageEvent) -> bool:
        """处理帮助命令"""
        await self.messaging.reply_to_event(event, self.HELP_TEXT)
        return True

    # ============ 快捷命令 Stub（由 main.py 的定时任务处理具体逻辑） ============

    async def _handle_morning(self, event: AiocqhttpMessageEvent) -> bool:
        """早安命令占位（具体逻辑在 main.py）"""
        await self.messaging.reply_to_event(event, "早安播报已生成~")
        return True

    async def _handle_water(self, event: AiocqhttpMessageEvent) -> bool:
        """喝水命令占位"""
        await self.messaging.reply_to_event(event, "喝水提醒已触发~")
        return True

    async def _handle_bath(self, event: AiocqhttpMessageEvent) -> bool:
        """洗澡命令占位"""
        await self.messaging.reply_to_event(event, "洗澡提醒已触发~")
        return True

    async def _handle_sleep(self, event: AiocqhttpMessageEvent) -> bool:
        """睡觉命令占位"""
        await self.messaging.reply_to_event(event, "睡觉提醒已触发~")
        return True

    # ============ 内部辅助方法 ============

    async def _get_user_schedules(self, user_id: str) -> List[ScheduleItem]:
        """获取用户的日程列表（仅 schedule 类型）"""
        schedules_dict = await self.store.get_schedules(user_id)
        return schedules_dict.get(SCHEDULES_KEY, [])