"""共享 pytest fixtures。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试开始前,清掉所有可能影响 LLM/搜索 工厂的环境变量。

    确保测试不被本地 .env 或 CI 环境变量干扰。
    """
    names = [
        # 第一阶段
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "TAVILY_API_KEY",
        "LLM_MODEL_RESEARCHER",
        "LLM_MODEL_BRIEFING",
        "LLM_MODEL_EDITOR",
        "LLM_TEMPERATURE",
        "LLM_STREAMING",
        "LLM_BASE_URL",
        "LLM_MAX_TOKENS",
        "SEARCH_PROVIDER",
        # 第二阶段：供应商路由与原厂 Key
        "LLM_VENDOR",
        "LLM_VENDOR_PRIORITY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "ZAI_API_KEY",
        "XIAOMI_API_KEY",
        "MINIMAX_API_KEY",
    ]
    # 单 vendor 维度 base_url 覆盖,全部清掉
    for vendor in (
        "DEEPSEEK",
        "QWEN",
        "KIMI",
        "GLM",
        "MIMO",
        "MINIMAX",
        "OPENROUTER",
        "OPENAI",
    ):
        names.append(f"LLM_BASE_URL_{vendor}")
    for name in names:
        monkeypatch.delenv(name, raising=False)
