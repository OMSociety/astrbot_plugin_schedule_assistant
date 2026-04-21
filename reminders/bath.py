"""洗澡提醒服务"""
from datetime import datetime
from ..constants import DEFAULT_BATH_TIME


class BathReminder:
    def __init__(self, config: dict, get_dashboard_status, llm_service, store):
        self.config = config
        self.get_dashboard_status = get_dashboard_status
        self.llm_service = llm_service
        self.store = store
        self.default_user_id = config.get("default_user_id", "")

    async def generate(self, username: str, dashboard: str, history_text: str) -> str | None:
        now = datetime.now()
        prompt = f"""你是「{username}」的贴心日程助手，现在需要生成一条洗澡时间提醒~

【用户信息】
- 用户名: {username}
- 当前时间: {now.strftime("%H:%M")}
- 设定的洗澡时间: {self.config.get("bath_time", DEFAULT_BATH_TIME)}
- 用户当前状态: {dashboard}

【近期对话】
{history_text or "（无近期对话）"}

【生成要求】
1. 语气活泼可爱，像朋友催你去洗澡
2. 如果 dashboard 显示用户刚运动/干活了，可以调侃"该洗掉汗味啦"
3. 40字以内，带1-2个emoji
4. 不要markdown，纯文本输出
5. 只输出提醒消息本身"""
        return await self.llm_service.generate(prompt)
