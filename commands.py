"""
日程命令处理模块
"""

import re
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from astrbot.api.event import filter

if TYPE_CHECKING:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from .schedule_store import ScheduleItem
from .constants import LOG_PREFIX


class CommandHandler:
    """日程命令处理器"""

    def __init__(self, store, reminder_funcs: dict):
        self.store = store
        self.reminder_funcs = reminder_funcs  # {"bath": func, "sleep": func, "water": func, "briefing": func}

    async def _get_user_schedules(self, user_id: str):
        """获取用户所有日程"""
        schedules = []
        for s in (await self.store.get_schedules(user_id)).get("schedules", []):
            schedules.append(s)
        for h in (await self.store.get_schedules(user_id)).get("habits", []):
            schedules.append(h)
        return schedules

    async def handle_message(self, event: "AiocqhttpMessageEvent", user_id: str, msg_text: str) -> bool:
        """处理普通消息文本命令"""
        msg_text = msg_text.strip()
        
        # 自然语言处理
        if "添加" in msg_text or "新增" in msg_text:
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
            return await self._morning_briefing(user_id) or True
        elif msg_text == "喝水":
            return await self._water_reminder(user_id) or True
        return False

    async def handle_command(self, event: "AiocqhttpMessageEvent", user_id: str, cmd: str) -> bool:
        """处理斜杠命令"""
        cmd = cmd.strip()
        
        if cmd.startswith("/日程"):
            sub = cmd[3:].strip()
            return await self._handle_schedule_sub(event, user_id, sub)
        elif cmd == "/喝水":
            return await self._water_reminder(user_id) or True
        elif cmd in ("/早安", "/天气"):
            return await self._morning_briefing(user_id) or True
        elif cmd == "/洗澡":
            return await self._bath_reminder(user_id) or True
        elif cmd == "/睡觉":
            return await self._sleep_reminder(user_id) or True
        return False

    async def _handle_schedule_sub(self, event: "AiocqhttpMessageEvent", user_id: str, sub: str):
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
            await event.reply("未知命令，输入 /日程帮助 查看可用命令~")
            return True

    async def _handle_add(self, event: "AiocqhttpMessageEvent", user_id: str, text: str):
        """处理添加日程"""
        time_match = re.search(r'(\d{1,2})[:：时](\d{0,2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or "0")
            content = re.sub(r'(\d{1,2})[:：时](\d{0,2})', '', text).strip()
            content = content.replace("添加", "").replace("新增", "").strip()

            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                await event.reply("时间格式有误，请检查~ (小时 0-23，分钟 0-59)")
                return True

            item = ScheduleItem(
                type="schedule",
                title=content or "待办",
                time=datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M"),
            )
            await self.store.add_item(user_id, item)
            await event.reply(f"日程已添加：{content or '待办'} @ {hour:02d}:{minute:02d}")
            return True
        else:
            await event.reply("请告诉我时间哦~ 比如「添加 14:30 开会」")
            return True

    async def _handle_delete(self, event: "AiocqhttpMessageEvent", user_id: str, text: str):
        """处理删除日程"""
        idx_match = re.search(r'#?(\d+)', text)
        if idx_match:
            idx = int(idx_match.group(1)) - 1
            schedules = await self._get_user_schedules(user_id)
            if 0 <= idx < len(schedules):
                item = schedules[idx]
                await self.store.remove_item(user_id, item.id)
                await event.reply(f"已删除：{item.title}")
                return True
            else:
                await event.reply("编号超出范围~")
                return True
        else:
            await event.reply("请告诉我要删除的编号~ 比如「删除 #1」")
            return True

    async def _handle_list(self, event: "AiocqhttpMessageEvent", user_id: str):
        """处理查看日程"""
        schedules = await self._get_user_schedules(user_id)
        if not schedules:
            await event.reply("暂无日程安排，输入「添加 14:30 开会」来添加~")
            return True

        lines = ["📅 你的日程："]
        for i, item in enumerate(schedules, 1):
            time_str = item.time[:16] if item.time else "未定"
            lines.append(f"{i}. {item.title} @ {time_str}")
        await event.reply("\n".join(lines))
        return True

    async def _handle_skip(self, event: "AiocqhttpMessageEvent", user_id: str, text: str):
        """处理跳过日程"""
        idx_match = re.search(r'#?(\d+)', text)
        if idx_match:
            idx = int(idx_match.group(1)) - 1
            schedules = await self._get_user_schedules(user_id)
            if 0 <= idx < len(schedules):
                item = schedules[idx]
                await self.store.snooze_item(user_id, item.id, 60)
                await event.reply(f"已跳过 {item.title}，1小时后提醒~")
                return True
        await event.reply("请告诉我要跳过的编号~")
        return True

    async def _handle_modify_time(self, event: "AiocqhttpMessageEvent", user_id: str, text: str):
        """处理修改时间"""
        await event.reply("修改时间功能开发中~")
        return True

    async def _handle_help(self, event: "AiocqhttpMessageEvent"):
        """处理帮助命令"""
        help_text = """📋 日程助手命令：

普通模式：
  添加 14:30 开会 - 添加日程
  删除 #1 - 删除日程
  查看 - 查看所有日程
  跳过 #1 - 跳过某项
  喝水 - 手动喝水提醒

斜杠命令：
  /日程列表 - 查看日程
  /早安 - 早安播报
  /洗澡 - 洗澡提醒
  /睡觉 - 睡觉提醒
  /喝水 - 喝水提醒

快捷操作：直接输入「14:30 开会」自动添加"""
        await event.reply(help_text)
        return True

    # 快捷方法
    async def _morning_briefing(self, user_id: str):
        func = self.reminder_funcs.get("briefing")
        if func:
            await func(user_id)

    async def _water_reminder(self, user_id: str):
        func = self.reminder_funcs.get("water")
        if func:
            await func(user_id)

    async def _bath_reminder(self, user_id: str):
        func = self.reminder_funcs.get("bath")
        if func:
            await func(user_id)

    async def _sleep_reminder(self, user_id: str):
        func = self.reminder_funcs.get("sleep")
        if func:
            await func(user_id)
