"""早安播报服务"""
# ruff: noqa: E501


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
        dashboard: str = "", late_night: str = "",
        user_id: str = None
    ) -> str:
        agenda_lines = [ln.strip().replace("|", " ") for ln in agenda.split("\n") if ln.strip()] if agenda and agenda not in ("暂无", "获取失败") else []
        _nl = chr(10)  # newline char for f-string
        notion_lines = [ln.strip() for ln in notion_todos.split("\n") if ln.strip()] if notion_todos and notion_todos not in ("暂无", "获取失败") else []

        # 清理 dashboard：无效状态时不显示
        dashboard_clean = dashboard.strip() if dashboard else ""
        if dashboard_clean in ("", "未知", "暂无", "未配置", "获取失败"):
            dashboard_section = ""
        else:
            dashboard_section = f"\n设备状态: {dashboard_clean}"

        late_night_section = ""
        if late_night and late_night.strip():
            late_night_section = f"\n熬夜检测: 昨晚有深夜日程（{late_night.strip()}），辛苦了"

        prompt = f"""【任务】生成一份完整的早安播报，严格遵循以下格式。

【格式要求】（必须逐行照搬，不要改顺序，不要删行，不要合并行）
称呼语（开头，必须有）
📅 日期 星期X
🌤️ 天气描述
📋 今日日程（如有）
  ⏰ 时间 │ 日程名
📌 待办提醒（如有）
  🔥/📃 剩余天数 │ 待办名
🦕 温馨建议（可选，一段以内）

【今日信息】
日期: {date} {weekday}
天气: {weather_current}（预报: {weather_forecast if weather_forecast else "暂无"}）
日程:
{_nl.join(agenda_lines) if agenda_lines else "暂无"}
待办:
{_nl.join(notion_lines) if notion_lines else "暂无"}{dashboard_section}{late_night_section}

【人格要求】
必须严格遵循上方系统人格设定的语气和风格。
称呼语中必须包含用户名 "{username}"。
不要 markdown，不要 emoji 以外的表情符号。
日程/待办如为"暂无"则整块省略不输出。

【示例输出】（格式参考，禁止添加省略的内容）
早安~{username}，新的一天开始啦♪

📅 2026-04-01 周三
🌤️ 当前晴 19°C，预报晴 9~24°C

📋 今日日程
  ⏰ 09:45 │ 学术英语听说
  ⏰ 13:50 │ 思政课

📌 待办提醒
  🔥 还剩1天 │ 读书报告

🦕 温馨提醒
四门课辛苦了，中午吃点好的补充能量~"""

        return await self.llm_service.generate(prompt, umo=user_id)
