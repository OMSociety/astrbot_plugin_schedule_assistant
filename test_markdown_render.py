"""MarkdownRenderer 渲染行为验证（无需 AstrBot 环境，markdown.py 无外部依赖）

验证场景：
1. QQ 官方（qq_official）：默认原生 md 直发
2. QQ 官方 + qq_markdown_enabled=false：降级 QQ 排版纯文本
3. 其他原生平台（discord）：原生直发
4. 非原生平台（Onebot 等）：strip 纯文本降级
5. markdown_enabled=false：全局关闭，原文直发
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from markdown import MarkdownRenderer

SAMPLE_MD = (
    "早安~新的一天开始啦♪\n\n"
    "#### 📅 早安播报\n"
    "愚人节快乐~ 2026-04-01 周三\n\n"
    "**🌤️ 天气** 当前阴天 19°C\n\n"
    "#### 📋 今日日程\n"
    "| 时间 | 课程 |\n"
    "|------|------|\n"
    "| 09:45 | 学术英语听说 |\n"
)

failures = []


def check(name: str, got, want):
    ok = got == want
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        failures.append(name)
        print(f"      期望: {want!r}")
        print(f"      实际: {got!r}")


# 1. QQ 官方：默认原生 md 直发（平台实例 id "Flandre" 映射到平台类型 qq_official）
r = MarkdownRenderer(
    {"markdown_enabled": True},
    platform_types={"Flandre": "qq_official"},
)
content, kind = r.render(SAMPLE_MD, "Flandre")
check("QQ官方默认 -> 原生直发", (content, kind), (SAMPLE_MD, "native"))

# 2. QQ 官方 + qq_markdown_enabled=false -> QQ 排版纯文本（表格转键:值）
r2 = MarkdownRenderer(
    {"markdown_enabled": True, "qq_markdown_enabled": False},
    platform_types={"Flandre": "qq_official"},
)
content2, kind2 = r2.render(SAMPLE_MD, "Flandre")
check("QQ官方+关闭md -> QQ排版纯文本", (kind2, "时间：课程" in content2), ("plain", True))

# 3. 其他原生平台（discord）：原生直发
r3 = MarkdownRenderer(
    {"markdown_enabled": True},
    platform_types={"d1": "discord"},
)
content3, kind3 = r3.render(SAMPLE_MD, "d1")
check("discord -> 原生直发", (content3, kind3), (SAMPLE_MD, "native"))

# 4. 非原生平台（Onebot）：strip 纯文本降级
r4 = MarkdownRenderer(
    {"markdown_enabled": True},
    platform_types={"ob1": "aiocqhttp"},
)
content4, kind4 = r4.render(SAMPLE_MD, "ob1")
check("Onebot(aiocqhttp) -> 纯文本降级", (kind4, "| 时间 | 课程 |" not in content4), ("plain", True))

# 5. markdown_enabled=false：全局关闭，原文直发
r5 = MarkdownRenderer(
    {"markdown_enabled": False},
    platform_types={"Flandre": "qq_official"},
)
content5, kind5 = r5.render(SAMPLE_MD, "Flandre")
check("全局关闭 -> 原文直发", (content5, kind5), (SAMPLE_MD, "plain"))

# 6. 无 md 语法文本：不触发渲染（行为零变化）
r6 = MarkdownRenderer(
    {"markdown_enabled": True},
    platform_types={"Flandre": "qq_official"},
)
plain_text = "晚上好，今天过得怎么样？"
content6, kind6 = r6.render(plain_text, "Flandre")
check("纯文本消息 -> 原文直发", (content6, kind6), (plain_text, "plain"))

print()
if failures:
    print(f"共 {len(failures)} 项失败: {failures}")
    sys.exit(1)
print("全部 6 项渲染行为验证通过 (OK)")
