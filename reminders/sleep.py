"""睡觉提醒服务"""
from datetime import datetime
from ..constants import DEFAULT_SLEEP_TIME


_SLEEP_FALLBACK_LATE = "🌙 都几点了还不睡！快去睡觉！"
_SLEEP_FALLBACK_NORMAL = "😴 睡觉时间到啦~ 晚安，早点休息哦~"


class SleepReminder:
    def __init__(self, config: dict, default_user_id: str, llm_service, store):
        self.config = config
        self.default_user_id = default_user_id
        self.llm_service = llm_service
        self.store = store

    def _get_fallback(self) -> str:
        return _SLEEP_FALLBACK_LATE if datetime.now().hour >= 23 else _SLEEP_FALLBACK_NORMAL


    def _is_late(self, now: datetime) -> bool:
        return now.hour >= 23 or now.hour < 2

    async def generate(self, username: str, dashboard: str, history_text: str) -> str | None:
        now = datetime.now()
        is_late = self._is_late(now)
        self.llm_service.set_fallback_template(self._get_fallback())
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
        return await self.llm_service.generate(prompt)
