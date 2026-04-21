"""
Schedule Assistant 插件常量定义

定义插件范围内使用的常量，包括存储键名和默认配置值。
"""

# ==================== 数据存储配置 ====================
# 插件数据存储使用的 preference scope
PREFERENCE_SCOPE = "schedule_assistant"

# Preference 键名

# 数据键名（存储在 preference value 中的键）
SCHEDULES_KEY = "schedules"      # 单次日程列表键名
HABITS_KEY = "habits"            # 重复习惯列表键名
WATER_LAST_KEY = "water_last"    # 上次喝水时间键名
CONVERSATION_KEY = "conversation_history"  # 近期对话历史键名
CONVERSATION_MAX_AGE_HOURS = 1   # 对话历史保留时间（小时）
CONVERSATION_MAX_MESSAGES = 10   # 最多保留消息条数

# ==================== 默认提醒时间 ====================
DEFAULT_BATH_TIME = "22:00"           # 默认洗澡时间
DEFAULT_SLEEP_TIME = "23:00"          # 默认睡觉时间
DEFAULT_WATER_START = "09:30"       # 默认喝水提醒开始时间
DEFAULT_WATER_END = "21:30"         # 默认喝水提醒结束时间
DEFAULT_WATER_INTERVAL = 90         # 默认喝水提醒间隔（分钟）
MAX_WATER_INTERVAL_MINUTES = 720    # 喝水提醒间隔上限（分钟）
SCHEDULE_SCAN_WINDOW_MINUTES = 80   # 日程扫描窗口（分钟）

# ==================== 日志前缀 ====================
LOG_PREFIX = "[ScheduleAssistant]"