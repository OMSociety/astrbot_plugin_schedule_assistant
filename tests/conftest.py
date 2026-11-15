"""pytest 共享配置：把插件目录注册成 schedule_assistant 包。"""

import os
import sys
import types

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

_package = types.ModuleType("schedule_assistant")
_package.__path__ = [_PLUGIN_DIR]
sys.modules.setdefault("schedule_assistant", _package)
