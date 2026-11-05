"""``backend.services.llm_factory.get_llm`` 单元测试。

覆盖:
- OpenCode Console 仅显式选择与禁用跨供应商付费回退
- 国内原厂、OpenRouter 和 OpenAI 单供应商路径
- 缺少密钥时明确报错
- 角色隔离（researcher / briefing / editor 互不干扰）
- 覆盖参数优先于默认参数
- 未知角色报错
- LLM_BASE_URL 覆盖默认 base_url
- LLM_TEMPERATURE / LLM_STREAMING 行为
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    RunnableGenerator,
    RunnableLambda,
)
from langchain_openai import ChatOpenAI
from openai import PermissionDeniedError

import backend.services.llm_factory as llm_factory
from backend.services.client_model import SelectedModel
from backend.services.llm_factory import (
    CLIENT_MODEL_VENDORS,
    DEFAULT_MODELS,
    DEFAULT_VENDOR_PRIORITY,
    OPENAI_BASE_URL,
    OPENROUTER_BASE_URL,
    build_client_llm,
    get_llm,
    get_llm_credential_candidates,
)

# === Web 用户任务级模型 ===


def test_client_llm_uses_selected_vendor_model_and_official_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://proxy.example.invalid/v1")

    llm = build_client_llm(
        role="researcher",
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
        api_key="sk-user-qwen",
        streaming=True,
    )

    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "qwen3.7-plus"
    assert "dashscope.aliyuncs.com/compatible-mode/v1" in str(
        getattr(llm, "openai_api_base", "") or ""
    )
    assert "proxy.example.invalid" not in str(getattr(llm, "openai_api_base", "") or "")
    assert "sk-user-qwen" not in repr(llm)


def test_client_llm_rejects_unknown_vendor() -> None:
    with pytest.raises(ValueError, match="不支持的用户模型供应商"):
        build_client_llm(
            role="researcher",
            selection=SelectedModel(
                vendor="custom",
                model="deepseek-v4-flash",
            ),
            api_key="sk-test",
            streaming=True,
        )


def test_client_llm_preserves_dynamically_validated_model_id() -> None:
    llm = build_client_llm(
        role="editor",
        selection=SelectedModel(vendor="qwen", model="namespace/report-model"),
        api_key="sk-test",
        streaming=True,
    )

    assert llm.model_name == "namespace/report-model"


def test_client_model_vendors_match_fixed_official_hosts() -> None:
    assert CLIENT_MODEL_VENDORS == (
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


# === OpenCode Console 显式按量选择 ===


def test_opencode_key_alone_requires_explicit_vendor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")

    with pytest.raises(RuntimeError, match="LLM_VENDOR=opencode"):
        get_llm("editor")


def test_automatic_selection_skips_opencode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")

    llm = get_llm("researcher")

    assert isinstance(llm, ChatOpenAI)
    assert "api.deepseek.com" in str(llm.openai_api_base)
    assert llm.openai_api_key.get_secret_value() == "sk-deepseek-test"


def test_priority_cannot_silently_enable_opencode(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("LLM_VENDOR_PRIORITY", "opencode,deepseek")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher")

    assert isinstance(llm, ChatOpenAI)
    assert "api.deepseek.com" in str(llm.openai_api_base)
    assert "LLM_VENDOR=opencode" in caplog.text
    assert "sk-opencode-test" not in caplog.text


def test_priority_with_only_opencode_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("LLM_VENDOR_PRIORITY", "opencode")

    with pytest.raises(RuntimeError, match="LLM_VENDOR_PRIORITY"):
        get_llm("researcher")


def test_explicit_opencode_uses_paid_console_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")

    llm = get_llm("researcher")

    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "deepseek-v4.1-flash"
    assert str(llm.openai_api_base).rstrip("/") == (
        "https://opencode.ai/inference/openai/v1"
    )
    assert llm.openai_api_key.get_secret_value() == "sk-opencode-test"


@pytest.mark.parametrize(
    "model",
    ["deepseek-v4-flash-free", "deepseek-v4.1-flash-free", "vendor/model:free"],
)
def test_opencode_free_routes_are_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")

    with pytest.raises(ValueError, match="免费模型仅限 OpenCode 客户端"):
        get_llm("researcher", model=model)


def test_explicit_opencode_permission_error_does_not_call_another_vendor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    constructed: list[dict[str, object]] = []

    def fake_chat_openai(**kwargs: object) -> RunnableLambda:
        constructed.append(kwargs)

        def reject(_: object) -> str:
            request = httpx.Request(
                "POST",
                "https://opencode.ai/inference/openai/v1/chat/completions",
            )
            raise PermissionDeniedError(
                "厂商拒绝请求",
                response=httpx.Response(403, request=request),
                body=None,
            )

        return RunnableLambda(reject)

    monkeypatch.setattr(llm_factory, "ChatOpenAI", fake_chat_openai)

    with pytest.raises(PermissionDeniedError):
        get_llm("researcher", model="paygo-report-model").invoke("调研请求")

    assert len(constructed) == 1
    assert constructed[0]["api_key"] == "sk-opencode-test"


@pytest.mark.asyncio
async def test_lcel_message_stream_keeps_single_selected_provider_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")

    async def report_stream(
        _: AsyncIterator[object],
    ) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="公司")
        yield AIMessageChunk(content="报告")

    monkeypatch.setattr(
        llm_factory,
        "ChatOpenAI",
        lambda **_kwargs: RunnableGenerator(report_stream),
    )
    chain = (
        ChatPromptTemplate.from_template("调研 {company}")
        | get_llm("editor", model="paygo-report-model")
        | StrOutputParser()
    )

    assert [chunk async for chunk in chain.astream({"company": "示例公司"})] == [
        "公司",
        "报告",
    ]


def test_blank_explicit_vendor_keeps_automatic_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", "   ")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")

    llm = get_llm("researcher")

    assert isinstance(llm, ChatOpenAI)
    assert "api.deepseek.com" in str(llm.openai_api_base)


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
    # 不设置 LLM_MODEL_RESEARCHER 时应该使用默认值

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
    """所有 Key 都没配时必须给出中文报错。"""
    # conftest 已经把这些 env var 清空,这里不需要再 delenv

    with pytest.raises(RuntimeError) as exc_info:
        get_llm("researcher")

    msg = str(exc_info.value)
    assert "OPENROUTER_API_KEY" in msg
    assert "OPENAI_API_KEY" in msg


def test_unknown_role_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    with pytest.raises(ValueError, match="未知的 LLM 角色"):
        get_llm("unknown_role")


# === 覆盖参数 ===


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


def test_custom_base_url_is_sanitized_in_debug_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "anything")
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "https://user:password@example.com/v1/path-secret?token=query-secret",
    )

    with caplog.at_level("DEBUG", logger=llm_factory.__name__):
        get_llm("researcher")

    messages = "\n".join(record.message for record in caplog.records)
    assert "https://example.com" in messages
    for secret in ("user", "password", "path-secret", "query-secret"):
        assert secret not in messages


# === LLM_TEMPERATURE / LLM_STREAMING ===


def test_temperature_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.42")

    llm = get_llm("researcher")

    assert abs(llm.temperature - 0.42) < 1e-6


@pytest.mark.parametrize(
    ("vendor", "env_key"),
    [
        ("kimi", "MOONSHOT_API_KEY"),
        ("glm", "ZAI_API_KEY"),
        ("minimax", "MINIMAX_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
    ],
)
def test_temperature_is_omitted_by_default(
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    env_key: str,
) -> None:
    monkeypatch.setenv("LLM_VENDOR", vendor)
    monkeypatch.setenv(env_key, "sk-provider-test")

    llm = get_llm("researcher")

    assert llm.temperature is None


def test_invalid_temperature_has_chinese_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-provider-test")
    monkeypatch.setenv("LLM_TEMPERATURE", "不是数字")

    with pytest.raises(ValueError, match="LLM_TEMPERATURE.*不是合法数字"):
        get_llm("researcher")


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
        ("", True),  # 空字符串走默认值为 True 之外的分支；conftest 实际会删除该变量
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
    """显式传入的 ``max_tokens`` 应该覆盖环境变量。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")

    llm = get_llm("researcher", max_tokens=8192)

    assert getattr(llm, "max_tokens", None) == 8192


# === 第二阶段：供应商探测 ===


@pytest.mark.parametrize(
    ("role", "expected_model"),
    [
        ("researcher", "deepseek-v4-flash"),
        ("briefing", "deepseek-v4-flash"),
        ("editor", "deepseek-v4-pro"),
    ],
)
def test_detect_deepseek_only(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    expected_model: str,
) -> None:
    """仅配 DEEPSEEK_API_KEY 时,所有 role 都走 DeepSeek 原厂。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

    llm = get_llm(role)

    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert base_url.rstrip("/") == "https://api.deepseek.com"
    assert "/" not in llm.model_name
    assert llm.model_name == expected_model


def test_detect_qwen_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    llm = get_llm("editor")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "dashscope.aliyuncs.com" in base_url
    assert llm.model_name == "qwen3.7-max"


def test_detect_kimi_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi-test")

    llm = get_llm("briefing")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.moonshot.cn" in base_url
    assert llm.model_name == "kimi-k3"


def test_kimi_editor_uses_current_flagship(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi-test")

    llm = get_llm("editor")

    assert llm.model_name == "kimi-k3"


def test_detect_mimo_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XIAOMI_API_KEY", "tp-mimo-test")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.xiaomimimo.com" in base_url
    assert llm.model_name == "mimo-v2.5"


def test_detect_mimo_official_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIMO_API_KEY", "sk-mimo-official")

    llm = get_llm("editor")

    assert llm.model_name == "mimo-v2.5-pro"
    assert llm.openai_api_key.get_secret_value() == "sk-mimo-official"


def test_mimo_official_key_precedes_legacy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MIMO_API_KEY", "sk-mimo-official")
    monkeypatch.setenv("XIAOMI_API_KEY", "sk-mimo-legacy")

    llm = get_llm("researcher")

    assert llm.openai_api_key.get_secret_value() == "sk-mimo-official"


def test_mimo_legacy_key_warns_without_exposing_value(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("XIAOMI_API_KEY", "sk-mimo-legacy-secret")

    with caplog.at_level("WARNING"):
        get_llm("researcher")

    messages = "\n".join(record.message for record in caplog.records)
    assert "XIAOMI_API_KEY" in messages
    assert "MIMO_API_KEY" in messages
    assert "sk-mimo-legacy-secret" not in messages


@pytest.mark.parametrize(
    ("env_key", "role", "expected_host", "expected_model"),
    [
        ("ZAI_API_KEY", "researcher", "open.bigmodel.cn", "glm-4.7-flash"),
        ("ZAI_API_KEY", "briefing", "open.bigmodel.cn", "glm-4.7"),
        ("ZAI_API_KEY", "editor", "open.bigmodel.cn", "glm-5.2"),
        ("MINIMAX_API_KEY", "researcher", "api.minimaxi.com", "MiniMax-M3"),
        ("MINIMAX_API_KEY", "briefing", "api.minimaxi.com", "MiniMax-M3"),
        ("MINIMAX_API_KEY", "editor", "api.minimaxi.com", "MiniMax-M3"),
    ],
)
def test_detect_new_domestic_vendors(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    role: str,
    expected_host: str,
    expected_model: str,
) -> None:
    monkeypatch.setenv(env_key, "sk-provider-test")

    llm = get_llm(role)

    assert expected_host in str(getattr(llm, "openai_api_base", "") or "")
    assert llm.model_name == expected_model


def test_minimax_separates_reasoning_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax-test")

    llm = get_llm("editor")

    assert llm.extra_body == {"reasoning_split": True}


def test_mimo_token_plan_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL_MIMO 切到 token plan 充值版端点。"""
    monkeypatch.setenv("XIAOMI_API_KEY", "tp-mimo-test")
    monkeypatch.setenv("LLM_BASE_URL_MIMO", "https://token-plan-cn.xiaomimimo.com/v1")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "token-plan-cn.xiaomimimo.com" in base_url


# === 第二阶段：优先级 ===


def test_priority_default_picks_deepseek_over_qwen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek + Qwen 共存时按默认优先级命中 DeepSeek。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    llm = get_llm("researcher")
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.deepseek.com" in base_url


def test_priority_default_picks_kimi_over_qwen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")

    llm = get_llm("researcher")

    base_url = str(getattr(llm, "openai_api_base", "") or "")
    assert "api.moonshot.cn" in base_url


def test_default_vendor_priority_matches_product_order() -> None:
    assert DEFAULT_VENDOR_PRIORITY == [
        "deepseek",
        "kimi",
        "qwen",
        "glm",
        "minimax",
        "mimo",
        "openrouter",
        "openai",
    ]


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


def test_priority_all_unknown_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自定义顺序全部无效时不得恢复默认付费顺序。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("LLM_VENDOR_PRIORITY", "wenxin,baichuan")

    with pytest.raises(RuntimeError, match="LLM_VENDOR_PRIORITY"):
        get_llm("researcher")


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


# === 第二阶段：显式锁定 ===


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


# === 第二阶段：前缀剥离 ===


def test_prefix_stripped_for_direct_vendor_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """使用 DeepSeek 时剥离 LLM_MODEL_RESEARCHER 中的供应商前缀并记录警告。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    monkeypatch.setenv("LLM_MODEL_RESEARCHER", "deepseek/deepseek-v4-flash")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher")

    assert llm.model_name == "deepseek-v4-flash"
    assert any(
        "LLM_MODEL_RESEARCHER" in r.message and "供应商前缀" in r.message
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
    """显式传入带前缀的模型时剥离前缀，但不记录警告。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")

    with caplog.at_level("WARNING"):
        llm = get_llm("researcher", model="deepseek/some-slug")

    assert llm.model_name == "some-slug"
    assert not any("vendor/" in r.message for r in caplog.records)


# === 第二阶段：单供应商维度的 base_url 覆盖 ===


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


# === 第二阶段：启动校验报错文案 ===


def test_all_keys_missing_lists_all_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有 key 全空时,RuntimeError 应列出 DeepSeek/Qwen/Kimi/OpenRouter/OpenAI 全部。"""
    # conftest 已经清空全部 env

    with pytest.raises(RuntimeError) as exc_info:
        get_llm("researcher")

    msg = str(exc_info.value)
    for env_key in (
        "OPENCODE_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "MIMO_API_KEY",
        "XIAOMI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert env_key in msg, f"报错信息缺少 {env_key}"


def test_credential_candidates_are_derived_from_registry() -> None:
    candidates = get_llm_credential_candidates()
    env_names = [name for name, _, _ in candidates]

    assert env_names == [
        "OPENCODE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "DASHSCOPE_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "MIMO_API_KEY",
        "XIAOMI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]


@pytest.mark.parametrize(
    ("vendor", "role", "expected_model"),
    [
        ("openrouter", "researcher", "deepseek/deepseek-v4-flash"),
        ("openrouter", "briefing", "qwen/qwen3.7-plus"),
        ("openrouter", "editor", "moonshotai/kimi-k3"),
        ("openai", "researcher", "gpt-5.6-luna"),
        ("openai", "briefing", "gpt-5.6-terra"),
        ("openai", "editor", "gpt-5.6-sol"),
    ],
)
def test_fallback_vendor_current_default_models(
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    role: str,
    expected_model: str,
) -> None:
    env_key = "OPENROUTER_API_KEY" if vendor == "openrouter" else "OPENAI_API_KEY"
    monkeypatch.setenv("LLM_VENDOR", vendor)
    monkeypatch.setenv(env_key, "sk-provider-test")

    llm = get_llm(role)

    assert llm.model_name == expected_model
