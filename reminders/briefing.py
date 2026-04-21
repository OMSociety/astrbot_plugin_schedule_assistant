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
        calendar: str, schedules: str, notion: str,
        dashboard: str = "", late_night: str = ""
    ) -> str:
        cal_lines = [l.strip().replace("|", " ") for l in calendar.split("\n") if l.strip()] if calendar and calendar not in ("暂无", "获取失败") else []
        notion_lines = [l.strip() for l in notion.split("\n") if l.strip()] if notion and notion not in ("暂无", "获取失败") else []

        prompt = f"""你的人格设定（由系统提供）会决定你的说话风格。

【你的任务】
请以符合人格风格的方式，生成一份完整的早安播报。要求：
1. 开头必须有称呼语（如"早安xxx~"），称呼要自然融入
2. 结合用户当前状态给出针对性建议
3. 语言要符合你的人设，不要生硬

【今日信息】
日期: {date} {weekday}
天气: {weather_current}（预报: {weather_forecast if weather_forecast else "暂无"}）
日程:
{"\n".join(cal_lines) if cal_lines else "暂无"}
待办:
{schedules if schedules and schedules != "暂无" else "暂无"}
Notion待办:
{"\n".join(notion_lines) if notion_lines else "暂无"}
设备状态: {dashboard if dashboard else "暂无"}
熬夜检测: {"有深夜日程（" + late_night.strip() + "），昨晚辛苦了" if late_night and late_night.strip() else "无深夜日程"}

【温馨建议生成规则】
- 如果熬夜检测显示有深夜日程，要说关心的话
- 如果设备显示用户还在床上或游戏中，温和催促开始新的一天
- 如果有DDL临近的待办，重点提醒
- 如果天气不好，提醒带伞添衣
- 建议要有针对性，不要泛泛而谈

【格式要求】
（早安语，称呼+简短问候）
日期
天气（当前+预报）
日程（如有）
待办（如有）
温馨建议（一段以内）"""
        return await self.llm_service.generate(prompt)
