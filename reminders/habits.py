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
        """初始化习惯提醒

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
        """根据习惯类型设置 LLM fallback 模板"""
        self.llm_service.set_fallback_template(self.FALLBACKS.get(self.habit_type, ""))

    def _get_default_time(self) -> str:
        """获取默认提醒时间"""
        if self.habit_type == "bath":
            return self.config.get("bath_time", DEFAULT_BATH_TIME)
        elif self.habit_type == "sleep":
            return self.config.get("sleep_time", DEFAULT_SLEEP_TIME)
        return ""

    def _is_late_hour(self, now: datetime) -> bool:
        """判断是否已过深夜（23点后或凌晨2点前）"""
        return now.hour >= 23 or now.hour < 2

    def _get_prompt_context(self, username: str, dashboard: str, history_text: str, now: datetime) -> dict:
        """获取 prompt 上下文信息

        Args:
            username: 用户名
            dashboard: 仪表盘状态描述
            history_text: 对话历史
            now: 当前时间

        Returns:
            包含上下文信息的字典
        """
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
        """生成提醒消息

        Args:
            username: 用户名
            dashboard: 仪表盘状态描述
            history_text: 近期对话历史

        Returns:
            生成的提醒消息文本
        """
        now = datetime.now()
        context = self._get_prompt_context(username, dashboard, history_text, now)
        prompt = self._build_prompt(context)
        # 传递对话历史给 LLM，让 AI 有上下文
        return await self.llm_service.generate(prompt, history=history_text)


class BathReminder(HabitReminder):
    """洗澡提醒"""

    def __init__(self, config: dict, default_user_id: str, llm_service, store):
        super().__init__(config, default_user_id, llm_service, store, "bath")

    def _build_prompt(self, context: dict) -> str:
        return f"""【重要】你的所有回复必须严格遵循系统人格设定。如果系统人格部分为空，则用你默认的对话风格。。

生成一条洗澡时间提醒：

【用户信息】
- 当前时间: {context['current_time']}
- 设定的洗澡时间: {context['default_time']}
- 用户当前状态: {context['dashboard']}

【近期对话】
{context['history']}

【要求】
1. 语气和风格严格遵循系统人格设定
2. 可以根据状态适当调侃
3. 40字以内，带1-2个emoji
4. 不要 markdown，纯文本输出
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
        return f"""【重要】你的所有回复必须严格遵循系统人格设定。如果系统人格部分为空，则用你默认的对话风格。。

生成一条睡觉时间提醒：

【用户信息】
- 当前时间: {context['current_time']}
- 设定的睡觉时间: {context['default_time']}
- 是否已超晚(23点后): {context.get('is_late', False)}
- 用户当前状态: {context['dashboard']}

【要求】
1. 语气和风格严格遵循系统人格设定
2. 如果超晚了可以带点小责备，但要符合人格
3. 结合 Dashboard 状态适当提醒
4. 40字以内，带1-2个emoji
5. 不要 markdown，纯文本输出
6. 只输出提醒消息本身"""


class WaterReminder(HabitReminder):
    """喝水提醒"""

    def __init__(self, config: dict, default_user_id: str, llm_service, store):
        super().__init__(config, default_user_id, llm_service, store, "water")

    def _build_prompt(self, context: dict) -> str:
        return f"""【重要】你的所有回复必须严格遵循系统人格设定。如果系统人格部分为空，则用你默认的对话风格。。

生成一条喝水提醒：

【用户信息】
- 当前时间: {context['current_time']}
- 用户当前状态: {context['dashboard']}

【近期对话】
{context['history']}

【要求】
1. 语气和风格严格遵循系统人格设定
2. 结合当前时间、状态、对话上下文
3. 30字以内，带1-2个emoji
4. 不要 markdown，纯文本输出
5. 只输出提醒消息本身"""
