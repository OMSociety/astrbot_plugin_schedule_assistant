"""喝水提醒服务"""
from datetime import datetime


class WaterReminder:
    def __init__(self, config: dict, get_dashboard_status, llm_service, store):
        self.config = config
        self.get_dashboard_status = get_dashboard_status
        self.llm_service = llm_service
        self.store = store
        self.default_user_id = config.get("default_user_id", "")

    async def generate(self, username: str, dashboard: str, history_text: str) -> str | None:
        now = datetime.now()
        prompt = f"""你是「{username}」的贴心日程助手，现在需要生成一条喝水提醒~

【用户信息】
- 用户名: {username}
- 当前时间: {now.strftime("%H:%M")}
- 用户当前状态: {dashboard}

【近期对话】
{history_text or "（无近期对话）"}

【生成要求】
1. 语气活泼俏皮，像闺蜜催你喝水
2. 结合当前时间、dashboard状态、近期对话上下文发挥创意，多样化调侃方式
3. 30字以内，带1-2个emoji
4. 不要markdown，纯文本输出
5. 只输出提醒消息本身"""
        return await self.llm_service.generate(prompt)
