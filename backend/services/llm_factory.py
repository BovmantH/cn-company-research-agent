"""统一 LLM 工厂。

设计目标:
- 通过 ``get_llm(role)`` 获取 LangChain ``BaseChatModel`` 实例
- 默认走 **OpenRouter**,兼容 OpenAI 协议,不需要每加一个模型改代码
- ``OPENROUTER_API_KEY`` 缺失但 ``OPENAI_API_KEY`` 存在时,自动降级到原生 OpenAI
- 模型选择**逐角色**通过 ``LLM_MODEL_<ROLE>`` 环境变量配置
- 调用方可通过 ``**overrides`` 临时覆盖任意参数

环境变量约定:
    OPENROUTER_API_KEY        OpenRouter API key(主推)
    OPENAI_API_KEY            OpenAI API key(降级路径)
    LLM_MODEL_RESEARCHER      researcher 角色用什么模型
    LLM_MODEL_BRIEFING        briefing 角色用什么模型
    LLM_MODEL_EDITOR          editor 角色用什么模型
    LLM_TEMPERATURE           温度,默认 0
    LLM_STREAMING             是否流式,默认 true
    LLM_BASE_URL              覆盖 base_url(用于本地 vLLM/Ollama 等)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# === 常量 ===

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# 各角色默认模型(可被环境变量覆盖)
DEFAULT_MODELS: dict[str, str] = {
    "researcher": "deepseek/deepseek-chat",
    "briefing": "qwen/qwen-2.5-72b-instruct",
    "editor": "anthropic/claude-3.5-sonnet",
}

VALID_ROLES = frozenset(DEFAULT_MODELS.keys())


def _str_to_bool(value: str | None, default: bool = False) -> bool:
    """字符串转布尔。空值用 default。"""
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes", "y", "on")


def _strip_vendor_prefix(model: str) -> str:
    """``"openai/gpt-4o" -> "gpt-4o"``,降级到 OpenAI 时用。"""
    if "/" in model:
        return model.split("/", 1)[-1]
    return model


def get_llm(role: str, **overrides: Any) -> BaseChatModel:
    """根据角色获取一个配置好的 LLM 实例。

    Args:
        role: 角色名,目前支持 ``"researcher"`` / ``"briefing"`` / ``"editor"``。
        **overrides: 任意可覆盖参数(``model``、``temperature``、``streaming``、
            ``base_url``、``api_key`` 等)。

    Returns:
        ``langchain_openai.ChatOpenAI`` 实例(OpenRouter 兼容 OpenAI 协议,
        因此用 ``ChatOpenAI`` 即可同时支持两条路径)。

    Raises:
        ValueError: 未知 role。
        RuntimeError: ``OPENROUTER_API_KEY`` 与 ``OPENAI_API_KEY`` 都未配置。
    """
    if role not in VALID_ROLES:
        raise ValueError(
            f"未知的 LLM role: {role!r}。可选值: {sorted(VALID_ROLES)}"
        )

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not openrouter_key and not openai_key:
        raise RuntimeError(
            "未配置 OPENROUTER_API_KEY 或 OPENAI_API_KEY。"
            "至少需要其中一个才能使用 LLM,请检查 .env 文件。"
        )

    # 模型选择优先级: overrides > env var > default
    env_model = os.getenv(f"LLM_MODEL_{role.upper()}")
    model = overrides.pop("model", None) or env_model or DEFAULT_MODELS[role]

    # base_url / api_key 选择
    custom_base = os.getenv("LLM_BASE_URL")
    if openrouter_key:
        base_url = custom_base or OPENROUTER_BASE_URL
        api_key = openrouter_key
        path = "openrouter"
    else:
        # 降级到 OpenAI 原生端点,且去掉 vendor 前缀(否则 OpenAI 不认)
        base_url = custom_base or OPENAI_BASE_URL
        api_key = openai_key
        model = _strip_vendor_prefix(model)
        path = "openai-fallback"
        logger.info(
            "OPENROUTER_API_KEY 未设置,降级到原生 OpenAI 端点(role=%s, model=%s)",
            role, model,
        )

    # 默认参数
    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "streaming": _str_to_bool(os.getenv("LLM_STREAMING"), default=True),
    }

    # overrides 覆盖一切(api_key / base_url 也允许覆盖,方便测试)
    kwargs.update(overrides)

    logger.debug(
        "构造 LLM: role=%s, path=%s, model=%s, base_url=%s, streaming=%s",
        role, path, kwargs["model"], kwargs["base_url"], kwargs["streaming"],
    )

    return ChatOpenAI(**kwargs)
