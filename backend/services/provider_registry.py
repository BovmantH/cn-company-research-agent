"""模型厂商的公开元数据、固定端点和服务端默认模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CatalogSource = Literal["official_api", "curated"]


@dataclass(frozen=True)
class VendorConfig:
    """单个模型厂商的固定配置。"""

    display_name: str
    short_name: str
    description: str
    api_console_url: str
    env_keys: tuple[str, ...]
    base_url: str
    default_models: dict[str, str]
    catalog_source: CatalogSource
    model_catalog_url: str | None = None
    docs_url: str = ""
    strip_role_prefix: bool = True

    def default_model(self, role: str) -> str:
        """获取指定角色的默认模型；未知角色使用首个默认值兜底。"""
        return self.default_models.get(role, next(iter(self.default_models.values())))


# 字典顺序是 Web 展示顺序；工厂会排除必须显式选择的线路。
VENDOR_REGISTRY: dict[str, VendorConfig] = {
    "opencode": VendorConfig(
        display_name="OpenCode Console 按量线路",
        short_name="OpenCode Console",
        description="OpenCode Console 按量模型服务；免费聊天模型仅限 OpenCode 客户端使用。",
        api_console_url="https://opencode.ai/auth",
        env_keys=("OPENCODE_API_KEY",),
        base_url="https://opencode.ai/inference/openai/v1",
        default_models={
            "researcher": "deepseek-v4.1-flash",
            "briefing": "deepseek-v4.1-flash",
            "editor": "deepseek-v4.1-flash",
        },
        catalog_source="official_api",
        model_catalog_url="https://opencode.ai/inference/v1/models",
        docs_url="https://opencode.ai/v2/docs/console/api/inference/",
    ),
    "deepseek": VendorConfig(
        display_name="DeepSeek 原厂",
        short_name="DeepSeek",
        description="DeepSeek 原厂模型服务，使用用户在原厂申请的 API Key。",
        api_console_url="https://platform.deepseek.com/api_keys",
        env_keys=("DEEPSEEK_API_KEY",),
        base_url="https://api.deepseek.com",
        default_models={
            "researcher": "deepseek-flash",
            "briefing": "deepseek-flash",
            "editor": "deepseek-v4-pro",
        },
        catalog_source="official_api",
        model_catalog_url="https://api.deepseek.com/models",
        docs_url="https://api-docs.deepseek.com/",
    ),
    "kimi": VendorConfig(
        display_name="Moonshot（Kimi）",
        short_name="Kimi",
        description="Moonshot AI 提供的 Kimi 模型服务。",
        api_console_url="https://platform.kimi.com/console/api-keys",
        env_keys=("MOONSHOT_API_KEY",),
        base_url="https://api.moonshot.cn/v1",
        default_models={
            "researcher": "kimi-k3.1-pro",
            "briefing": "kimi-k3.1-pro",
            "editor": "kimi-k3.1-pro",
        },
        catalog_source="official_api",
        model_catalog_url="https://api.moonshot.cn/v1/models",
        docs_url="https://platform.kimi.com/docs/models",
    ),
    "qwen": VendorConfig(
        display_name="阿里百炼（Qwen）",
        short_name="Qwen",
        description="阿里云百炼提供的通义千问模型服务。",
        api_console_url=(
            "https://bailian.console.aliyun.com/cn-beijing/?tab=app#/api-key"
        ),
        env_keys=("DASHSCOPE_API_KEY",),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_models={
            "researcher": "qwen3.8-flash",
            "briefing": "qwen3.7-plus",
            "editor": "qwen3.8-max",
        },
        catalog_source="curated",
        docs_url=(
            "https://help.aliyun.com/zh/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
    ),
    "glm": VendorConfig(
        display_name="智谱 GLM",
        short_name="智谱 GLM",
        description="智谱 AI 提供的 GLM 模型服务。",
        api_console_url="https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        env_keys=("ZAI_API_KEY",),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        default_models={
            "researcher": "glm-5.3-flash",
            "briefing": "glm-5.3",
            "editor": "glm-5.3",
        },
        catalog_source="curated",
        docs_url="https://docs.bigmodel.cn/cn/guide/develop/openai/introduction",
    ),
    "minimax": VendorConfig(
        display_name="MiniMax",
        short_name="MiniMax",
        description="MiniMax 提供的原厂模型服务。",
        api_console_url="https://platform.minimax.cn/console/access?tab=api-keys",
        env_keys=("MINIMAX_API_KEY",),
        base_url="https://api.minimax.cn/v1",
        default_models={
            "researcher": "MiniMax-M3.1-Flash",
            "briefing": "MiniMax-M3.1-Flash",
            "editor": "MiniMax-M3.1-Flash",
        },
        catalog_source="official_api",
        model_catalog_url="https://api.minimax.cn/v1/models",
        docs_url="https://platform.minimax.cn/docs/api-reference/text-openai-api",
    ),
    "mimo": VendorConfig(
        display_name="小米 MiMo",
        short_name="小米 MiMo",
        description="小米提供的 MiMo 模型服务。",
        api_console_url="https://platform.xiaomimimo.com/",
        env_keys=("MIMO_API_KEY", "XIAOMI_API_KEY"),
        base_url="https://api.xiaomimimo.com/v1",
        default_models={
            "researcher": "mimo-v2.6-flash",
            "briefing": "mimo-v2.6-flash",
            "editor": "mimo-v2.6-pro",
        },
        catalog_source="official_api",
        model_catalog_url="https://api.xiaomimimo.com/v1/models",
        docs_url="https://mimo.mi.com/docs/zh-CN/quick-start/summary/model",
    ),
    "openrouter": VendorConfig(
        display_name="OpenRouter 聚合",
        short_name="OpenRouter",
        description="OpenRouter 聚合模型线路，可使用账号下有权访问的模型。",
        api_console_url="https://openrouter.ai/settings/keys",
        env_keys=("OPENROUTER_API_KEY",),
        base_url="https://openrouter.ai/api/v1",
        default_models={
            "researcher": "deepseek/deepseek-v4.1-flash",
            "briefing": "qwen/qwen3.7-plus",
            "editor": "moonshotai/kimi-k3.1-pro",
        },
        catalog_source="official_api",
        model_catalog_url="https://openrouter.ai/api/v1/models/user",
        docs_url="https://openrouter.ai/docs",
        strip_role_prefix=False,
    ),
    "openai": VendorConfig(
        display_name="OpenAI 原生兜底",
        short_name="OpenAI",
        description="OpenAI 原生模型服务，作为兼容兜底入口。",
        api_console_url="https://platform.openai.com/api-keys",
        env_keys=("OPENAI_API_KEY",),
        base_url="https://api.openai.com/v1",
        default_models={
            "researcher": "gpt-6-luna",
            "briefing": "gpt-6.1-terra",
            "editor": "gpt-6.1-sol",
        },
        catalog_source="official_api",
        model_catalog_url="https://api.openai.com/v1/models",
        docs_url="https://developers.openai.com/api/docs/models",
    ),
}

CLIENT_MODEL_VENDORS: tuple[str, ...] = tuple(VENDOR_REGISTRY)

__all__ = [
    "CLIENT_MODEL_VENDORS",
    "CatalogSource",
    "VENDOR_REGISTRY",
    "VendorConfig",
]
