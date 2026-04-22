"""喝水提醒服务（已迁移到 habits.py）"""
from .habits import WaterReminder

# 向后兼容
__all__ = ["WaterReminder"]
