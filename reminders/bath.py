"""洗澡提醒服务（已迁移到 habits.py）"""
from .habits import BathReminder

# 向后兼容
__all__ = ["BathReminder"]
