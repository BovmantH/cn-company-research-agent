"""Web 用户任务级模型选择的安全值对象。"""

from __future__ import annotations

import re
from dataclasses import dataclass

CLIENT_MODEL_VENDORS: tuple[str, ...] = (
    "opencode",
    "deepseek",
    "kimi",
    "qwen",
    "glm",
    "minimax",
    "mimo",
    "openrouter",
    "openai",
)
CLIENT_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
QWEN_RESPONSES_WEB_SEARCH_MODELS = ("qwen3.7-plus", "qwen3.7-max")


@dataclass(frozen=True)
class SelectedModel:
    """已经通过模型目录校验、可安全交给任务工厂的选择。"""

    vendor: str
    model: str


__all__ = [
    "CLIENT_MODEL_ID_PATTERN",
    "CLIENT_MODEL_VENDORS",
    "QWEN_RESPONSES_WEB_SEARCH_MODELS",
    "SelectedModel",
]
