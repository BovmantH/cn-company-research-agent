"""``backend.services.llm_factory.get_llm`` 单元测试。

覆盖:
- OpenRouter 路径(默认)
- OpenAI 降级路径(去 vendor 前缀)
- 缺 key 时明确报错
- 角色隔离(researcher / briefing / editor 互不干扰)
- overrides 覆盖默认参数
- 未知 role 报错
- LLM_BASE_URL 覆盖默认 base_url
- LLM_TEMPERATURE / LLM_STREAMING 行为
"""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from backend.services.llm_factory import (
    DEFAULT_MODELS,
    OPENAI_BASE_URL,
    OPENROUTER_BASE_URL,
    get_llm,
)


# === OpenRouter 路径 ===


def test_openrouter_path_returns_chatopenai_with_correct_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "deepseek/deepseek-chat")

    llm = get_llm("researcher")

    assert isinstance(llm, ChatOpenAI)
    # base_url 在 ChatOpenAI 内部存在 openai_api_base 字段(不同版本字段名可能不同)
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert OPENROUTER_BASE_URL in base_url
    assert llm.model_name == "deepseek/deepseek-chat"


def test_openrouter_default_model_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    # 不设置 LLM_MODEL_RESEARCHER,应该用 default

    llm = get_llm("researcher")

    assert llm.model_name == DEFAULT_MODELS["researcher"]


def test_role_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """3 个角色用不同 env vars,互不影响。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "model-r")
    monkeypatch.setenv("LLM_MODEL_BRIEFING", "model-b")
    monkeypatch.setenv("LLM_MODEL_EDITOR", "model-e")

    assert get_llm("researcher").model_name == "model-r"
    assert get_llm("briefing").model_name == "model-b"
    assert get_llm("editor").model_name == "model-e"


# === OpenAI 降级路径 ===


def test_openai_fallback_when_no_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "gpt-4o-mini")

    llm = get_llm("researcher")

    base_url = str(getattr(llm, "openai_api_base", "") or "")
    # 没设 LLM_BASE_URL → 走 OpenAI 默认
    assert OPENAI_BASE_URL in base_url
    assert llm.model_name == "gpt-4o-mini"


def test_openai_fallback_strips_vendor_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI 降级时,``"openai/gpt-4o" -> "gpt-4o"``。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "openai/gpt-4o")

    llm = get_llm("researcher")

    assert llm.model_name == "gpt-4o"


def test_openrouter_keeps_vendor_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenRouter 路径必须保留 vendor 前缀,因为 OpenRouter 用它选 provider。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MODEL_BRIEFING", "qwen/qwen-2.5-72b-instruct")

    llm = get_llm("briefing")

    assert llm.model_name == "qwen/qwen-2.5-72b-instruct"


# === 错误路径 ===


def test_missing_both_keys_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个 key 都没配,必须给中文报错。"""
    # conftest 已经把这些 env var 清空,这里不需要再 delenv

    with pytest.raises(RuntimeError) as exc_info:
        get_llm("researcher")

    msg = str(exc_info.value)
    assert "OPENROUTER_API_KEY" in msg
    assert "OPENAI_API_KEY" in msg


def test_unknown_role_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    with pytest.raises(ValueError, match="未知的 LLM role"):
        get_llm("unknown_role")


# === overrides ===


def test_overrides_take_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "default-model")

    llm = get_llm("researcher", model="overridden-model", temperature=0.7)

    assert llm.model_name == "overridden-model"
    assert llm.temperature == 0.7


def test_streaming_can_be_disabled_via_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    llm = get_llm("researcher", streaming=False)

    assert llm.streaming is False


# === LLM_BASE_URL 覆盖 ===


def test_custom_base_url_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户走本地 vLLM/Ollama 的场景。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "anything")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "local-model")

    llm = get_llm("researcher")

    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "localhost:8000" in base_url
    assert llm.model_name == "local-model"


# === LLM_TEMPERATURE / LLM_STREAMING ===


def test_temperature_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.42")

    llm = get_llm("researcher")

    assert abs(llm.temperature - 0.42) < 1e-6


def test_streaming_default_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    llm = get_llm("researcher")

    assert llm.streaming is True


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", True),  # 空字符串落到 default=True 之外的分支?conftest 实际删掉了 var
    ],
)
def test_streaming_env_parsing(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    if env_value == "":
        # 空字符串场景:env 存在但为空,_str_to_bool 视作 False
        monkeypatch.setenv("LLM_STREAMING", "")
        llm = get_llm("researcher")
        assert llm.streaming is False
    else:
        monkeypatch.setenv("LLM_STREAMING", env_value)
        llm = get_llm("researcher")
        assert llm.streaming is expected


# === LLM_MAX_TOKENS ===


def test_max_tokens_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_MAX_TOKENS 应注入到 ChatOpenAI 实例,避免 OpenRouter 按模型最大窗口预扣费。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")

    llm = get_llm("researcher")

    # ChatOpenAI 把 max_tokens 存到 max_tokens 字段(LangChain 0.3+)
    assert getattr(llm, "max_tokens", None) == 2048


def test_max_tokens_unset_means_no_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """没设 LLM_MAX_TOKENS 时不传该参数,行为等同上游默认。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    llm = get_llm("researcher")

    # max_tokens 应为 None / 未设定(具体取决于 ChatOpenAI 默认)
    assert getattr(llm, "max_tokens", None) in (None, 0)


def test_max_tokens_invalid_falls_back_silently(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLM_MAX_TOKENS 不是合法整数时,只 warn 不 raise。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MAX_TOKENS", "not-an-int")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher")

    assert getattr(llm, "max_tokens", None) in (None, 0)
    assert any("LLM_MAX_TOKENS" in r.message for r in caplog.records)


def test_max_tokens_override_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """overrides['max_tokens'] 应该覆盖环境变量。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")

    llm = get_llm("researcher", max_tokens=8192)

    assert getattr(llm, "max_tokens", None) == 8192
