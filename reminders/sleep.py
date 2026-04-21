"""睡觉提醒服务"""
from datetime import datetime
from ..constants import DEFAULT_SLEEP_TIME


class SleepReminder:
    def __init__(self, config: dict, get_dashboard_status, llm_service, store):
        self.config = config
        self.get_dashboard_status = get_dashboard_status
        self.llm_service = llm_service
        self.store = store
        self.default_user_id = config.get("default_user_id", "")

    def _is_late(self, now: datetime) -> bool:
        return now.hour >= 23 or now.hour < 2

    async def generate(self, username: str, dashboard: str, history_text: str) -> str | None:
        now = datetime.now()
        is_late = self._is_late(now)
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
