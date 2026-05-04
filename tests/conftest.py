"""共享 pytest fixtures。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试开始前,清掉所有可能影响 LLM/搜索 工厂的环境变量。

    确保测试不被本地 .env 或 CI 环境变量干扰。
    """
    for name in [
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
        "SEARCH_PROVIDER",
    ]:
        monkeypatch.delenv(name, raising=False)
