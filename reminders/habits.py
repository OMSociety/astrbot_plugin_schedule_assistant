"""
通用习惯提醒模块
BathReminder, SleepReminder, WaterReminder 都基于此类
"""

from datetime import datetime
from typing import Optional

from ..constants import DEFAULT_BATH_TIME, DEFAULT_SLEEP_TIME, DEFAULT_WATER_START, DEFAULT_WATER_END, DEFAULT_WATER_INTERVAL


class HabitReminder:
    """通用习惯提醒生成器"""
    
    # 默认 fallback 消息
    FALLBACKS = {
        "bath": "🚿 洗澡时间到啦~ 今天流汗了吗？快去洗个澡清爽一下！",
        "sleep": "😴 睡觉时间到啦~ 晚安，早点休息哦~",
        "sleep_late": "🌙 都几点了还不睡！快去睡觉！",
        "water": "💧 该喝水啦~ 站起来活动活动，倒杯水润润嗓吧！",
    }
    
    # 各习惯的默认时间配置
    DEFAULT_TIMES = {
        "bath": DEFAULT_BATH_TIME,
        "sleep": DEFAULT_SLEEP_TIME,
        "water_start": DEFAULT_WATER_START,
        "water_end": DEFAULT_WATER_END,
        "water_interval": DEFAULT_WATER_INTERVAL,
    }
    
    def __init__(self, config: dict, default_user_id: str, llm_service, store, habit_type: str):
        """
        Args:
            config: 插件配置
            default_user_id: 默认用户 ID
            llm_service: LLM 服务
            store: 数据存储
            habit_type: 习惯类型 "bath" | "sleep" | "water"
        """
        self.config = config
        self.default_user_id = default_user_id
        self.llm_service = llm_service
        self.store = store
        self.habit_type = habit_type
        self._setup_llm_template()
    
    def _setup_llm_template(self):
        """根据习惯类型设置 LLM 模板"""
        self.llm_service.set_fallback_template(self.FALLBACKS.get(self.habit_type, ""))
    
    def _get_default_time(self) -> str:
        """获取默认提醒时间"""
        if self.habit_type == "bath":
            return self.config.get("bath_time", DEFAULT_BATH_TIME)
        elif self.habit_type == "sleep":
            return self.config.get("sleep_time", DEFAULT_SLEEP_TIME)
        return ""
    
    def _is_late_hour(self, now: datetime) -> bool:
        """判断是否已过深夜"""
        return now.hour >= 23 or now.hour < 2
    
    def _get_prompt_context(self, username: str, dashboard: str, history_text: str, now: datetime) -> dict:
        """获取 prompt 上下文信息，子类可覆盖"""
        return {
            "username": username,
            "current_time": now.strftime("%H:%M"),
            "default_time": self._get_default_time(),
            "dashboard": dashboard,
            "history": history_text or "（无近期对话）",
        }
    
    def _build_prompt(self, context: dict) -> str:
        """构建 LLM prompt，子类可覆盖"""
        raise NotImplementedError
    
    async def generate(self, username: str, dashboard: str, history_text: str) -> Optional[str]:
        """生成提醒消息"""
        now = datetime.now()
        context = self._get_prompt_context(username, dashboard, history_text, now)
        prompt = self._build_prompt(context)
        return await self.llm_service.generate(prompt)


class BathReminder(HabitReminder):
    """洗澡提醒"""
    
    def __init__(self, config: dict, default_user_id: str, llm_service, store):
        super().__init__(config, default_user_id, llm_service, store, "bath")
    
    def _build_prompt(self, context: dict) -> str:
        return f"""你是「{context['username']}」的贴心日程助手，现在需要生成一条洗澡时间提醒~

【用户信息】
- 用户名: {context['username']}
- 当前时间: {context['current_time']}
- 设定的洗澡时间: {context['default_time']}
- 用户当前状态: {context['dashboard']}


【近期对话】
{context['history']}

【生成要求】
1. 语气活泼可爱，像朋友催你去洗澡
2. 如果 dashboard 显示用户刚运动/干活了，可以调侃"该洗掉汗味啦"
3. 40字以内，带1-2个emoji
4. 不要markdown，纯文本输出
5. 只输出提醒消息本身"""


class SleepReminder(HabitReminder):
    """睡觉提醒"""
    
    def __init__(self, config: dict, default_user_id: str, llm_service, store):
        super().__init__(config, default_user_id, llm_service, store, "sleep")
        self.llm_service.set_fallback_template(self.FALLBACKS["sleep"])
    
    def _get_prompt_context(self, username: str, dashboard: str, history_text: str, now: datetime) -> dict:
        ctx = super()._get_prompt_context(username, dashboard, history_text, now)
        ctx["is_late"] = self._is_late_hour(now)
        return ctx
    
    def _build_prompt(self, context: dict) -> str:
        is_late = context.get("is_late", False)
        self.llm_service.set_fallback_template(
            self.FALLBACKS["sleep_late"] if is_late else self.FALLBACKS["sleep"]
        )
        return f"""你是「{context['username']}」的贴心日程助手，现在需要生成一条睡觉时间提醒~

【用户信息】
- 用户名: {context['username']}
- 当前时间: {context['current_time']}
- 设定的睡觉时间: {context['default_time']}
- 是否已超晚(23点后): {context.get('is_late', False)}
- 用户当前状态: {context['dashboard']}

【生成要求】
1. 如果已经超晚23点，语气要带点小责备，比如"都几点了还不睡！"
2. 如果还没很晚，语气温柔催促
3. 结合 dashboard 状态：如果显示还在熬夜/游戏，要重点催睡
4. 40字以内，带1-2个emoji
5. 不要markdown，纯文本输出
6. 只输出提醒消息本身"""


class WaterReminder(HabitReminder):
    """喝水提醒"""
    
    def __init__(self, config: dict, default_user_id: str, llm_service, store):
        super().__init__(config, default_user_id, llm_service, store, "water")
    
    def _build_prompt(self, context: dict) -> str:
        return f"""你是「{context['username']}」的贴心日程助手，现在需要生成一条喝水提醒~

【用户信息】
- 用户名: {context['username']}
- 当前时间: {context['current_time']}
- 用户当前状态: {context['dashboard']}


【近期对话】
{context['history']}

【生成要求】
1. 语气活泼俏皮，像闺蜜催你喝水
2. 结合当前时间、dashboard状态、近期对话上下文发挥创意，多样化调侃方式
3. 30字以内，带1-2个emoji
4. 不要markdown，纯文本输出
5. 只输出提醒消息本身"""
