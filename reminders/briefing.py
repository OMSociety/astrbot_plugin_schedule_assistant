"""早安播报服务"""
from ..constants import LOG_PREFIX


class BriefingReminder:
    def __init__(self, config: dict, context, llm_service):
        self.config = config
        self.context = context
        self.llm_service = llm_service

    async def generate_full_report(
        self,
        username: str, date: str, weekday: str,
        weather_current: str, weather_forecast: str,
        agenda: str, notion_todos: str,
        dashboard: str = "", late_night: str = ""
    ) -> str:
        agenda_lines = [l.strip().replace("|", " ") for l in agenda.split("\n") if l.strip()] if agenda and agenda not in ("暂无", "获取失败") else []
        notion_lines = [l.strip() for l in notion_todos.split("\n") if l.strip()] if notion_todos and notion_todos not in ("暂无", "获取失败") else []

        prompt = f"""【任务】生成一份完整的早安播报。

【系统人格】这部分是系统注入的人设约束，你的回复必须符合这个人设。如果这部分为空，则用你默认的对话风格。

【今日信息】
日期: {date} {weekday}
天气: {weather_current}（预报: {weather_forecast if weather_forecast else "暂无"}）
日程:
{"\n".join(agenda_lines) if agenda_lines else "暂无"}
待办:
{"\n".join(notion_lines) if notion_lines else "暂无"}
设备状态: {dashboard if dashboard else "暂无"}
熬夜检测: {"有深夜日程（" + late_night.strip() + "），昨晚辛苦了" if late_night and late_night.strip() else "无深夜日程"}

【播报要求】
1. 开头用称呼语，自然融入用户名
2. 语气和风格严格遵循上方系统人格设定
3. 根据信息给出针对性建议（如熬夜 → 关心，DDL临近 → 提醒）
4. 不要 markdown，纯文本输出
5. 只输出播报消息本身

【格式要求】
（早安语，称呼+简短问候）
日期
天气（当前+预报）
日程（如有）
待办（如有）
温馨建议（一段以内）

【例子】
早安~新的一天开始了♪

📅 2026-04-01 周三 愚人节快乐~
🌥 当前阴天 19°C，今日晴朗 9~24°C，降水概率0%

📋 今日日程
─────────────
⏰ 09:45 │ 学术英语听说
⏰ 13:50 │ 习近平新时代中国特色社会主义思想概论
⏰ 15:35 │ 马克思主义哲学史
⏰ 19:00 │ 学术写作与沟通

📌 待办提醒
─────────────
🔥 还剩1天 │ 《资本论》读书报告
📃 还剩3天 │ 学生会面试

🫕 温馨提示
今天阴天但气温还行，不用带伞~四门课连轴转辛苦了，中午记得吃点好的补充能量🥺读书报告只剩1天了，合理安排时间哦~"""

        return await self.llm_service.generate(prompt)
