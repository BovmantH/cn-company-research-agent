"""统一 LLM 工厂(Phase 2)。

设计目标:
- 通过 ``get_llm(role)`` 获取 LangChain ``BaseChatModel`` 实例
- 后端所有 LLM 调用的唯一入口
- 支持国产模型(DeepSeek / Qwen / Kimi)的官方 OpenAI 兼容端点直连,
  以及 OpenRouter 聚合、OpenAI 原生
- 启动期探测,**单 vendor 全包**:命中第一家 vendor 接管所有 role
- 通过 ``LLM_VENDOR`` 显式锁定可跳过探测,``LLM_VENDOR_PRIORITY`` 调整优先级
- ``LLM_MODEL_<ROLE>`` 解析:vendor=OpenRouter 原样保留 ``vendor/`` 前缀;
  vendor=原厂/OpenAI 时自动剥离前缀(env 触发会 WARN)
- 调用方可通过 ``**overrides`` 临时覆盖任意参数(``model`` / ``base_url`` /
  ``api_key`` / ``temperature`` 等)

环境变量约定:
    # vendor key(任意一个;多个时按优先级)
    DEEPSEEK_API_KEY          DeepSeek 原厂
    DASHSCOPE_API_KEY         阿里百炼(Qwen)
    MOONSHOT_API_KEY          Moonshot(Kimi)
    OPENROUTER_API_KEY        OpenRouter 聚合(Phase 1 主路径)
    OPENAI_API_KEY            OpenAI 原生

    # 选择策略
    LLM_VENDOR                显式锁定 vendor(跳过探测;对应 key 缺失则报错)
    LLM_VENDOR_PRIORITY       逗号分隔覆盖默认优先级,如 "qwen,deepseek,openrouter"

    # 模型与通用参数
    LLM_MODEL_RESEARCHER      researcher 模型 slug
    LLM_MODEL_BRIEFING        briefing 模型 slug
    LLM_MODEL_EDITOR          editor 模型 slug
    LLM_TEMPERATURE           温度,默认 0
    LLM_STREAMING             是否流式,默认 true
    LLM_MAX_TOKENS            响应 max_tokens 上限

    # base_url 覆盖
    LLM_BASE_URL              全局 base_url(优先级最高,所有 vendor 都被覆盖)
    LLM_BASE_URL_<VENDOR>     单 vendor 覆盖,如 LLM_BASE_URL_DEEPSEEK
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


# === Vendor 注册表 ===


@dataclass(frozen=True)
class VendorConfig:
    """单个 vendor 的连接配置。

    Attributes:
        env_key: 触发该 vendor 命中的环境变量名(也是 ``api_key`` 的来源)。
        base_url: 该 vendor 的 OpenAI 协议兼容端点。
        default_models: ``role -> 默认 slug`` 映射(未设 ``LLM_MODEL_<ROLE>`` 时兜底)。
        docs_url: 文档地址,用户排错用。
        strip_role_prefix: 是否对带 ``vendor/`` 前缀的 model 自动剥离。
            OpenRouter 必须保留前缀(它依赖前缀路由 provider),其余均剥离。
    """

    env_key: str
    base_url: str
    default_models: dict[str, str]
    docs_url: str = ""
    strip_role_prefix: bool = True

    def default_model(self, role: str) -> str:
        """取该 role 的默认 slug;若 role 缺失则用 ``default_models`` 第一项兜底。"""
        return self.default_models.get(role, next(iter(self.default_models.values())))


# 入选 vendor 列表。GLM / MiMo / MiniMax 待 §4 兼容性 smoke test 通过后再补。
VENDOR_REGISTRY: dict[str, VendorConfig] = {
    "deepseek": VendorConfig(
        env_key="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1",
        # 注:deepseek-chat / deepseek-reasoner 将于 2026/07/24 退役,
        # 自动路由到 deepseek-v4-flash。新代码直接用 V4 slug。
        default_models={
            "researcher": "deepseek-v4-flash",
            "briefing": "deepseek-v4-flash",
            "editor": "deepseek-v4-flash",
        },
        docs_url="https://api-docs.deepseek.com/",
    ),
    "qwen": VendorConfig(
        env_key="DASHSCOPE_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        # Qwen3 系列(2026 主流):flash 便宜 / plus 性价比 / max 旗舰
        default_models={
            "researcher": "qwen3.6-flash",
            "briefing": "qwen3.6-plus",
            "editor": "qwen3-max",
        },
        docs_url=(
            "https://help.aliyun.com/zh/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
    ),
    "kimi": VendorConfig(
        env_key="MOONSHOT_API_KEY",
        base_url="https://api.moonshot.cn/v1",
        # K2 系列(2026 主流):k2.5 多模态旗舰 / k2-turbo-preview 快速版
        default_models={
            "researcher": "kimi-k2.5",
            "briefing": "kimi-k2-turbo-preview",
            "editor": "kimi-k2.5",
        },
        docs_url="https://platform.moonshot.cn/docs",
    ),
    "mimo": VendorConfig(
        env_key="XIAOMI_API_KEY",
        base_url="https://api.xiaomimimo.com/v1",
        default_models={
            "researcher": "mimo-v2.5-pro",
            "briefing": "mimo-v2.5-pro",
            "editor": "mimo-v2.5-pro",
        },
        docs_url="https://api.xiaomimimo.com/",
    ),
    "openrouter": VendorConfig(
        env_key="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        default_models={
            "researcher": "deepseek/deepseek-v4-flash",
            "briefing": "qwen/qwen3.6-flash",
            "editor": "moonshotai/kimi-k2.6",
        },
        docs_url="https://openrouter.ai/docs",
        strip_role_prefix=False,
    ),
    "openai": VendorConfig(
        env_key="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        default_models={
            "researcher": "gpt-4o-mini",
            "briefing": "gpt-4o-mini",
            "editor": "gpt-4o",
        },
        docs_url="https://platform.openai.com/docs",
    ),
}

# 默认探测顺序:中国用户优先 → OpenRouter 聚合 → OpenAI 兜底
DEFAULT_VENDOR_PRIORITY: list[str] = [
    "deepseek",
    "qwen",
    "kimi",
    "mimo",
    "openrouter",
    "openai",
]

VALID_ROLES = frozenset({"researcher", "briefing", "editor"})

# Phase 1 老导入兼容
OPENROUTER_BASE_URL = VENDOR_REGISTRY["openrouter"].base_url
OPENAI_BASE_URL = VENDOR_REGISTRY["openai"].base_url
DEFAULT_MODELS: dict[str, str] = VENDOR_REGISTRY["openrouter"].default_models


# === 工具 ===


def _str_to_bool(value: str | None, default: bool = False) -> bool:
    """字符串转布尔。空值用 default。"""
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

    未知 vendor 名记录 warning 并丢弃。全部丢弃后回退到默认。
    """
    raw = os.getenv("LLM_VENDOR_PRIORITY")
    if not raw:
        return DEFAULT_VENDOR_PRIORITY

    out: list[str] = []
    for token in raw.split(","):
        v = token.strip().lower()
        if not v:
            continue
        if v not in VENDOR_REGISTRY:
            logger.warning(
                "LLM_VENDOR_PRIORITY 含未知 vendor %r,已忽略。可选值: %s",
                v,
                sorted(VENDOR_REGISTRY.keys()),
            )
            continue
        out.append(v)
    return out or DEFAULT_VENDOR_PRIORITY


def _resolve_vendor() -> tuple[str, str]:
    """返回 ``(vendor 名, api_key)``。

    选择顺序:``LLM_VENDOR`` 显式锁定 > ``LLM_VENDOR_PRIORITY`` 探测。
    全空则抛 ``RuntimeError``,信息列出全部可选 key。
    """
    explicit = os.getenv("LLM_VENDOR", "").strip().lower()
    if explicit:
        if explicit not in VENDOR_REGISTRY:
            raise RuntimeError(
                f"LLM_VENDOR={explicit!r} 不在支持列表内。"
                f"可选值: {sorted(VENDOR_REGISTRY.keys())}"
            )
        cfg = VENDOR_REGISTRY[explicit]
        key = os.getenv(cfg.env_key)
        if not key:
            raise RuntimeError(
                f"LLM_VENDOR={explicit!r} 已显式锁定,但对应环境变量 "
                f"{cfg.env_key} 未配置。请在 .env 中填写该 key,或删除 "
                f"LLM_VENDOR 走自动探测。"
            )
        logger.info("selected vendor=%s via LLM_VENDOR", explicit)
        return explicit, key

    for vendor in _get_priority_list():
        cfg = VENDOR_REGISTRY[vendor]
        key = os.getenv(cfg.env_key)
        if key:
            logger.info("selected vendor=%s via LLM_VENDOR_PRIORITY", vendor)
            return vendor, key

    available = "\n  ".join(
        f"- {VENDOR_REGISTRY[v].env_key}  (vendor: {v})"
        for v in DEFAULT_VENDOR_PRIORITY
    )
    raise RuntimeError(
        "未配置任何 LLM provider 凭证。请在 .env 中至少设置以下其中一个:\n  "
        + available
    )


def _resolve_base_url(vendor: str) -> str:
    """单 vendor 维度 base_url 解析。

    优先级:全局 ``LLM_BASE_URL`` > ``LLM_BASE_URL_<VENDOR>`` > registry 默认。
    """
    global_url = os.getenv("LLM_BASE_URL")
    if global_url:
        return global_url
    per_vendor = os.getenv(f"LLM_BASE_URL_{vendor.upper()}")
    if per_vendor:
        return per_vendor
    return VENDOR_REGISTRY[vendor].base_url


def _resolve_model(role: str, vendor: str, override: str | None) -> str:
    """model slug 解析。

    优先级:overrides > ``LLM_MODEL_<ROLE>`` > ``VendorConfig.default_model(role)``。

    若 vendor 需剥离前缀(OpenRouter 之外)且 model 带 ``vendor/`` 前缀,
    自动剥离;来自 env 的剥离会 WARN(来自 overrides 的不 warn,因为是调用方
    显式指定)。
    """
    env_value = os.getenv(f"LLM_MODEL_{role.upper()}")
    raw = override or env_value or VENDOR_REGISTRY[vendor].default_model(role)

    cfg = VENDOR_REGISTRY[vendor]
    if cfg.strip_role_prefix and "/" in raw:
        stripped = _strip_vendor_prefix(raw)
        if env_value and raw == env_value:
            logger.warning(
                "LLM_MODEL_%s=%r 带 vendor/ 前缀,但选中 vendor=%s 非 OpenRouter,"
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


def get_llm(role: str, **overrides: Any) -> BaseChatModel:
    """根据角色获取一个配置好的 LLM 实例。

    Args:
        role: ``"researcher"`` / ``"briefing"`` / ``"editor"`` 之一。
        **overrides: 任意可覆盖参数(``model``、``base_url``、``api_key``、
            ``temperature``、``streaming``、``max_tokens`` 等)。

    Returns:
        ``langchain_openai.ChatOpenAI`` 实例。所有支持的 vendor 都通过此类
        实例化(全部走 OpenAI 协议兼容端点)。

    Raises:
        ValueError: 未知 role。
        RuntimeError: 所有 vendor key 都未配置;或 ``LLM_VENDOR`` 显式锁定但对应
            key 缺失。
    """
    if role not in VALID_ROLES:
        raise ValueError(f"未知的 LLM role: {role!r}。可选值: {sorted(VALID_ROLES)}")

    vendor, api_key = _resolve_vendor()
    base_url = _resolve_base_url(vendor)
    model_override = overrides.pop("model", None)
    model = _resolve_model(role, vendor, model_override)

    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "streaming": _str_to_bool(os.getenv("LLM_STREAMING"), default=True),
    }

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
