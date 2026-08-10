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


# === Phase 2: vendor 探测 ===


def test_detect_deepseek_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅配 DEEPSEEK_API_KEY 时,所有 role 都走 DeepSeek 原厂。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

    for role in ("researcher", "briefing", "editor"):
        llm = get_llm(role)
        base_url = str(getattr(llm, "openai_api_base", "") or "")
        assert "api.deepseek.com" in base_url
        # 默认 slug 应该是 DeepSeek 原厂 slug,而非 OpenRouter 前缀
        assert "/" not in llm.model_name
        assert llm.model_name == "deepseek-v4-flash"


def test_detect_qwen_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    llm = get_llm("editor")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "dashscope.aliyuncs.com" in base_url
    assert llm.model_name == "qwen3-max"


def test_detect_kimi_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi-test")

    llm = get_llm("briefing")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.moonshot.cn" in base_url
    assert llm.model_name == "kimi-k2-turbo-preview"


def test_detect_mimo_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XIAOMI_API_KEY", "tp-mimo-test")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.xiaomimimo.com" in base_url
    assert llm.model_name == "mimo-v2.5-pro"


def test_mimo_token_plan_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL_MIMO 切到 token plan 充值版端点。"""
    monkeypatch.setenv("XIAOMI_API_KEY", "tp-mimo-test")
    monkeypatch.setenv("LLM_BASE_URL_MIMO", "https://token-plan-cn.xiaomimimo.com/v1")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "token-plan-cn.xiaomimimo.com" in base_url


# === Phase 2: 优先级 ===


def test_priority_default_picks_deepseek_over_qwen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek + Qwen 共存时按默认优先级命中 DeepSeek。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.deepseek.com" in base_url


def test_priority_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_VENDOR_PRIORITY=qwen,deepseek 让 Qwen 胜出。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")
    monkeypatch.setenv("LLM_VENDOR_PRIORITY", "qwen,deepseek")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "dashscope.aliyuncs.com" in base_url


def test_priority_unknown_vendor_ignored(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLM_VENDOR_PRIORITY 含未知 vendor 名时记录 warning 并跳过。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("LLM_VENDOR_PRIORITY", "wenxin,deepseek")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher")

    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.deepseek.com" in base_url
    assert any("wenxin" in r.message for r in caplog.records)


def test_priority_phase1_compat_openrouter_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 1 配置(仅 OPENROUTER_API_KEY)行为零破坏。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "deepseek/deepseek-v4-flash")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert OPENROUTER_BASE_URL in base_url
    # OpenRouter 必须保留 vendor/ 前缀
    assert llm.model_name == "deepseek/deepseek-v4-flash"


# === Phase 2: 显式锁定 ===


def test_explicit_lock_uses_locked_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_VENDOR=qwen 锁定后忽略 DeepSeek key,即使后者在默认优先级更靠前。"""
    monkeypatch.setenv("LLM_VENDOR", "qwen")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "dashscope.aliyuncs.com" in base_url


def test_explicit_lock_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_VENDOR=deepseek 但 DEEPSEEK_API_KEY 缺失 → RuntimeError,不退回探测。"""
    monkeypatch.setenv("LLM_VENDOR", "deepseek")
    # 配了 Qwen key,但 LLM_VENDOR 锁死了 deepseek,不应退回
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    with pytest.raises(RuntimeError) as exc_info:
        get_llm("researcher")

    msg = str(exc_info.value)
    assert "LLM_VENDOR" in msg
    assert "DEEPSEEK_API_KEY" in msg


def test_explicit_lock_unknown_vendor_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_VENDOR=wenxin(未支持)→ RuntimeError 列出支持列表。"""
    monkeypatch.setenv("LLM_VENDOR", "wenxin")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

    with pytest.raises(RuntimeError, match="不在支持列表"):
        get_llm("researcher")


def test_explicit_lock_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_VENDOR 大小写不敏感。"""
    monkeypatch.setenv("LLM_VENDOR", "DeepSeek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.deepseek.com" in base_url


# === Phase 2: 前缀剥离 ===


def test_prefix_stripped_for_direct_vendor_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """vendor=DeepSeek 但 LLM_MODEL_RESEARCHER 带 vendor/ 前缀 → 剥离 + WARN。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "deepseek/deepseek-v4-flash")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher")

    assert llm.model_name == "deepseek-v4-flash"
    assert any(
        "LLM_MODEL_RESEARCHER" in r.message and "vendor/" in r.message
        for r in caplog.records
    )


def test_prefix_kept_for_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    """vendor=OpenRouter 时 vendor/ 前缀必须原样保留(回归)。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "deepseek/deepseek-v4-flash")

    llm = get_llm("researcher")

    assert llm.model_name == "deepseek/deepseek-v4-flash"


def test_prefix_override_does_not_warn(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """通过 overrides 显式传带前缀的 model → 剥离但不 warn(调用方明示)。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher", model="deepseek/some-slug")

    assert llm.model_name == "some-slug"
    assert not any("vendor/" in r.message for r in caplog.records)


# === Phase 2: 单 vendor 维度 base_url 覆盖 ===


def test_per_vendor_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL_DEEPSEEK 覆盖 DeepSeek 默认 base_url。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("LLM_BASE_URL_DEEPSEEK", "http://localhost:3000/v1")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "localhost:3000" in base_url


def test_global_base_url_beats_per_vendor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_BASE_URL 全局优先于 LLM_BASE_URL_<VENDOR>。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("LLM_BASE_URL", "http://global-gateway/v1")
    monkeypatch.setenv("LLM_BASE_URL_DEEPSEEK", "http://deepseek-gateway/v1")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "global-gateway" in base_url


def test_per_vendor_base_url_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL_DEEPSEEK 不影响 Qwen 选中时的 base_url。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")
    monkeypatch.setenv("LLM_BASE_URL_DEEPSEEK", "http://localhost:3000/v1")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "dashscope.aliyuncs.com" in base_url


# === Phase 2: 启动校验报错文案 ===


def test_all_keys_missing_lists_all_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有 key 全空时,RuntimeError 应列出 DeepSeek/Qwen/Kimi/OpenRouter/OpenAI 全部。"""
    # conftest 已经清空全部 env

    with pytest.raises(RuntimeError) as exc_info:
        get_llm("researcher")

    msg = str(exc_info.value)
    for env_key in (
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "XIAOMI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert env_key in msg, f"报错信息缺少 {env_key}"
