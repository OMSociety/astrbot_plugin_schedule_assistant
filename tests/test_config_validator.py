"""
配置验证模块测试
"""

import pytest
from datetime import datetime

# 导入被测试的模块
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_validator import ConfigValidator, ConfigMigration


class TestConfigValidator:
    """ConfigValidator 测试类"""

    def test_validate_time_format_valid(self):
        """测试有效的时间格式"""
        assert ConfigValidator.validate_time_format("09:00") == True
        assert ConfigValidator.validate_time_format("23:59") == True
        assert ConfigValidator.validate_time_format("00:00") == True

    def test_validate_time_format_invalid(self):
        """测试无效的时间格式"""
        assert ConfigValidator.validate_time_format("") == False
        assert ConfigValidator.validate_time_format(None) == False
        assert ConfigValidator.validate_time_format("25:00") == False
        assert ConfigValidator.validate_time_format("12:60") == False
        assert ConfigValidator.validate_time_format("12:00:00") == False
        assert ConfigValidator.validate_time_format("1200") == False

    def test_validate_interval_valid(self):
        """测试有效的间隔值"""
        assert ConfigValidator.validate_interval(10) == 10
        assert ConfigValidator.validate_interval("10") == 10
        assert ConfigValidator.validate_interval(1, min_val=2) == 2  # 小于最小值

    def test_validate_interval_invalid(self):
        """测试无效的间隔值"""
        assert ConfigValidator.validate_interval("") == 2  # 默认最小值
        assert ConfigValidator.validate_interval(None) == 2
        assert ConfigValidator.validate_interval("abc") == 2
        assert ConfigValidator.validate_interval(-5) == 2  # 负数

    def test_validate_list_config_valid(self):
        """测试有效的列表配置"""
        assert ConfigValidator.validate_list_config("a,b,c") == ["a", "b", "c"]
        assert ConfigValidator.validate_list_config("a;b;c") == ["a", "b", "c"]
        assert ConfigValidator.validate_list_config("a\nb\nc") == ["a", "b", "c"]
        assert ConfigValidator.validate_list_config("a, b, c") == ["a", "b", "c"]

    def test_validate_list_config_invalid(self):
        """测试无效的列表配置"""
        assert ConfigValidator.validate_list_config("") == []
        assert ConfigValidator.validate_list_config(None) == []
        assert ConfigValidator.validate_list_config(",,") == []

    def test_validate_url_valid(self):
        """测试有效的URL"""
        assert ConfigValidator.validate_url("https://example.com") == True
        assert ConfigValidator.validate_url("http://localhost:8080") == True
        assert ConfigValidator.validate_url("https://api.example.com/path?query=1") == True

    def test_validate_url_invalid(self):
        """测试无效的URL"""
        assert ConfigValidator.validate_url("") == False
        assert ConfigValidator.validate_url(None) == False
        assert ConfigValidator.validate_url("example.com") == False
        assert ConfigValidator.validate_url("ftp://example.com") == False

    def test_validate_bool_valid(self):
        """测试有效的布尔值"""
        assert ConfigValidator.validate_bool(True) == True
        assert ConfigValidator.validate_bool(False) == False
        assert ConfigValidator.validate_bool("true") == True
        assert ConfigValidator.validate_bool("false") == False
        assert ConfigValidator.validate_bool("1") == True
        assert ConfigValidator.validate_bool("0") == False

    def test_validate_int_valid(self):
        """测试有效的整数值"""
        assert ConfigValidator.validate_int(10) == 10
        assert ConfigValidator.validate_int("10") == 10
        assert ConfigValidator.validate_int(None, default=5) == 5
        assert ConfigValidator.validate_int("", default=5) == 5
        assert ConfigValidator.validate_int(10, min_val=5, max_val=15) == 10
        assert ConfigValidator.validate_int(1, min_val=5) == 5  # 小于最小值
        assert ConfigValidator.validate_int(20, max_val=15) == 15  # 大于最大值

    def test_validate_float_valid(self):
        """测试有效的浮点数值"""
        assert ConfigValidator.validate_float(10.5) == 10.5
        assert ConfigValidator.validate_float("10.5") == 10.5
        assert ConfigValidator.validate_float(None, default=5.0) == 5.0
        assert ConfigValidator.validate_float("", default=5.0) == 5.0
        assert ConfigValidator.validate_float(10.5, min_val=5.0, max_val=15.0) == 10.5


class TestConfigMigration:
    """ConfigMigration 测试类"""

    def test_migrate_config_v1(self):
        """测试配置迁移 v1.0"""
        config = {
            "water_interval": "90",
            "morning_report_time": "09:00",
            "bath_time": "22:00"
        }
        migrated = ConfigMigration.migrate_config(config, "1.0")
        assert migrated["water_interval"] == 90
        assert migrated["morning_report_time"] == "09:00"
        assert migrated["bath_time"] == "22:00"

    def test_migrate_config_invalid_time(self):
        """测试无效时间格式的迁移"""
        config = {
            "morning_report_time": "invalid",
            "bath_time": "25:00"
        }
        migrated = ConfigMigration.migrate_config(config, "1.0")
        assert migrated["morning_report_time"] == "09:00"  # 默认值
        assert migrated["bath_time"] == "22:00"  # 默认值

    def test_get_config_version(self):
        """测试获取配置版本"""
        config = {"_version": "2.0"}
        assert ConfigMigration.get_config_version(config) == "2.0"

        config = {}
        assert ConfigMigration.get_config_version(config) == "1.0"  # 默认版本

    def test_set_config_version(self):
        """测试设置配置版本"""
        config = {}
        config = ConfigMigration.set_config_version(config, "2.0")
        assert config["_version"] == "2.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])