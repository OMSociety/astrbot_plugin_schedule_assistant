"""喝水提醒服务"""
from datetime import datetime


_WATER_FALLBACK = "💧 该喝水啦~ 站起来活动活动，倒杯水润润嗓吧！"


class WaterReminder:
    def __init__(self, config: dict, get_dashboard_status, llm_service, store):
        self.config = config
        self.get_dashboard_status = get_dashboard_status
        self.llm_service = llm_service
        self.store = store
        self.default_user_id = config.get("default_user_id", "")
        self.llm_service.set_fallback_template(_WATER_FALLBACK)

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

    async def _trigger(self, parent):
        username = await parent._get_username_from_qq(parent.default_user_id) or "用户"
        dashboard = await parent.dashboard_service.func()
        history = await parent.store.get_conversation_history(parent.default_user_id)
        history_text = parent.store.format_history_for_prompt(history)
        message = await self.generate(username, dashboard, history_text)
        if message:
            await parent._send_to_user(parent.default_user_id, message)
            await parent.store.add_conversation_message(parent.default_user_id, "assistant", message)
        # 自动重新调度下一次喝水提醒
        from datetime import datetime
        ws = parent.config.get("water_start_time", "09:30")
        we = parent.config.get("water_end_time", "21:30")
        wi = parent.config.get("water_interval", 90)
        next_trigger = parent._get_water_next_trigger(datetime.now(), ws, we, wi)
        parent.scheduler.add_job(parent._water_reminder, "date", run_date=next_trigger, id="water_reminder", replace_existing=True)
        return message
