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

    @filter.llm_tool(
        description="创建新日程。参数：title-日程标题/内容，datetime_str-日期时间（格式如 \"2024-01-15 14:30\" 或 \"明天 9:00\"），description-可选备注"
    )
    async def llm_create_schedule(
        self,
        event: AiocqhttpMessageEvent,
        title: str,
        datetime_str: str,
        description: str = ""
    ) -> str:
        """创建新日程

        Args:
            title: 日程标题/内容
            datetime_str: 日期时间，格式如 "2024-01-15 14:30" 或 "明天 9:00"
            description: 可选，备注描述

        Returns:
            str: 创建结果
        """
        try:
            from dateutil import parser as date_parser
            from dateutil.relativedelta import relativedelta
            
            now = datetime.now()
            dt = None
            
            if "明天" in datetime_str:
                time_part = datetime_str.replace("明天", "").strip()
                dt = now + relativedelta(days=1)
                if time_part:
                    t = datetime.strptime(time_part.replace("点", ":00").replace("：", ":"), "%H:%M")
                    dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            elif "后天" in datetime_str:
                time_part = datetime_str.replace("后天", "").strip()
                dt = now + relativedelta(days=2)
                if time_part:
                    t = datetime.strptime(time_part.replace("点", ":00").replace("：", ":"), "%H:%M")
                    dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            elif "今天" in datetime_str:
                time_part = datetime_str.replace("今天", "").strip()
                dt = now
                if time_part:
                    t = datetime.strptime(time_part.replace("点", ":00").replace("：", ":"), "%H:%M")
                    dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            else:
                dt = date_parser.parse(datetime_str)

            user_id = self._resolve_user_id(event)
            if not user_id:
                return "无法确定用户身份"

            store = getattr(self, 'store', None)
            if not store:
                return "日程存储服务未初始化"

            item = ScheduleItem(
                type="schedule",
                title=title,
                time=dt.strftime("%Y-%m-%d %H:%M"),
                context=description
            )

            await store.add_item(user_id, item)
            return f"已创建日程「{title}」，时间：{dt.strftime('%m-%d %H:%M')} ✅"
            
        except Exception as e:
            logger.error(f"创建日程失败: {e}")
            return f"创建日程失败: {e}"


class LLMDeleteSchedule(LLMScheduleToolBase):
    """删除日程工具"""

    @filter.llm_tool(
        description="删除日程。参数：schedule_id-日程ID（精确匹配）或 title_keyword-日程标题关键词（模糊匹配）"
    )
    async def llm_delete_schedule(
        self,
        event: AiocqhttpMessageEvent,
        schedule_id: str = "",
        title_keyword: str = ""
    ) -> str:
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
                return "无法确定用户身份"

            store = getattr(self, 'store', None)
            if not store:
                return "日程存储服务未初始化"

            if schedule_id:
                success = await store.remove_item(user_id, schedule_id)
                if success:
                    return f"已删除日程 ✅"
                return "未找到指定日程"

            if title_keyword:
                schedules_dict = await store.get_schedules(user_id)
                all_items = schedules_dict.get("schedules", []) + schedules_dict.get("habits", [])
                matches = [s for s in all_items if title_keyword in s.title]

                if not matches:
                    return f"没有找到包含「{title_keyword}」的日程"
                elif len(matches) == 1:
                    await store.remove_item(user_id, matches[0].id)
                    return f"已删除日程「{matches[0].title}」✅"
                else:
                    lines = ["找到多个匹配日程，请提供更具体的信息："]
                    for s in matches:
                        lines.append(f"  [{s.id}] {s.title} @ {s.time}")
                    return "\n".join(lines)

            return "请提供日程ID或标题关键词"

        except Exception as e:
            logger.error(f"删除日程失败: {e}")
            return f"删除日程失败: {e}"


class LLMListSchedules(LLMScheduleToolBase):
    """查看日程列表工具"""

    @filter.llm_tool(
        description="查看日程列表。参数：days-查看最近几天的日程，默认7天"
    )
    async def llm_list_schedules(
        self,
        event: AiocqhttpMessageEvent,
        days: int = 7
    ) -> str:
        """查看日程列表

        Args:
            days: 查看最近几天的日程，默认7天

        Returns:
            str: 日程列表
        """
        try:
            user_id = self._resolve_user_id(event)
            if not user_id:
                return "无法确定用户身份"

            store = getattr(self, 'store', None)
            if not store:
                return "日程存储服务未初始化"

            schedules_dict = await store.get_schedules(user_id)
            all_items = schedules_dict.get("schedules", []) + schedules_dict.get("habits", [])
            
            now = datetime.now()
            future = now + __import__('datetime').timedelta(days=days)
            
            # 过滤属于该用户的日程
            user_schedules = []
            for s in all_items:
                if not s.time:
                    continue
                try:
                    dt = datetime.strptime(s.time, "%Y-%m-%d %H:%M")
                    if now <= dt <= future:
                        user_schedules.append((dt, s))
                except Exception:
                    continue
            
            if not user_schedules:
                return f"最近{days}天没有日程安排~"

            # 按时间排序
            user_schedules.sort(key=lambda x: x[0])

            lines = [f"📋 接下来{days}天日程（共{len(user_schedules)}个）：", ""]
            current_date = None
            
            for dt, s in user_schedules:
                date_str = dt.strftime("%m-%d")
                
                if date_str != current_date:
                    current_date = date_str
                    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
                    lines.append(f"━━━ {date_str} {weekday} ━━━")
                
                lines.append(f"  ⏰ {dt.strftime('%H:%M')} │ {s.title}")
                if s.context:
                    lines.append(f"      📝 {s.context}")

            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"查看日程失败: {e}")
            return f"查看日程失败: {e}"


class LLMUpdateSchedule(LLMScheduleToolBase):
    """修改日程工具"""

    @filter.llm_tool(
        description="修改日程。参数：schedule_id-日程ID，title_keyword-标题关键词（用于匹配），new_title-新标题，new_datetime-新时间，new_description-新备注"
    )
    async def llm_update_schedule(
        self,
        event: AiocqhttpMessageEvent,
        schedule_id: str = "",
        title_keyword: str = "",
        new_title: str = "",
        new_datetime: str = "",
        new_description: str = ""
    ) -> str:
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
                return "无法确定用户身份"

            if not schedule_id and not title_keyword:
                return "请提供要修改的日程ID或标题关键词"

            if not new_title and not new_datetime and not new_description:
                return "请提供要修改的内容（新标题/新时间/新备注）"

            store = getattr(self, 'store', None)
            if not store:
                return "日程存储服务未初始化"

            schedules_dict = await store.get_schedules(user_id)
            all_items = schedules_dict.get("schedules", []) + schedules_dict.get("habits", [])
            
            matches = []
            for s in all_items:
                if schedule_id and s.id == schedule_id:
                    matches = [s]
                    break
                elif title_keyword and title_keyword in s.title:
                    matches.append(s)

            if not matches:
                return f"没有找到匹配的日程"

            if len(matches) > 1:
                lines = ["找到多个匹配日程，请提供更具体的信息："]
                for s in matches:
                    lines.append(f"  [{s.id}] {s.title} @ {s.time}")
                return "\n".join(lines)

            target = matches[0]
            
            # 更新字段
            if new_title:
                target.title = new_title
            if new_description:
                target.context = new_description
            if new_datetime:
                from dateutil import parser as date_parser
                dt = date_parser.parse(new_datetime)
                target.time = dt.strftime("%Y-%m-%d %H:%M")

            await store.update_item(user_id, target)
            
            changes = []
            if new_title:
                changes.append(f"标题改为「{new_title}」")
            if new_datetime:
                changes.append(f"时间改为{new_datetime}")
            if new_description:
                changes.append("备注已更新")
            
            return f"已修改日程：{', '.join(changes)} ✅"
            
        except Exception as e:
            logger.error(f"修改日程失败: {e}")
            return f"修改日程失败: {e}"
