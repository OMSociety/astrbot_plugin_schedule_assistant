"""向后兼容的再导出薄包装。权威实现在 services.config_parser。"""

from ..services.config_parser import (  # noqa: F401
    get_bool_value,
    get_int_value,
    get_text_value,
    parse_list_config,
)
