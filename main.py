"""
Schedule Assistant Plugin

Intelligent Schedule Assistant,支持自然语言创建日程,定时habit reminders,结合Live Dashboard
状态智能生成提醒,上下午感知提醒,私聊定向推送等功能.

版本: v1.2.0
作者: Slandre & Flandre
"""

import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Generator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot import logger
from astrbot.api.star import Star, Context
from astrbot.api.event import filter
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.platform import MessageType

from astrbot.core.provider.entities import ProviderType
from .schedule_store import ScheduleStore, ScheduleItem
from .notion_client import NotionClient, notion_get_pending_async
from .apple_calendar import AppleCalendar
from .constants import (
    LOG_PREFIX, 
    DEFAULT_BATH_TIME, 
    DEFAULT_SLEEP_TIME,
    DEFAULT_WATER_START,
    DEFAULT_WATER_END,
    DEFAULT_WATER_INTERVAL
)


class ScheduleAssistant(Star):
    """Main class for Schedule Assistant
    
    Provides schedule management,habit reminders,intelligent morning reports.
    Uses AstrBot Preference API for data persistence.
    """

    @staticmethod
    def _get_water_next_trigger(now: datetime, water_start: str, water_end: str, interval: int) -> datetime:
        """Calculate the next water reminder trigger time

        Rules:
        1. If within water hours --> find next interval-minute cycle
        2. If before start time --> wait for start_time
        3. If after end time --> wait for tomorrow start_time
        """
        start_h, start_m = map(int, water_start.split(":"))
        end_h, end_m = map(int, water_end.split(":"))
        
        start_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end_time = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        
        # 情况3:已过结束时间 --> 明天开始
        if now > end_time:
            return start_time + timedelta(days=1)
        
        # 情况2:未到开始时间 --> 等开始
        if now < start_time:
            return start_time
        
        # 情况1:在水时段内,找下一个interval分钟周期的整点
        current = start_time
        while current <= now:
            current += timedelta(minutes=interval)
        
        # 如果算出的时间超过了 end_time,说明今天没下次了,等明天
        if current > end_time:
            return start_time + timedelta(days=1)
        
        return current

    def __init__(self, context: Context, config: dict = None):
        """Initialize ScheduleAssistant
        
        Args:
            context: AstrBot 上下文
            config: 插件配置字典(从 AstrBot 配置系统传入)
        """
        super().__init__(context)
        
        # 配置必须最先初始化，后续代码依赖 self.config
        self.config = config or {}
        
        # 使用 AstrBot Storage API 替代本地 JSON
        self.store = ScheduleStore(context)
        
        # Notion 客户端（配置统一从 AstrBot 传入）
        self.notion = NotionClient(
            api_key=self.config.get("maton_api_key", ""),
            transaction_db_id=self.config.get("transaction_db_id", ""),
            reading_db_id=self.config.get("reading_db_id", "")
        )
        
        # Apple 日历客户端(可选)
        self.calendar = None
        if self.config.get("apple_calendar_enabled", False):
            self.calendar = AppleCalendar(
                username=self.config.get("apple_id"),
                app_password=self.config.get("apple_app_password"),
                webcal_urls=self.config.get("webcal_urls", [])
            )
        
        # 定时任务调度器
        self.scheduler = AsyncIOScheduler()
        
        # 防重入锁 - 防止任务重复触发
        self._water_reminder_running = False
        
        # 从配置读取用户设置
        self.default_user_id = self.config.get("default_user_id", "") or                         (self.config.get("whitelist_qq_ids", [""])[0] if self.config.get("whitelist_qq_ids") else "")
        self.default_username = ""  # 从QQ API获取，获取不到用「用户」
        
        # 在 __init__ 中直接注册定时任务
        self._register_jobs()
        
        logger.info(f"{LOG_PREFIX} 插件初始化完成,定时任务已注册")

    def _register_jobs(self):
        """注册所有定时任务
        
        包括:早安播报,洗澡提醒,睡觉提醒,喝水提醒,Notion DDL检查
        """
        try:
            # Morning briefing at 9:00
            morning_report_time = self.config.get("morning_report_time", "09:00")
            morning_hour, morning_minute = map(int, morning_report_time.split(":"))
            self.scheduler.add_job(
                self._morning_briefing,
                CronTrigger(hour=morning_hour, minute=morning_minute),
                id="morning_briefing",
                replace_existing=True
            )
            
            # Bath reminder
            bath_time = self.config.get("bath_time", DEFAULT_BATH_TIME)
            bath_hour, bath_minute = map(int, bath_time.split(":"))
            self.scheduler.add_job(
                self._bath_reminder,
                CronTrigger(hour=bath_hour, minute=bath_minute),
                id="bath_reminder",
                replace_existing=True
            )
            
            # Sleep reminder
            sleep_time = self.config.get("sleep_time", DEFAULT_SLEEP_TIME)
            sleep_hour, sleep_minute = map(int, sleep_time.split(":"))
            self.scheduler.add_job(
                self._sleep_reminder,
                CronTrigger(hour=sleep_hour, minute=sleep_minute),
                id="sleep_reminder",
                replace_existing=True
            )
            
            # Water reminder - 智能计算首次触发时间
            water_start = self.config.get("water_start_time", DEFAULT_WATER_START)
            water_end = self.config.get("water_end_time", DEFAULT_WATER_END)
            water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
            
            # 使用辅助函数计算下次触发时间(支持重载时立即触发)
            now = datetime.now()
            next_trigger = self._get_water_next_trigger(now, water_start, water_end, water_interval)
            initial_delay = (next_trigger - now).total_seconds()
            
            self.scheduler.add_job(
                self._water_reminder,
                "date",
                run_date=datetime.now() + timedelta(seconds=initial_delay),
                id="water_reminder",
                replace_existing=True
            )
            logger.info(f"{LOG_PREFIX} 喝水提醒首次触发: {next_trigger.strftime('%H:%M')} ({initial_delay/60:.1f}分钟后)")
            
            # 每小时检查一次 Notion DDL
            self.scheduler.add_job(
                self._notion_ddl_check,
                CronTrigger(minute=0),  # 每小时整点
                id="notion_ddl_check",
                replace_existing=True
            )
            
            # 每天凌晨清理过期的临时修改(00:05执行,避开0点高峰)
            self.scheduler.add_job(
                self._clear_expired_overrides,
                CronTrigger(hour=0, minute=5),
                id="clear_expired_overrides",
                replace_existing=True
            )
            
            # 立即启动 scheduler
            if not self.scheduler.running:
                self.scheduler.start()
            
            logger.info(f"{LOG_PREFIX} 所有定时任务已注册,调度器已启动")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 定时任务注册失败: {e}")

    async def on_load(self):
        """插件加载回调(AstrBot 生命周期)"""
        logger.info(f"{LOG_PREFIX} 插件加载完成")

    async def on_unload(self):
        """插件卸载/重启时清理 scheduler
        
        确保所有定时任务正确停止,避免资源泄漏.
        """
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                logger.info(f"{LOG_PREFIX} 调度器已停止")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 调度器停止失败: {e}")

    # ==================== 定时任务回调 ====================
    
    async def _morning_briefing(self):
        """
        早安播报任务
        
        每天早上 9:00 自动推送综合日程简报，所有内容由LLM生成。
        """
        try:
            now = datetime.now()
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            user_id = self.default_user_id
            # 自动从白名单获取用户名
            if not self.default_username:
                username = await self._get_username_from_qq(user_id)
            else:
                username = self.default_username
            
            # ========== 并发获取所有数据 ==========
            weather_task = self._fetch_weather()
            calendar_task = self._fetch_calendar_events()
            schedule_task = self._fetch_local_schedules(user_id)
            notion_task = self._fetch_notion_pending()
            
            # 同时获取Dashboard状态
            from .dashboard import get_dashboard_status
            dashboard = await get_dashboard_status()
            
            # 使用asyncio.gather并发执行
            weather_result, calendar_info, schedule_info, notion_info = await asyncio.gather(
                weather_task, calendar_task, schedule_task, notion_task,
                return_exceptions=True
            )
            
            # 处理异常
            if isinstance(weather_result, Exception):
                weather_current, weather_forecast = "获取失败", ""
            else:
                weather_current, weather_forecast = weather_result
            
            if isinstance(calendar_info, Exception):
                calendar_info = "获取失败"
            if isinstance(schedule_info, Exception):
                schedule_info = "获取失败"
            if isinstance(notion_info, Exception):
                notion_info = "获取失败"
            
            # ========== LLM 生成完整播报 ==========
            full_report = await self._generate_full_morning_report(
                username=username,
                date=now.strftime('%Y-%m-%d'),
                weekday=weekdays[now.weekday()],
                weather_current=weather_current,
                weather_forecast=weather_forecast,
                calendar=calendar_info,
                schedules=schedule_info,
                notion=notion_info,
                dashboard=dashboard
            )
            
            await self._send_to_user(user_id, full_report)
            logger.info(f"{LOG_PREFIX} 早安播报已发送")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 早安播报失败: {e}")


    async def _get_username_from_qq(self, user_id: str) -> str:
        """
        根据用户ID获取QQ昵称
        
        Args:
            user_id: QQ号
            
        Returns:
            用户昵称，获取失败则返回原ID
        """
        try:
            # 通过 platform_manager 获取用户信息
            for platform in self.context.platform_manager.platform_insts:
                try:
                    # 尝试获取陌生人信息
                    info = await platform.bot.call_action(
                        action="get_stranger_info",
                        user_id=int(user_id),
                        no_cache=True
                    )
                    if info and info.get("nickname"):
                        return info.get("nickname", user_id)
                    elif info and info.get("nick"):
                        return info.get("nick", user_id)
                except Exception:
                    pass
            return user_id
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 获取用户 {user_id} 昵称失败: {e}")
            return user_id

    async def _fetch_weather(self) -> tuple[str, str]:
        """获取天气信息
        
        Returns:
            (当前天气, 预报信息)
        """
        weather_api_key = self.config.get("weather_api_key", "")
        weather_city = self.config.get("weather_city", "北京")
        
        weather_current = ""
        weather_forecast = ""
        
        if not weather_api_key:
            return "未配置天气API", ""
        
        try:
            async with aiohttp.ClientSession() as session:
                # 获取当前天气
                now_url = "https://api.seniverse.com/v3/weather/now.json"
                now_params = {
                    "key": weather_api_key, 
                    "location": weather_city, 
                    "language": "zh-Hans", 
                    "unit": "c"
                }
                async with session.get(now_url, params=now_params, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            now_weather = results[0].get("now", {})
                            weather_current = f"{now_weather.get('text', '未知')}, {now_weather.get('temperature', '?')}°C"
                
                # 获取今日预报
                daily_url = "https://api.seniverse.com/v3/weather/daily.json"
                daily_params = {
                    "key": weather_api_key, 
                    "location": weather_city, 
                    "language": "zh-Hans", 
                    "unit": "c"
                }
                async with session.get(daily_url, params=daily_params, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            daily = results[0].get("daily", [])
                            if daily:
                                today = daily[0]
                                day_text = today.get("text_day", "未知")
                                night_text = today.get("text_night", "未知")
                                high = today.get("high", "?")
                                low = today.get("low", "?")
                                rain_prob = today.get("precip", "0")
                                weather_forecast = f"白天{day_text} / 夜间{night_text}, {low}~{high}°C, 降水概率{rain_prob}%"
        except asyncio.TimeoutError:
            logger.warning(f"{LOG_PREFIX} 天气API请求超时")
            weather_current = "获取超时"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 天气获取失败: {e}")
            weather_current = "获取失败"
        
        return weather_current, weather_forecast

    async def _fetch_calendar_events(self) -> str:
        """获取日历事件
        
        Returns:
            格式化的事件列表字符串
        """
        if not self.calendar:
            return "未启用日历同步"
        
        try:
            events = self.calendar.get_all_events(days=1)
            if events:
                return "\n".join([f"{e['start'][11:16] if len(e['start']) > 11 else ''} {e['summary']}" 
                                 for e in events[:5]])
            return "暂无日历事件"
        except asyncio.TimeoutError:
            logger.warning(f"{LOG_PREFIX} 日历获取超时")
            return "日历获取超时"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 日历获取失败: {e}")
            return "日历获取失败"

    async def _fetch_local_schedules(self, user_id: str) -> str:
        """获取本地日程
        
        Args:
            user_id: 用户ID
            
        Returns:
            格式化的日程列表字符串
        """
        try:
            items = await self.store.list_all_items(user_id)
            today_items = [i for i in items if i.type == "schedule"]
            if today_items:
                return "\n".join([f"{i.time} {i.title}" for i in today_items[:5]])
            return "暂无日程"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 本地日程获取失败: {e}")
            return "获取失败"

    async def _fetch_notion_pending(self) -> str:
        """获取 Notion 待办
        
        Returns:
            格式化的待办列表字符串
        """
        try:
            pending = await self.notion.get_pending_transactions()
            if pending:
                return "\n".join([f"- {t['title']} ({t['status']})" for t in pending[:5]])
            return "暂无待办"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Notion 获取失败: {e}")
            return "获取失败"

    async def _generate_full_morning_report(
        self,
        username: str,
        date: str,
        weekday: str,
        weather_current: str,
        weather_forecast: str,
        calendar: str,
        schedules: str,
        notion: str,
        dashboard: str = ""
    ) -> str:
        """
        使用LLM生成完整的早安播报。
        
        自动获取当前人格配置，保持Bot的人设一致性。
        LLM会根据人格自己生成包含称呼语的早安语。
        """
        try:
            # 使用默认对话模型
            try:
                provider = self.context.provider_manager.get_using_provider(ProviderType.CHAT_COMPLETION)
                if not provider:
                    logger.error(f"{LOG_PREFIX} 未配置默认LLM Provider")
                    return ""
                provider_id = provider.meta().id
            except Exception as e:
                logger.error(f"{LOG_PREFIX} 获取默认模型失败: {e}")
                return ""
            
            # 自动获取当前人格的system prompt
            try:
                persona = await self.context.persona_manager.get_default_persona_v3()
                system_prompt = persona.get('prompt', '') if isinstance(persona, dict) else getattr(persona, 'prompt', '') if persona else ""
            except Exception:
                system_prompt = ""
            
            # 格式化日历事件
            calendar_lines = []
            if calendar and calendar != "暂无" and calendar != "获取失败":
                for line in calendar.split('\n'):
                    if line.strip():
                        calendar_lines.append(line.strip().replace("|", " "))
            
            # 格式化待办
            notion_lines = []
            if notion and notion != "暂无" and notion != "获取失败":
                for line in notion.split('\n'):
                    if line.strip():
                        notion_lines.append(line.strip())
            
            user_prompt = f"""你的人格设定（由系统提供）会决定你的说话风格。

【你的任务】
请以符合人格风格的方式，生成一份完整的早安播报。要求：
1. 开头必须有称呼语（如"早安xxx~"），称呼要自然融入
2. 结合用户当前状态（如昨晚熬夜、在游戏中等等）给出针对性建议
3. 语言要符合你的人设，不要生硬

【今日信息】
日期: {date} {weekday}
天气: {weather_current}（预报: {weather_forecast if weather_forecast else "暂无"}）
日程:
{chr(10).join(calendar_lines) if calendar_lines else "暂无"}
待办:
{schedules if schedules and schedules != "暂无" else "暂无"}
Notion待办:
{chr(10).join(notion_lines) if notion_lines else "暂无"}
设备状态: {dashboard if dashboard else "暂无"}

【温馨建议生成规则】
这部分最重要！需要结合设备状态和个人数据生成：
- 如果设备显示熬夜到很晚，建议今天早点睡
- 如果设备显示用户还在床上或游戏中，温和温和催促开始新的一天
- 如果有DDL临近的待办，重点提醒
- 如果天气不好，提醒带伞添衣
- 建议要有针对性，不要泛泛而谈

【格式要求】
按以下格式生成（空数据则省略该行）：
（早安语，称呼+简短问候）
日期
天气（当前+预报；emoji根据天气自动选☀️🌧️⛅等）
日程（如有，每一项单独一行，用换行符分隔）
待办（如有）
温馨建议（一段以内）

【输出范例】
🌅 2026-04-09 周四
🌧 当前15°C下着小雨，今日气温8-14°C，白天会转晴，夜间转小雨（降水概率55%）

📋 今日日程
─────────────
⏰ 09:45 │ 早会
⏰ 14:00 │ 西方哲学史

📌 待办提醒
─────────────
🔥 还剩2天 │ 论文初稿截止（4月11日）
📅 还剩4天 │ 季度报告（4月13日）

🫕 温馨提示
今天有雨记得带伞~昨晚设备显示你2点才睡，中午记得眯一会儿补补觉🥺论文的DDL还剩2天，加油~
"""
            
            resp = await self.context.llm_generate(
                prompt=user_prompt,
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                stream=False
            )
            
            # 提取文本内容
            if hasattr(resp, 'completion_text'):
                return resp.completion_text.strip()
            elif hasattr(resp, 'text'):
                return resp.text.strip()
            elif isinstance(resp, str):
                return resp.strip()
            else:
                return str(resp).strip()
                
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} LLM生成失败，回退到默认格式: {e}")
            # 失败时回退
            return f"今日{date} {weekday}，{weather_current}。{schedules}。{notion}"


    async def _bath_reminder(self):
        """洗澡提醒任务
        
        结合 Live Dashboard 状态,使用 LLM 生成个性化提醒.
        """
        try:
            user_id = self.default_user_id
            if not self.config.get("enable_bath_reminder", True):
                return
            
            from .dashboard import get_dashboard_status
            dashboard = await get_dashboard_status()
            username = await self._get_username_from_qq(user_id) or "用户"
            
            prompt = f"""你是「{username}」的贴心日程助手，现在需要生成一条洗澡时间提醒~

【用户信息】
- 用户名: {username}
- 当前时间: {datetime.now().strftime("%H:%M")}
- 设定的洗澡时间: {self.config.get("bath_time", DEFAULT_BATH_TIME)}
- 用户当前状态: {dashboard}

【生成要求】
1. 语气活泼可爱，像朋友催你去洗澡
2. 如果 dashboard 显示用户刚运动/干活了，可以调侃"该洗掉汗味啦"
3. 40字以内，带1-2个emoji
4. 不要markdown，纯文本输出
5. 只输出提醒消息本身"""

            message = await self._generate_llm_message(prompt)
            if message:
                await self._send_to_user(user_id, message)
            else:
                logger.warning(f"{LOG_PREFIX} 洗澡提醒消息为空，跳过发送")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 洗澡提醒失败: {e}")

    async def _sleep_reminder(self):
        """睡觉提醒任务
        
        结合当前时间和 Dashboard 状态生成提醒,超过 23:30 会带"吐槽".
        """
        try:
            user_id = self.default_user_id
            if not self.config.get("enable_sleep_reminder", True):
                return
            
            from .dashboard import get_dashboard_status
            dashboard = await get_dashboard_status()
            username = await self._get_username_from_qq(user_id) or "用户"
            
            now = datetime.now()
            is_late = now.hour >= 23 or now.hour < 2
            
            prompt = f"""你是「{username}」的贴心日程助手，现在需要生成一条睡觉时间提醒~

【用户信息】
- 用户名: {username}
- 当前时间: {now.strftime("%H:%M")}
- 设定的睡觉时间: {self.config.get("sleep_time", DEFAULT_SLEEP_TIME)}
- 是否已超晚(23点后): {is_late}
- 用户当前状态: {dashboard}

【生成要求】
1. 如果已经超晚23点，语气要带点小责备，比如"都几点了还不睡！"
2. 如果还没很晚，语气温柔催促
3. 结合 dashboard 状态：如果显示还在熬夜/游戏，要重点催睡
4. 40字以内，带1-2个emoji
5. 不要markdown，纯文本输出
6. 只输出提醒消息本身"""
            
            message = await self._generate_llm_message(prompt)
            if message:
                await self._send_to_user(user_id, message)
            else:
                logger.warning(f"{LOG_PREFIX} 睡觉提醒消息为空，跳过发送")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 睡觉提醒失败: {e}")

    async def _water_reminder(self):
        """喝水提醒任务"""
        # 防重入检查
        if self._water_reminder_running:
            logger.warning(f"{LOG_PREFIX} 喝水提醒正在执行中，跳过本次触发")
            return
        self._water_reminder_running = True
        
        try:
            user_id = self.default_user_id
            if not self.config.get("enable_water_reminder", True):
                return
            
            from .dashboard import get_dashboard_status
            dashboard = await get_dashboard_status()
            username = await self._get_username_from_qq(user_id) or "用户"
            
            now = datetime.now()
            water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
            
            prompt = f"""你是「{username}」的贴心日程助手，现在需要生成一条喝水提醒~

【用户信息】
- 用户名: {username}
- 当前时间: {now.strftime("%H:%M")}
- 距离上次喝水: {water_interval}分钟
- 用户当前状态: {dashboard}

【生成要求】
1. 语气活泼俏皮，像闺蜜催你喝水
2. 可以调侃"皮肤要变干咯"、"脑子要变笨咯"之类的
3. 如果 dashboard 显示用户刚运动完，强调要多喝水
4. 30字以内，带1-2个emoji
5. 不要markdown，纯文本输出
6. 只输出提醒消息本身"""
            
            message = await self._generate_llm_message(prompt)
            if message:
                await self._send_to_user(user_id, message)
                logger.info(f"{LOG_PREFIX} 喝水提醒已发送: {message[:30]}...")
            else:
                logger.warning(f"{LOG_PREFIX} 喝水提醒消息生成失败，跳过发送")
            
            # 自动重新调度下一次喝水提醒
            water_start = self.config.get("water_start_time", DEFAULT_WATER_START)
            water_end = self.config.get("water_end_time", DEFAULT_WATER_END)
            water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
            next_trigger = self._get_water_next_trigger(datetime.now(), water_start, water_end, water_interval)
            self.scheduler.add_job(
                self._water_reminder,
                "date",
                run_date=next_trigger,
                id="water_reminder",
                replace_existing=True
            )
            logger.info(f"{LOG_PREFIX} 喝水提醒已续期，下次触发: {next_trigger.strftime('%H:%M')}")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 喝水提醒失败: {e}")
        finally:
            # 释放防重入锁
            self._water_reminder_running = False

    async def _notion_ddl_check(self):
        """Notion DDL 检查任务
        
        每小时检查一次即将到期的 Notion 任务.
        """
        try:
            if not self.notion:
                return
            tasks = await notion_get_pending_async()
            now = datetime.now()
            
            for task in tasks:
                # 检查是否快到期(24小时内)
                due = task.get('ddl')
                if due:
                    try:
                        due_date = datetime.fromisoformat(due.replace('Z', '+00:00'))
                        due_date_local = due_date.astimezone().replace(tzinfo=None)
                        diff = (due_date_local - now).total_seconds()
                        if 0 < diff < 86400:  # 24小时内
                            title = task.get('title', '未命名任务')
                            logger.info(f"{LOG_PREFIX} DDL提醒: {title} 将在 {diff/3600:.1f} 小时后到期")
                    except Exception as e:
                        logger.debug(f"{LOG_PREFIX} 解析任务截止日期失败: {e}")
                        
        except Exception as e:
            logger.error(f"{LOG_PREFIX} DDL检查失败: {e}")

    async def _clear_expired_overrides(self):
        """每日清理过期的临时修改
        
        在凌晨00:05执行,清理所有习惯的过期temp_override.
        """
        try:
            user_id = self.default_user_id
            if user_id:
                await self.store.clear_expired_overrides(user_id)
                logger.info(f"{LOG_PREFIX} 已清理过期的临时修改")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 清理过期临时修改失败: {e}")

    async def _generate_llm_message(self, prompt: str, use_persona: bool = True) -> str:
        """使用 LLM 生成消息
        
        Args:
            prompt: 提示词
            use_persona: 是否使用人格注入
            
        Returns:
            LLM 生成的文本
        """
        try:
            # 使用默认对话模型
            try:
                provider = self.context.provider_manager.get_using_provider(ProviderType.CHAT_COMPLETION)
                if not provider:
                    logger.error(f"{LOG_PREFIX} 未配置默认LLM Provider")
                    return ""  # 返回空字符串，避免错误信息出现在聊天
                provider_id = provider.meta().id
            except Exception as e:
                logger.error(f"{LOG_PREFIX} 获取默认模型失败: {e}")
                return ""  # 返回空字符串，避免错误信息出现在聊天
            
            # 获取人格 system_prompt
            system_prompt = ""
            if use_persona:
                try:
                    persona = await self.context.persona_manager.get_default_persona_v3()
                    system_prompt = persona.get('prompt', '') if isinstance(persona, dict) else getattr(persona, 'prompt', '') if persona else ""
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} 获取人格失败: {e}")
            
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=system_prompt if system_prompt else None
            )
            return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"{LOG_PREFIX} LLM 生成失败: {e}")
            return ""  # 返回空字符串，避免错误信息出现在聊天

    def _get_platform_id(self) -> str:
        """获取平台 ID
        
        Returns:
            平台标识符
        """
        try:
            for platform in self.context.platform_manager.platform_insts:
                return platform.meta().id
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 获取平台ID失败: {e}")
        return "aiocqhttp"

    async def _send_to_user(self, user_id: str, message: str):
        """发送私聊消息给用户
        
        Args:
            user_id: 用户ID
            message: 消息内容
        """
        try:
            # 检查白名单
            allowed = self.config.get("whitelist_qq_ids", [])
            
            if user_id not in allowed:
                logger.warning(f"{LOG_PREFIX} 用户 {user_id} 不在白名单,跳过发送")
                return
            
            from astrbot.core.platform.message_session import MessageSession
            
            session = MessageSession(
                platform_name=self._get_platform_id(),
                message_type=MessageType.FRIEND_MESSAGE,
                session_id=user_id
            )
            
            from astrbot.api.event import MessageChain
            chain = MessageChain().message(message)
            await self.context.send_message(session, chain)
            logger.info(f"{LOG_PREFIX} 消息已发送给用户 {user_id}")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息失败: {e}")

    # ==================== LLM Tools ====================
    
    @filter.llm_tool(
        name="add_schedule",
        description="添加新的日程或习惯。参数：title-日程名称，time-执行时间(HH:MM)，recur-重复周期(daily/weekly/monthly，空则单次)，description-描述(可选)"
    )
    async def add_schedule_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        title: str, 
        time: str, 
        recur: Optional[str] = None, 
        description: str = ""
    ) -> Generator[str, Any, None]:
        """添加日程或习惯
        
        Args:
            title (str): 日程/习惯的名称
            time (str): 执行时间,格式为 HH:MM,such as "09:00"
            recur (str, optional): 重复周期,可选值: daily, weekly, monthly,空字符串表示不重复
            description (str, optional): 日程描述
        """
        user_id = str(event.sender_info.user_id)
        
        item = ScheduleItem(
            type="habit" if recur else "schedule",
            title=title,
            time=time,
            recur=recur,
            context=description
        )
        
        await self.store.add_item(user_id, item)
        
        recur_text = ""
        if recur == "daily":
            recur_text = ",每天重复"
        elif recur == "weekly":
            recur_text = ",每周重复"
        
        yield event.plain_result(f"已添加: {title} @ {time}{recur_text}")

    @filter.llm_tool(
        name="remove_schedule",
        description="删除指定的日程或习惯。支持模糊匹配，传入日程名称即可删除"
    )
    async def remove_schedule_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        title: str
    ) -> Generator[str, Any, None]:
        """删除日程或习惯
        
        Args:
            title (str): 要删除的日程/习惯名称(支持模糊匹配)
        """
        user_id = str(event.sender_info.user_id)
        items = await self.store.list_all_items(user_id)
        
        for item in items:
            if title.lower() in item.title.lower():
                if await self.store.remove_item(user_id, item.id):
                    yield event.plain_result(f"已删除: {item.title}")
                    return
        
        yield event.plain_result(f"未找到: {title}")

    @filter.llm_tool(
        name="list_schedules",
        description="查看用户当前所有的日程和习惯列表，包括执行时间和重复周期"
    )
    async def list_schedules_llm(self, event: AiocqhttpMessageEvent) -> Generator[str, Any, None]:
        """查看所有日程和习惯列表
        """
        user_id = str(event.sender_info.user_id)
        items = await self.store.list_all_items(user_id)
        
        if not items:
            yield event.plain_result("暂无日程")
            return
        
        lines = ["📅 日程列表:"]
        for item in items:
            recur_text = ""
            if item.recur == "daily":
                recur_text = " 🔄 每天"
            elif item.recur == "weekly":
                recur_text = " 🔄 每周"
            elif item.recur == "monthly":
                recur_text = " 🔄 每月"
            lines.append(f"  • {item.title} @ {item.time}{recur_text}")
        
        yield event.plain_result("\n".join(lines))

    @filter.llm_tool(
        name="snooze_schedule",
        description="推迟指定的日程或习惯提醒。参数：title-日程名称，minutes-推迟的分钟数"
    )
    async def snooze_schedule_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        title: str, 
        minutes: int
    ) -> Generator[str, Any, None]:
        """推迟日程提醒
        
        Args:
            title (str): 要推迟的日程名称
            minutes (int): 推迟的分钟数
        """
        user_id = str(event.sender_info.user_id)
        items = await self.store.list_all_items(user_id)
        
        for item in items:
            if title.lower() in item.title.lower():
                if await self.store.snooze_item(user_id, item.id, minutes):
                    yield event.plain_result(f"已将 {item.title} 推迟 {minutes} 分钟")
                    return
        
        yield event.plain_result(f"未找到: {title}")

    @filter.llm_tool(
        name="temp_override_habit",
        description="临时修改习惯的提醒时间，仅当天生效。参数：habit_name-习惯名称，new_time-新的提醒时间(HH:MM)"
    )
    async def temp_override_habit_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        habit_name: str, 
        new_time: str
    ) -> Generator[str, Any, None]:
        """临时修改习惯的提醒时间(仅今天生效)
        
        Args:
            habit_name (str): 习惯名称
            new_time (str): 新的提醒时间,格式为 HH:MM
        """
        user_id = str(event.sender_info.user_id)
        
        if await self.store.set_temp_override(user_id, habit_name, new_time):
            yield event.plain_result(f"已临时修改 {habit_name} 为 {new_time}(今天生效)")
        else:
            yield event.plain_result(f"未找到: {habit_name}")

    @filter.llm_tool(
        name="get_notion_tasks",
        description="查看Notion中所有未完成的待办任务，显示任务名称和状态"
    )
    async def get_notion_tasks_llm(self, event: AiocqhttpMessageEvent) -> Generator[str, Any, None]:
        """查看 Notion 中标记为 PENDING 的待办任务
        """
        try:
            pending = await self.notion.get_pending_transactions()
            if not pending:
                yield event.plain_result("📝 Notion 待办为空")
                return
            
            lines = ["📝 Notion 待办:"]
            for task in pending[:10]:
                ddl = task.get('ddl')
                ddl_str = f" | 截止 {ddl[:10]}" if ddl else ""
                lines.append(f"  • {task['title']}{ddl_str} [{task['status']}]")
            if len(pending) > 10:
                lines.append(f"  ...还有 {len(pending) - 10} 项")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"获取 Notion 任务失败: {str(e)}")

    @filter.llm_tool(
        name="skip_water",
        description="跳过本次喝水提醒，系统会记录跳过时间，下次提醒将在正常间隔后触发"
    )
    async def skip_water_llm(self, event: AiocqhttpMessageEvent) -> Generator[str, Any, None]:
        """跳过本次喝水提醒
        """
        user_id = str(event.sender_info.user_id)
        await self.store.set_water_last(user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        yield event.plain_result("好的,已Skip this water reminder~")


async def __initialize(context: Context):
    """插件初始化入口
    
    Args:
        context: AstrBot 上下文
        
    Returns:
        ScheduleAssistant 实例
    """
    # 从配置获取
    config = context.get_config().get("schedule_assistant", {})
    assistant = ScheduleAssistant(context, config)
    return assistant
