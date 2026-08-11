"""Web 用户任务级模型选择的安全值对象。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .provider_registry import CLIENT_MODEL_VENDORS

CLIENT_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
QWEN_RESPONSES_WEB_SEARCH_MODELS = ("qwen3.7-plus", "qwen3.7-max")
GLM_WEB_SEARCH_MODELS = ("glm-4.7", "glm-5.2", "glm-4.7-flash")
MIMO_WEB_SEARCH_MODELS = ("mimo-v2.5", "mimo-v2.5-pro")
OPENAI_RESPONSES_WEB_SEARCH_MODELS = (
    "gpt-5.6",
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
)
WEB_SEARCH_MODEL_ALLOWLISTS: dict[str, frozenset[str]] = {
    "qwen": frozenset(QWEN_RESPONSES_WEB_SEARCH_MODELS),
    "glm": frozenset(GLM_WEB_SEARCH_MODELS),
    "mimo": frozenset(MIMO_WEB_SEARCH_MODELS),
    "openai": frozenset(OPENAI_RESPONSES_WEB_SEARCH_MODELS),
}


@dataclass(frozen=True)
class SelectedModel:
    """已经通过模型目录校验、可安全交给任务工厂的选择。"""

    vendor: str
    model: str


__all__ = [
    "CLIENT_MODEL_ID_PATTERN",
    "CLIENT_MODEL_VENDORS",
    "GLM_WEB_SEARCH_MODELS",
    "MIMO_WEB_SEARCH_MODELS",
    "OPENAI_RESPONSES_WEB_SEARCH_MODELS",
    "QWEN_RESPONSES_WEB_SEARCH_MODELS",
    "SelectedModel",
    "WEB_SEARCH_MODEL_ALLOWLISTS",
]
