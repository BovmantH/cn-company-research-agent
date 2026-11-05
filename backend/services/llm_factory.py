"""统一 LLM 工厂（第二阶段）。

设计目标:
- 通过 ``get_llm(role)`` 获取 LangChain ``BaseChatModel`` 实例
- 后端所有 LLM 调用的唯一入口
- 支持显式选择 OpenCode Console 按量线路、国产模型原厂 OpenAI 兼容端点直连，
  以及 OpenRouter 聚合、OpenAI 原生
- 启动期按服务端配置选择单个供应商，故障不会自动切换到其他账户计费
- 通过 ``LLM_VENDOR`` 显式锁定可跳过探测,``LLM_VENDOR_PRIORITY`` 调整优先级
- 解析 ``LLM_MODEL_<ROLE>``：OpenRouter 原样保留供应商前缀；
  原厂或 OpenAI 自动剥离前缀（环境变量触发时会记录警告）
- 调用方可通过 ``**overrides`` 临时覆盖任意参数(``model`` / ``base_url`` /
  ``api_key`` / ``temperature`` 等)

环境变量约定:
    # 供应商密钥（任意一个；多个时按优先级）
    OPENCODE_API_KEY          OpenCode Console（需要显式 LLM_VENDOR=opencode）
    DEEPSEEK_API_KEY          DeepSeek 原厂
    DASHSCOPE_API_KEY         阿里百炼(Qwen)
    MOONSHOT_API_KEY          Moonshot(Kimi)
    ZAI_API_KEY               智谱 GLM
    MINIMAX_API_KEY           MiniMax
    MIMO_API_KEY              小米 MiMo
    XIAOMI_API_KEY            小米 MiMo 旧变量名（兼容）
    OPENROUTER_API_KEY        OpenRouter 聚合兼容入口
    OPENAI_API_KEY            OpenAI 原生

    # 选择策略
    LLM_VENDOR                显式锁定供应商（跳过探测；对应密钥缺失则报错）
    LLM_VENDOR_PRIORITY       逗号分隔覆盖默认优先级,如 "qwen,deepseek,openrouter"

    # 模型与通用参数
    LLM_MODEL_RESEARCHER      researcher 模型 slug
    LLM_MODEL_BRIEFING        briefing 模型 slug
    LLM_MODEL_EDITOR          editor 模型 slug
    LLM_TEMPERATURE           可选温度；不填时使用供应商默认值
    LLM_STREAMING             是否流式,默认 true
    LLM_MAX_TOKENS            响应 max_tokens 上限

    # base_url 覆盖
    LLM_BASE_URL              全局 base_url(优先级最高)
    LLM_BASE_URL_<VENDOR>     单供应商覆盖,如 LLM_BASE_URL_DEEPSEEK
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any
from urllib.parse import urlsplit

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .client_model import (
    CLIENT_MODEL_ID_PATTERN,
    SelectedModel,
)
from .provider_registry import CLIENT_MODEL_VENDORS, VENDOR_REGISTRY
from .qwen_config import qwen_inference_base_url

logger = logging.getLogger(__name__)


# 默认探测国内原厂、OpenRouter 与 OpenAI；Console 按量线路必须显式选择。
DEFAULT_VENDOR_PRIORITY: list[str] = [
    vendor for vendor in VENDOR_REGISTRY if vendor != "opencode"
]

VALID_ROLES = frozenset({"researcher", "briefing", "editor"})


# 第一阶段旧导入兼容
OPENROUTER_BASE_URL = VENDOR_REGISTRY["openrouter"].base_url
OPENAI_BASE_URL = VENDOR_REGISTRY["openai"].base_url
DEFAULT_MODELS: dict[str, str] = VENDOR_REGISTRY["openrouter"].default_models


def get_llm_credential_candidates() -> tuple[tuple[str, str, str], ...]:
    """从注册表生成启动凭证提示，避免入口文件重复维护供应商清单。"""
    candidates: list[tuple[str, str, str]] = []
    for config in VENDOR_REGISTRY.values():
        for index, env_key in enumerate(config.env_keys):
            label = config.display_name
            if index:
                label = f"{label}（兼容旧变量）"
            candidates.append((env_key, label, config.docs_url))
    return tuple(candidates)


# === 工具 ===


def _str_to_bool(value: str | None, default: bool = False) -> bool:
    """将字符串转换为布尔值；空值使用 ``default``。"""
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes", "y", "on")


def _strip_vendor_prefix(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[-1]
    return model


# === 探测与解析 ===


def _get_priority_list() -> list[str]:
    """解析 ``LLM_VENDOR_PRIORITY``,未设置则用默认顺序。

    未知供应商名称会记录警告并丢弃；全部无效时拒绝启动，避免恢复默认付费顺序。
    """
    raw = os.getenv("LLM_VENDOR_PRIORITY")
    if not raw:
        return DEFAULT_VENDOR_PRIORITY

    out: list[str] = []
    has_known_value = False
    for token in raw.split(","):
        v = token.strip().lower()
        if not v:
            continue
        if v not in VENDOR_REGISTRY:
            logger.warning(
                "LLM_VENDOR_PRIORITY 包含未知供应商 %r，已忽略。可选值：%s",
                v,
                sorted(VENDOR_REGISTRY.keys()),
            )
            continue
        if v == "opencode":
            logger.warning(
                "OpenCode Console 按量线路仅支持显式 LLM_VENDOR=opencode，"
                "已从自动优先级中忽略。"
            )
            continue
        has_known_value = True
        if v not in out:
            out.append(v)
    if not has_known_value:
        raise RuntimeError(
            "LLM_VENDOR_PRIORITY 未包含任何受支持的供应商，"
            "请修正该配置或删除它以使用默认顺序。"
        )
    return out


def _get_vendor_api_key(vendor: str) -> tuple[str | None, str | None]:
    """按注册表优先级读取供应商 Key，并对旧变量名给出无敏感值警告。"""
    config = VENDOR_REGISTRY[vendor]
    for index, env_key in enumerate(config.env_keys):
        value = os.getenv(env_key)
        if not value:
            continue
        if index:
            logger.warning(
                "%s 已兼容但不再推荐，请迁移到 %s。",
                env_key,
                config.env_keys[0],
            )
        return value, env_key
    return None, None


def _resolve_vendor() -> tuple[str, str]:
    """返回 ``(供应商名称, api_key)``。

    选择顺序:``LLM_VENDOR`` 显式锁定 > ``LLM_VENDOR_PRIORITY`` 探测。
    全部为空时抛出 ``RuntimeError``，信息中列出所有可选密钥。
    """
    explicit = os.getenv("LLM_VENDOR", "").strip().lower()
    if explicit:
        if explicit not in VENDOR_REGISTRY:
            raise RuntimeError(
                f"LLM_VENDOR={explicit!r} 不在支持列表内。"
                f"可选值: {sorted(VENDOR_REGISTRY.keys())}"
            )
        cfg = VENDOR_REGISTRY[explicit]
        key, _ = _get_vendor_api_key(explicit)
        if not key:
            expected_keys = " 或 ".join(cfg.env_keys)
            raise RuntimeError(
                f"LLM_VENDOR={explicit!r} 已显式锁定,但对应环境变量 "
                f"{expected_keys} 未配置。请在 .env 中填写该密钥，或删除 "
                f"LLM_VENDOR 走自动探测。"
            )
        logger.info("已通过 LLM_VENDOR 选定供应商：%s", explicit)
        return explicit, key

    for vendor in _get_priority_list():
        key, _ = _get_vendor_api_key(vendor)
        if key:
            logger.info("已按 LLM_VENDOR_PRIORITY 选定供应商：%s", vendor)
            return vendor, key

    if _get_vendor_api_key("opencode")[0]:
        raise RuntimeError(
            "OpenCode Console 不参与自动探测。若要使用该按量线路，"
            "请显式设置 LLM_VENDOR=opencode；免费模型仅限 OpenCode 客户端。"
        )

    available = "\n  ".join(
        f"- {env_key}  (vendor: {vendor})"
        for vendor in VENDOR_REGISTRY
        for env_key in VENDOR_REGISTRY[vendor].env_keys
    )
    raise RuntimeError(
        "未配置任何 LLM 服务商凭证。请在 .env 中至少设置以下其中一个：\n  " + available
    )


def validate_llm_configuration() -> None:
    """离线校验当前供应商选择能否解析到对应 Key，不发起任何模型请求。"""
    _resolve_vendor()


def _resolve_base_url(vendor: str) -> str:
    """解析单个供应商的 ``base_url``。

    优先级:全局 ``LLM_BASE_URL`` > ``LLM_BASE_URL_<VENDOR>`` > registry 默认。
    """
    global_url = os.getenv("LLM_BASE_URL")
    if global_url:
        return global_url
    per_vendor = os.getenv(f"LLM_BASE_URL_{vendor.upper()}")
    if per_vendor:
        return per_vendor
    return VENDOR_REGISTRY[vendor].base_url


def _resolve_model(
    role: str,
    vendor: str,
    override: str | None,
    *,
    use_role_env: bool = True,
) -> str:
    """解析模型标识。

    优先级：覆盖参数 > ``LLM_MODEL_<ROLE>`` > ``VendorConfig.default_model(role)``。

    若供应商需要剥离前缀（OpenRouter 除外）且模型带供应商前缀，则自动剥离；
    环境变量触发时记录警告，调用方通过覆盖参数显式指定时不记录。
    """
    env_value = os.getenv(f"LLM_MODEL_{role.upper()}") if use_role_env else None
    raw = override or env_value or VENDOR_REGISTRY[vendor].default_model(role)

    cfg = VENDOR_REGISTRY[vendor]
    if cfg.strip_role_prefix and "/" in raw:
        stripped = _strip_vendor_prefix(raw)
        if env_value and raw == env_value:
            logger.warning(
                "LLM_MODEL_%s=%r 带供应商前缀，但选中的供应商 %s 不是 OpenRouter，"
                "已自动剥离为 %r。如确实想走 OpenRouter,请设 LLM_VENDOR=openrouter "
                "或仅保留 OPENROUTER_API_KEY。",
                role.upper(),
                raw,
                vendor,
                stripped,
            )
        return stripped
    return raw


# === 主入口 ===


def _build_chat_model(
    role: str,
    vendor: str,
    api_key: str,
    *,
    model_override: str | None,
    use_role_env: bool,
    overrides: dict[str, Any],
    fixed_base_url: str | None = None,
    exact_model_id: str | None = None,
) -> BaseChatModel:
    """构造一个供应商隔离的聊天模型实例，防止 Key 或模型串线。"""
    base_url = fixed_base_url or _resolve_base_url(vendor)
    model = exact_model_id or _resolve_model(
        role,
        vendor,
        model_override,
        use_role_env=use_role_env,
    )

    if vendor == "opencode" and model.lower().endswith(("-free", ":free")):
        raise ValueError(
            "免费模型仅限 OpenCode 客户端，本项目请使用 Console 按量模型。"
        )

    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "streaming": _str_to_bool(os.getenv("LLM_STREAMING"), default=True),
    }
    if "temperature" not in overrides:
        temperature_env = os.getenv("LLM_TEMPERATURE")
        if temperature_env:
            try:
                temperature = float(temperature_env)
            except ValueError:
                raise ValueError(
                    f"LLM_TEMPERATURE={temperature_env!r} 不是合法数字。"
                ) from None
            if not math.isfinite(temperature):
                raise ValueError(f"LLM_TEMPERATURE={temperature_env!r} 不是有限数字。")
            kwargs["temperature"] = temperature
    if vendor == "opencode":
        # Console 的当前聊天模型走 Chat Completions，禁止客户端自动切换协议。
        kwargs["use_responses_api"] = False
    if vendor == "minimax":
        # MiniMax 原始响应可能把思考过程混入正文，显式要求拆分 reasoning_content。
        kwargs["extra_body"] = {"reasoning_split": True}

    max_tokens_env = os.getenv("LLM_MAX_TOKENS")
    if max_tokens_env:
        try:
            kwargs["max_tokens"] = int(max_tokens_env)
        except ValueError:
            logger.warning("LLM_MAX_TOKENS=%r 不是合法整数,已忽略", max_tokens_env)

    kwargs.update(overrides)

    # 新推理模型不接受采样参数；不把部署者的通用温度强加给用户所选模型。
    if (
        (
            vendor == "openai"
            and model.startswith(("gpt-5", "gpt-6"))
            and kwargs.get("reasoning_effort") != "none"
        )
        or (vendor == "glm" and model.startswith("glm-5.3"))
        or (vendor == "kimi" and model.startswith("kimi-k3"))
        or (vendor == "mimo" and model.startswith("mimo-v2.6"))
    ):
        for parameter in ("temperature", "top_p", "top_logprobs", "logprobs"):
            kwargs.pop(parameter, None)

    parsed_base_url = urlsplit(str(kwargs["base_url"]))
    endpoint = (
        f"{parsed_base_url.scheme}://{parsed_base_url.hostname}"
        if parsed_base_url.scheme and parsed_base_url.hostname
        else "<自定义端点>"
    )
    logger.debug(
        "构造 LLM: role=%s, vendor=%s, model=%s, base_url=%s, streaming=%s",
        role,
        vendor,
        kwargs["model"],
        endpoint,
        kwargs["streaming"],
    )
    return ChatOpenAI(**kwargs)


def build_client_llm(
    *,
    role: str,
    selection: SelectedModel,
    api_key: str,
    streaming: bool,
    workspace_id: str | None = None,
) -> BaseChatModel:
    """为单次 Web 调研构造固定厂商模型，不读取服务端厂商选择或执行回退。"""
    if role not in VALID_ROLES:
        raise ValueError(f"未知的 LLM 角色：{role!r}。可选值：{sorted(VALID_ROLES)}")

    normalized_vendor = selection.vendor.strip().lower()
    if normalized_vendor not in CLIENT_MODEL_VENDORS:
        raise ValueError(f"不支持的用户模型供应商：{normalized_vendor!r}")
    if workspace_id and normalized_vendor != "qwen":
        raise ValueError("业务空间 ID 仅适用于百炼")

    normalized_model = selection.model.strip()
    if not CLIENT_MODEL_ID_PATTERN.fullmatch(normalized_model):
        raise ValueError("用户模型标识格式不合法")

    normalized_key = api_key.strip()
    if not normalized_key:
        raise ValueError("用户 API Key 不能为空")

    return _build_chat_model(
        role,
        normalized_vendor,
        normalized_key,
        model_override=normalized_model,
        use_role_env=False,
        overrides={"streaming": streaming},
        fixed_base_url=(
            qwen_inference_base_url(workspace_id)
            if normalized_vendor == "qwen"
            else VENDOR_REGISTRY[normalized_vendor].base_url
        ),
        exact_model_id=normalized_model,
    )


def get_llm(role: str, **overrides: Any) -> BaseChatModel:
    """根据角色构造一个供应商隔离的 LLM，不自动切换到其他账户。

    参数:
        role: ``"researcher"`` / ``"briefing"`` / ``"editor"`` 之一。
        **overrides: 单次调用覆盖参数，例如模型、连接和生成参数。
    """
    if role not in VALID_ROLES:
        raise ValueError(f"未知的 LLM 角色：{role!r}。可选值：{sorted(VALID_ROLES)}")

    vendor, api_key = _resolve_vendor()
    return _build_chat_model(
        role,
        vendor,
        api_key,
        model_override=overrides.pop("model", None),
        use_role_env=True,
        overrides=overrides,
    )
