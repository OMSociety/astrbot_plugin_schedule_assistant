"""日程管理 LLM 工具

提供自然语言操作日程的能力：
- 创建日程
- 删除日程
- 查看日程列表
- 修改日程时间/标题
"""

from typing import Generator, Any, Optional
from datetime import datetime

from astrbot import logger
from astrbot.api.event import filter
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from ..schedule_store import ScheduleItem


def register_schedule_tools(plugin_instance) -> None:
    """注册日程管理工具到插件实例"""
    setattr(plugin_instance, 'create_schedule', LLMCreateSchedule.llm_create_schedule)
    setattr(plugin_instance, 'delete_schedule', LLMDeleteSchedule.llm_delete_schedule)
    setattr(plugin_instance, 'list_schedules', LLMListSchedules.llm_list_schedules)
    setattr(plugin_instance, 'update_schedule', LLMUpdateSchedule.llm_update_schedule)


class LLMScheduleToolBase:
    """日程工具基类"""

    @staticmethod
    def _stop_and_yield(event: AiocqhttpMessageEvent, message: str = ""):
        event.stop_event()
        if message:
            yield message
        return

    def _get_user_id(self, event: AiocqhttpMessageEvent) -> Optional[str]:
        """获取用户ID"""
        return str(event.get_user_id())

    def _get_default_user_id(self) -> Optional[str]:
        """获取默认用户ID"""
        return getattr(self, 'default_user_id', None)

    def _resolve_user_id(self, event: AiocqhttpMessageEvent) -> Optional[str]:
        """解析用户ID"""
        return self._get_user_id(event) or self._get_default_user_id()


class LLMCreateSchedule(LLMScheduleToolBase):
    """创建日程工具"""

    @filter.llm_tool()
    async def llm_create_schedule(
        self,
        event: AiocqhttpMessageEvent,
        title: str,
        datetime_str: str,
        description: str = ""
    ) -> Generator[str, Any, None]:
        """创建新日程

        Args:
            title: 日程标题/内容
            datetime_str: 日期时间，格式如 "2024-01-15 14:30" 或 "明天 9:00"
            description: 可选，备注描述

        Returns:
            str: 创建结果
        """
        try:
            # 解析日期时间
            from dateutil import parser as date_parser
            from dateutil.relativedelta import relativedelta
            
            # 尝试解析日期时间字符串
            try:
                # 处理相对时间（明天、后天等）
                now = datetime.now()
                dt = None
                
                if "明天" in datetime_str:
                    days = 1
                    time_part = datetime_str.replace("明天", "").strip()
                    dt = now + relativedelta(days=days)
                    if time_part:
                        t = datetime.strptime(time_part, "%H:%M")
                        dt = dt.replace(hour=t.hour, minute=t.minute)
                elif "后天" in datetime_str:
                    days = 2
                    time_part = datetime_str.replace("后天", "").strip()
                    dt = now + relativedelta(days=days)
                    if time_part:
                        t = datetime.strptime(time_part, "%H:%M")
                        dt = dt.replace(hour=t.hour, minute=t.minute)
                elif "今天" in datetime_str:
                    time_part = datetime_str.replace("今天", "").strip()
                    dt = now
                    if time_part:
                        t = datetime.strptime(time_part, "%H:%M")
                        dt = dt.replace(hour=t.hour, minute=t.minute)
                else:
                    dt = date_parser.parse(datetime_str)
                    
            except Exception as e:
                logger.error(f"日期解析失败: {e}")
                event.stop_event()
                yield f"日期时间格式不支持，请使用标准格式如 '2024-01-15 14:30' 或 '明天 9:00'"
                return

            user_id = self._resolve_user_id(event)
            if not user_id:
                event.stop_event()
                yield "无法确定用户身份"
                return

            # 调用 store 创建
            store = getattr(self, 'store', None)
            if not store:
                event.stop_event()
                yield "日程存储服务未初始化"
                return

            item = ScheduleItem(
                id="",  # 会自动生成
                title=title,
                description=description,
                remind_time=dt.isoformat(),
                remind_before=0,
                user_id=user_id,
                created_at=datetime.now().isoformat()
            )

            schedule_id = await store.add(item)
            
            event.stop_event()
            yield f"已创建日程「{title}」，时间：{dt.strftime('%m-%d %H:%M')} ✅"
            
        except Exception as e:
            logger.error(f"创建日程失败: {e}")
            event.stop_event()
            yield f"创建日程失败: {e}"


class LLMDeleteSchedule(LLMScheduleToolBase):
    """删除日程工具"""

    @filter.llm_tool()
    async def llm_delete_schedule(
        self,
        event: AiocqhttpMessageEvent,
        schedule_id: str = "",
        title_keyword: str = ""
    ) -> Generator[str, Any, None]:
        """删除日程

        Args:
            schedule_id: 日程ID（精确匹配）
            title_keyword: 日程标题关键词（模糊匹配）

        Returns:
            str: 删除结果
        """
        try:
            user_id = self._resolve_user_id(event)
            if not user_id:
                event.stop_event()
                yield "无法确定用户身份"
                return

            store = getattr(self, 'store', None)
            if not store:
                event.stop_event()
                yield "日程存储服务未初始化"
                return

            deleted = False
            
            if schedule_id:
                # 通过ID删除
                schedules = await store.get_all()
                for s in schedules:
                    if s.id == schedule_id:
                        await store.delete(schedule_id)
                        deleted = True
                        break
                        
            elif title_keyword:
                # 通过关键词删除
                schedules = await store.get_all()
                matches = [s for s in schedules if title_keyword in s.title]
                
                if not matches:
                    event.stop_event()
                    yield f"没有找到包含「{title_keyword}」的日程"
                    return
                elif len(matches) == 1:
                    await store.delete(matches[0].id)
                    deleted = True
                else:
                    # 多个匹配，列出让用户确认
                    lines = ["找到多个匹配日程，请提供更具体的信息："]
                    for s in matches:
                        dt = datetime.fromisoformat(s.remind_time)
                        lines.append(f"  [{s.id}] {s.title} - {dt.strftime('%m-%d %H:%M')}")
                    event.stop_event()
                    yield "\n".join(lines)
                    return
            else:
                event.stop_event()
                yield "请提供日程ID或标题关键词"
                return

            if deleted:
                event.stop_event()
                yield f"已删除日程 ✅"
            else:
                event.stop_event()
                yield "未找到指定日程"
                
        except Exception as e:
            logger.error(f"删除日程失败: {e}")
            event.stop_event()
            yield f"删除日程失败: {e}"


class LLMListSchedules(LLMScheduleToolBase):
    """查看日程列表工具"""

    @filter.llm_tool()
    async def llm_list_schedules(
        self,
        event: AiocqhttpMessageEvent,
        days: int = 7
    ) -> Generator[str, Any, None]:
        """查看日程列表

        Args:
            days: 查看最近几天的日程，默认7天

        Returns:
            str: 日程列表
        """
        try:
            user_id = self._resolve_user_id(event)
            if not user_id:
                event.stop_event()
                yield "无法确定用户身份"
                return

            store = getattr(self, 'store', None)
            if not store:
                event.stop_event()
                yield "日程存储服务未初始化"
                return

            all_schedules = await store.get_all()
            now = datetime.now()
            future = now + __import__('datetime').timedelta(days=days)
            
            # 过滤属于该用户的日程
            user_schedules = [
                s for s in all_schedules 
                if s.user_id == user_id and 
                datetime.fromisoformat(s.remind_time) <= future
            ]
            
            if not user_schedules:
                event.stop_event()
                yield f"最近{days}天没有日程安排~"
                return

            # 按时间排序
            user_schedules.sort(key=lambda s: s.remind_time)

            lines = [f"📋 接下来{days}天日程（共{len(user_schedules)}个）：", ""]
            current_date = None
            
            for s in user_schedules:
                dt = datetime.fromisoformat(s.remind_time)
                date_str = dt.strftime("%m-%d")
                
                if date_str != current_date:
                    current_date = date_str
                    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
                    lines.append(f"━━━ {date_str} {weekday} ━━━")
                
                lines.append(f"  ⏰ {dt.strftime('%H:%M')} │ {s.title}")
                if s.description:
                    lines.append(f"      📝 {s.description}")

            event.stop_event()
            yield "\n".join(lines)
            
        except Exception as e:
            logger.error(f"查看日程失败: {e}")
            event.stop_event()
            yield f"查看日程失败: {e}"


class LLMUpdateSchedule(LLMScheduleToolBase):
    """修改日程工具"""

    @filter.llm_tool()
    async def llm_update_schedule(
        self,
        event: AiocqhttpMessageEvent,
        schedule_id: str = "",
        title_keyword: str = "",
        new_title: str = "",
        new_datetime: str = "",
        new_description: str = ""
    ) -> Generator[str, Any, None]:
        """修改日程

        Args:
            schedule_id: 日程ID（精确匹配）
            title_keyword: 日程标题关键词（模糊匹配）
            new_title: 新标题
            new_datetime: 新时间，格式如 "2024-01-15 14:30"
            new_description: 新备注

        Returns:
            str: 修改结果
        """
        try:
            user_id = self._resolve_user_id(event)
            if not user_id:
                event.stop_event()
                yield "无法确定用户身份"
                return

            if not schedule_id and not title_keyword:
                event.stop_event()
                yield "请提供要修改的日程ID或标题关键词"
                return

            if not new_title and not new_datetime and not new_description:
                event.stop_event()
                yield "请提供要修改的内容（新标题/新时间/新备注）"
                return

            store = getattr(self, 'store', None)
            if not store:
                event.stop_event()
                yield "日程存储服务未初始化"
                return

            all_schedules = await store.get_all()
            matches = []
            
            for s in all_schedules:
                if s.user_id == user_id:
                    if schedule_id and s.id == schedule_id:
                        matches = [s]
                        break
                    elif title_keyword and title_keyword in s.title:
                        matches.append(s)

            if not matches:
                event.stop_event()
                keyword = schedule_id or title_keyword
                yield f"没有找到包含「{keyword}」的日程"
                return
            elif len(matches) > 1:
                lines = ["找到多个匹配日程，请提供更具体的信息："]
                for s in matches:
                    dt = datetime.fromisoformat(s.remind_time)
                    lines.append(f"  [{s.id}] {s.title} - {dt.strftime('%m-%d %H:%M')}")
                event.stop_event()
                yield "\n".join(lines)
                return

            target = matches[0]
            
            # 更新字段
            if new_title:
                target.title = new_title
            if new_description:
                target.description = new_description
            if new_datetime:
                from dateutil import parser as date_parser
                try:
                    dt = date_parser.parse(new_datetime)
                    target.remind_time = dt.isoformat()
                except Exception:
                    event.stop_event()
                    yield f"日期时间格式不支持：{new_datetime}"
                    return

            await store.update(target)
            
            changes = []
            if new_title:
                changes.append(f"标题改为「{new_title}」")
            if new_datetime:
                changes.append(f"时间改为{datetime.fromisoformat(target.remind_time).strftime('%m-%d %H:%M')}")
            if new_description:
                changes.append("备注已更新")
            
            event.stop_event()
            yield f"已修改日程：{', '.join(changes)} ✅"
            
        except Exception as e:
            logger.error(f"修改日程失败: {e}")
            event.stop_event()
            yield f"修改日程失败: {e}"
