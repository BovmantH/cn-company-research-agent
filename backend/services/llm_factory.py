"""统一 LLM 工厂（第二阶段）。

设计目标:
- 通过 ``get_llm(role)`` 获取 LangChain ``BaseChatModel`` 实例
- 后端所有 LLM 调用的唯一入口
- 支持 OpenCode Zen 免费线路、国产模型原厂 OpenAI 兼容端点直连，
  以及 OpenRouter 聚合、OpenAI 原生
- 启动期探测，**单供应商全包**：命中第一家供应商后接管所有角色
- 通过 ``LLM_VENDOR`` 显式锁定可跳过探测,``LLM_VENDOR_PRIORITY`` 调整优先级
- 解析 ``LLM_MODEL_<ROLE>``：OpenRouter 原样保留供应商前缀；
  原厂或 OpenAI 自动剥离前缀（环境变量触发时会记录警告）
- 调用方可通过 ``**overrides`` 临时覆盖任意参数(``model`` / ``base_url`` /
  ``api_key`` / ``temperature`` 等)

环境变量约定:
    # 供应商密钥（任意一个；多个时按优先级）
    OPENCODE_API_KEY          OpenCode Zen
    DEEPSEEK_API_KEY          DeepSeek 原厂
    DASHSCOPE_API_KEY         阿里百炼(Qwen)
    MOONSHOT_API_KEY          Moonshot(Kimi)
    ZAI_API_KEY               智谱 GLM
    MINIMAX_API_KEY           MiniMax
    MIMO_API_KEY              小米 MiMo
    XIAOMI_API_KEY            小米 MiMo 旧变量名（兼容）
    OPENROUTER_API_KEY        OpenRouter 聚合（第一阶段主路径）
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
    LLM_BASE_URL              全局 base_url(优先级最高,所有 vendor 都被覆盖)
    LLM_BASE_URL_<VENDOR>     单 vendor 覆盖,如 LLM_BASE_URL_DEEPSEEK
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    AuthenticationError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


# === Vendor 注册表 ===


@dataclass(frozen=True)
class VendorConfig:
    """单个供应商的连接配置。

    属性:
        display_name: 用于启动错误提示的供应商名称。
        env_keys: 按优先级排列的环境变量名，也是 ``api_key`` 的来源。
        base_url: 该供应商的 OpenAI 协议兼容端点。
        default_models: ``角色 -> 默认模型标识`` 映射（未设 ``LLM_MODEL_<ROLE>`` 时兜底）。
        docs_url: 文档地址,用户排错用。
        strip_role_prefix: 是否自动剥离模型中的供应商前缀。
            OpenRouter 依赖前缀路由，必须保留；其余供应商均剥离。
    """

    display_name: str
    env_keys: tuple[str, ...]
    base_url: str
    default_models: dict[str, str]
    docs_url: str = ""
    strip_role_prefix: bool = True

    def default_model(self, role: str) -> str:
        """获取指定角色的默认模型标识；角色缺失时使用 ``default_models`` 第一项兜底。"""
        return self.default_models.get(role, next(iter(self.default_models.values())))


# 供应商注册表是连接信息、Key 名称和角色默认模型的唯一事实来源。
VENDOR_REGISTRY: dict[str, VendorConfig] = {
    "opencode": VendorConfig(
        display_name="OpenCode Zen 免费线路",
        env_keys=("OPENCODE_API_KEY",),
        base_url="https://opencode.ai/zen/v1",
        default_models={
            "researcher": "deepseek-v4-flash-free",
            "briefing": "deepseek-v4-flash-free",
            "editor": "deepseek-v4-flash-free",
        },
        docs_url="https://opencode.ai/docs/zen",
    ),
    "deepseek": VendorConfig(
        display_name="DeepSeek 原厂",
        env_keys=("DEEPSEEK_API_KEY",),
        base_url="https://api.deepseek.com",
        default_models={
            "researcher": "deepseek-v4-flash",
            "briefing": "deepseek-v4-flash",
            "editor": "deepseek-v4-pro",
        },
        docs_url="https://api-docs.deepseek.com/",
    ),
    "qwen": VendorConfig(
        display_name="阿里百炼（Qwen）",
        env_keys=("DASHSCOPE_API_KEY",),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_models={
            "researcher": "qwen3.7-flash",
            "briefing": "qwen3.7-plus",
            "editor": "qwen3.7-max",
        },
        docs_url=(
            "https://help.aliyun.com/zh/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
    ),
    "kimi": VendorConfig(
        display_name="Moonshot（Kimi）",
        env_keys=("MOONSHOT_API_KEY",),
        base_url="https://api.moonshot.cn/v1",
        default_models={
            "researcher": "kimi-k3",
            "briefing": "kimi-k3",
            "editor": "kimi-k3",
        },
        docs_url="https://platform.kimi.com/docs/models",
    ),
    "glm": VendorConfig(
        display_name="智谱 GLM",
        env_keys=("ZAI_API_KEY",),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        default_models={
            "researcher": "glm-4.7-flash",
            "briefing": "glm-4.7",
            "editor": "glm-5.2",
        },
        docs_url="https://docs.bigmodel.cn/cn/guide/develop/openai/introduction",
    ),
    "minimax": VendorConfig(
        display_name="MiniMax",
        env_keys=("MINIMAX_API_KEY",),
        base_url="https://api.minimaxi.com/v1",
        default_models={
            "researcher": "MiniMax-M3",
            "briefing": "MiniMax-M3",
            "editor": "MiniMax-M3",
        },
        docs_url="https://platform.minimaxi.com/docs/api-reference/text-openai-api",
    ),
    "mimo": VendorConfig(
        display_name="小米 MiMo",
        env_keys=("MIMO_API_KEY", "XIAOMI_API_KEY"),
        base_url="https://api.xiaomimimo.com/v1",
        default_models={
            "researcher": "mimo-v2.5",
            "briefing": "mimo-v2.5",
            "editor": "mimo-v2.5-pro",
        },
        docs_url="https://mimo.mi.com/docs/zh-CN/quick-start/summary/model",
    ),
    "openrouter": VendorConfig(
        display_name="OpenRouter 聚合",
        env_keys=("OPENROUTER_API_KEY",),
        base_url="https://openrouter.ai/api/v1",
        default_models={
            "researcher": "deepseek/deepseek-v4-flash",
            "briefing": "qwen/qwen3.7-plus",
            "editor": "moonshotai/kimi-k3",
        },
        docs_url="https://openrouter.ai/docs",
        strip_role_prefix=False,
    ),
    "openai": VendorConfig(
        display_name="OpenAI 原生兜底",
        env_keys=("OPENAI_API_KEY",),
        base_url="https://api.openai.com/v1",
        default_models={
            "researcher": "gpt-5.6-luna",
            "briefing": "gpt-5.6-terra",
            "editor": "gpt-5.6-sol",
        },
        docs_url="https://developers.openai.com/api/docs/models",
    ),
}

# 默认探测顺序：Zen 免费线路 → 国内原厂 → OpenRouter → OpenAI。
DEFAULT_VENDOR_PRIORITY: list[str] = [
    "opencode",
    "deepseek",
    "kimi",
    "qwen",
    "glm",
    "minimax",
    "mimo",
    "openrouter",
    "openai",
]

VALID_ROLES = frozenset({"researcher", "briefing", "editor"})

# 只处理可归因于上游不可用的异常，避免把本地参数错误或业务缺陷隐藏成付费回退。
FALLBACK_EXCEPTIONS = (
    APIConnectionError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    RateLimitError,
    ConflictError,
    InternalServerError,
)

# 第一阶段旧导入兼容
OPENROUTER_BASE_URL = VENDOR_REGISTRY["openrouter"].base_url
OPENAI_BASE_URL = VENDOR_REGISTRY["openai"].base_url
DEFAULT_MODELS: dict[str, str] = VENDOR_REGISTRY["openrouter"].default_models


def get_llm_credential_candidates() -> tuple[tuple[str, str, str], ...]:
    """从注册表生成启动凭证提示，避免入口文件重复维护供应商清单。"""
    candidates: list[tuple[str, str, str]] = []
    for vendor in DEFAULT_VENDOR_PRIORITY:
        config = VENDOR_REGISTRY[vendor]
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

    未知供应商名称会记录警告并丢弃；全部丢弃后回退到默认顺序。
    """
    raw = os.getenv("LLM_VENDOR_PRIORITY")
    if not raw:
        return DEFAULT_VENDOR_PRIORITY

    # Zen 免费线路按产品约定始终优先；部署者可调整其后的付费供应商顺序。
    out: list[str] = ["opencode"]
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
        has_known_value = True
        if v not in out:
            out.append(v)
    return out if has_known_value else DEFAULT_VENDOR_PRIORITY


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

    available = "\n  ".join(
        f"- {env_key}  (vendor: {vendor})"
        for vendor in DEFAULT_VENDOR_PRIORITY
        for env_key in VENDOR_REGISTRY[vendor].env_keys
    )
    raise RuntimeError(
        "未配置任何 LLM 服务商凭证。请在 .env 中至少设置以下其中一个：\n  " + available
    )


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
) -> BaseChatModel:
    """构造一个供应商隔离的聊天模型实例，防止 Key 或模型串线。"""
    base_url = _resolve_base_url(vendor)
    model = _resolve_model(
        role,
        vendor,
        model_override,
        use_role_env=use_role_env,
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
        # Zen 的免费 DeepSeek 使用 Chat Completions，禁止客户端自动切到 Responses。
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

    logger.debug(
        "构造 LLM: role=%s, vendor=%s, model=%s, base_url=%s, streaming=%s",
        role,
        vendor,
        kwargs["model"],
        kwargs["base_url"],
        kwargs["streaming"],
    )
    return ChatOpenAI(**kwargs)


def get_llm(role: str, **overrides: Any) -> BaseChatModel | Runnable[Any, Any]:
    """根据角色获取一个配置好的 LLM 实例。

    参数:
        role: ``"researcher"`` / ``"briefing"`` / ``"editor"`` 之一。
        **overrides: 任意可覆盖参数(``model``、``base_url``、``api_key``、
            ``temperature``、``streaming``、``max_tokens`` 等)。

    返回:
        单供应商时返回 ``ChatOpenAI``；Zen 与后续供应商同时配置时返回
        首块输出前可回退的 LangChain Runnable。所有候选均走彼此隔离的
        OpenAI 协议兼容端点和服务端 Key。

    抛出:
        ValueError: 未知角色。
        RuntimeError: 所有供应商密钥都未配置；或 ``LLM_VENDOR`` 显式锁定但对应
            密钥缺失。
    """
    if role not in VALID_ROLES:
        raise ValueError(f"未知的 LLM 角色：{role!r}。可选值：{sorted(VALID_ROLES)}")

    vendor, api_key = _resolve_vendor()
    model_override = overrides.pop("model", None)
    explicitly_locked = bool(os.getenv("LLM_VENDOR"))
    primary = _build_chat_model(
        role,
        vendor,
        api_key,
        model_override=model_override,
        # 自动模式下固定使用 Zen 免费模型，避免旧的跨供应商模型配置污染免费线路。
        use_role_env=vendor != "opencode" or explicitly_locked,
        overrides=overrides,
    )

    # 显式锁定或自定义连接边界时保持单供应商语义，避免把覆盖 Key/URL 扇出。
    connection_overridden = bool(os.getenv("LLM_BASE_URL")) or any(
        key in overrides for key in ("api_key", "base_url")
    )
    if vendor != "opencode" or explicitly_locked or connection_overridden:
        return primary

    fallbacks: list[BaseChatModel] = []
    fallback_names: list[str] = []
    for fallback_vendor in _get_priority_list():
        if fallback_vendor == "opencode":
            continue
        fallback_key, _ = _get_vendor_api_key(fallback_vendor)
        if not fallback_key:
            continue
        fallbacks.append(
            _build_chat_model(
                role,
                fallback_vendor,
                fallback_key,
                model_override=None,
                use_role_env=False,
                overrides=overrides,
            )
        )
        fallback_names.append(fallback_vendor)

    if not fallbacks:
        return primary

    logger.info("OpenCode Zen 不可用时将依次回退：%s", fallback_names)
    return primary.with_fallbacks(
        fallbacks,
        exceptions_to_handle=FALLBACK_EXCEPTIONS,
    )
