"""
配置验证模块

提供配置验证、解析和迁移功能。
确保配置的健壮性和一致性。
"""

import re
from datetime import datetime
from typing import Any


class ConfigValidator:
    """配置验证器"""

    @staticmethod
    def validate_time_format(time_str: str) -> bool:
        """验证HH:MM格式的时间字符串"""
        if not time_str or not isinstance(time_str, str):
            return False
        try:
            datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    @staticmethod
    def validate_interval(value: Any, min_val: int = 2) -> int:
        """验证并转换间隔值"""
        try:
            if value is None or value == "":
                return min_val
            if isinstance(value, str):
                value = value.strip()
                if not value.isdigit():
                    return min_val
            int_val = int(value)
            return max(min_val, int_val)
        except (ValueError, TypeError):
            return min_val

    @staticmethod
    def validate_list_config(value: str) -> list[str]:
        """验证并解析列表配置（逗号或换行分隔）"""
        if not value or not isinstance(value, str):
            return []
        # 支持逗号、换行、分号分隔
        items = re.split(r"[,;\n]", value)
        return [item.strip() for item in items if item.strip()]

    @staticmethod
    def validate_url(url: str) -> bool:
        """验证URL格式"""
        if not url or not isinstance(url, str):
            return False
        # 简单的URL验证
        url_pattern = re.compile(
            r"^https?://"  # http:// or https://
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain...
            r"localhost|"  # localhost...
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
            r"(?::\d+)?"  # optional port
            r"(?:/?|[/?]\S+)$",
            re.IGNORECASE,
        )
        return bool(url_pattern.match(url))

    @staticmethod
    def validate_bool(value: Any) -> bool:
        """验证并转换布尔值"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    @staticmethod
    def validate_int(
        value: Any, default: int = 0, min_val: int = None, max_val: int = None
    ) -> int:
        """验证并转换整数值"""
        try:
            if value is None or value == "":
                return default
            if isinstance(value, str):
                value = value.strip()
                if not value.isdigit() and not (
                    value.startswith("-") and value[1:].isdigit()
                ):
                    return default
            int_val = int(value)
            if min_val is not None and int_val < min_val:
                return min_val
            if max_val is not None and int_val > max_val:
                return max_val
            return int_val
        except (ValueError, TypeError):
            return default

    @staticmethod
    def validate_float(
        value: Any, default: float = 0.0, min_val: float = None, max_val: float = None
    ) -> float:
        """验证并转换浮点数值"""
        try:
            if value is None or value == "":
                return default
            float_val = float(value)
            if min_val is not None and float_val < min_val:
                return min_val
            if max_val is not None and float_val > max_val:
                return max_val
            return float_val
        except (ValueError, TypeError):
            return default


class ConfigMigration:
    """配置迁移器"""

    @staticmethod
    def migrate_config(config: dict, version: str = "1.0") -> dict:
        """迁移配置到最新版本"""
        migrated = config.copy()

        # 示例：迁移旧版本配置
        if version == "1.0":
            # 将旧格式的配置转换为新格式
            if "water_interval" in migrated and isinstance(
                migrated["water_interval"], str
            ):
                migrated["water_interval"] = ConfigValidator.validate_interval(
                    migrated["water_interval"], min_val=30
                )

            # 确保所有时间格式正确
            time_fields = [
                "morning_report_time",
                "bath_time",
                "sleep_time",
                "water_start_time",
                "water_end_time",
            ]
            for field in time_fields:
                if field in migrated and not ConfigValidator.validate_time_format(
                    migrated[field]
                ):
                    # 设置默认值
                    defaults = {
                        "morning_report_time": "09:00",
                        "bath_time": "22:00",
                        "sleep_time": "23:00",
                        "water_start_time": "09:30",
                        "water_end_time": "21:30",
                    }
                    migrated[field] = defaults.get(field, "00:00")

        return migrated

    @staticmethod
    def get_config_version(config: dict) -> str:
        """获取配置版本"""
        return config.get("_version", "1.0")

    @staticmethod
    def set_config_version(config: dict, version: str) -> dict:
        """设置配置版本"""
        config["_version"] = version
        return config
