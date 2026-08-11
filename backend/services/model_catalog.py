"""从固定官方端点读取 Web 用户可选择的模型目录。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from .client_model import (
    CLIENT_MODEL_ID_PATTERN,
    CLIENT_MODEL_VENDORS,
    QWEN_RESPONSES_WEB_SEARCH_MODELS,
    SelectedModel,
)

MODEL_CATALOG_TIMEOUT_SECONDS = 15.0
MAX_MODEL_CATALOG_BYTES = 2_000_000
MAX_MODEL_COUNT = 1_000
NON_TEXT_MODEL_MARKERS = (
    "embedding",
    "moderation",
    "rerank",
    "whisper",
    "transcribe",
    "text-to-speech",
    "tts",
    "image",
    "video",
    "dall-e",
    "sora",
    "realtime",
)
OFFICIAL_MODEL_CATALOG_URLS: dict[str, str] = {
    "opencode": "https://opencode.ai/zen/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "kimi": "https://api.moonshot.cn/v1/models",
    "minimax": "https://api.minimaxi.com/v1/models",
    "mimo": "https://api.xiaomimimo.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models/user",
    "openai": "https://api.openai.com/v1/models",
}
DYNAMIC_MODEL_VENDORS = frozenset(OFFICIAL_MODEL_CATALOG_URLS)
# 千问按量推理和智谱当前没有文档化的模型目录接口。这里仅集中保留经过
# 官方模型页核对的推荐项，不调用探测到但未承诺稳定性的兼容路由。
CURATED_MODEL_OPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "qwen": tuple(
        (model_id, model_id.replace("qwen", "Qwen").replace("-", " ").title())
        for model_id in QWEN_RESPONSES_WEB_SEARCH_MODELS
    ),
    "glm": (
        ("glm-4.7", "GLM-4.7"),
        ("glm-5.2", "GLM-5.2"),
        ("glm-4.7-flash", "GLM-4.7 Flash"),
    ),
}


class ModelCatalogError(RuntimeError):
    """模型目录读取失败的安全基类，不携带上游响应正文。"""


class ModelCatalogCredentialError(ModelCatalogError):
    """用户 Key 无法通过官方模型目录鉴权。"""


class ModelCatalogUnavailable(ModelCatalogError):
    """官方模型目录当前不可用或返回了不可信结构。"""


class ModelOption(BaseModel):
    """可安全返回给前端的最小模型信息。"""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str


class ModelCatalog(BaseModel):
    """单个厂商的模型目录及其可信来源。"""

    model_config = ConfigDict(frozen=True)

    vendor: str
    source: Literal["official_api", "curated"]
    models: tuple[ModelOption, ...]


def official_model_catalog_url(vendor: str) -> str:
    """只根据服务端注册表生成官方目录地址，禁止用户传入 URL。"""
    normalized_vendor = vendor.strip().lower()
    if normalized_vendor not in CLIENT_MODEL_VENDORS:
        raise ValueError(f"不支持的模型供应商：{normalized_vendor!r}")
    if normalized_vendor not in DYNAMIC_MODEL_VENDORS:
        raise ValueError("该厂商当前没有文档化的官方模型目录接口")
    return OFFICIAL_MODEL_CATALOG_URLS[normalized_vendor]


def _has_text_output(record: Mapping[str, Any]) -> bool:
    """优先采用目录能力元数据，并排除明显的非文本专用模型。"""
    architecture = record.get("architecture")
    if isinstance(architecture, Mapping):
        output_modalities = architecture.get("output_modalities")
        if isinstance(output_modalities, list) and output_modalities:
            return "text" in output_modalities

    model_id = record.get("id")
    if not isinstance(model_id, str):
        return False
    normalized_id = model_id.lower()
    return not any(marker in normalized_id for marker in NON_TEXT_MODEL_MARKERS)


def _parse_model_options(payload: object) -> list[ModelOption]:
    """将 OpenAI 兼容目录收窄为无敏感字段的文本模型列表。"""
    if not isinstance(payload, Mapping):
        raise ModelCatalogUnavailable("官方模型目录暂时不可用")
    records = payload.get("data")
    if not isinstance(records, list) or not records:
        raise ModelCatalogUnavailable("官方模型目录暂时不可用")

    options: list[ModelOption] = []
    seen: set[str] = set()
    for record in records[:MAX_MODEL_COUNT]:
        if not isinstance(record, Mapping) or not _has_text_output(record):
            continue
        model_id = record.get("id")
        if (
            not isinstance(model_id, str)
            or not CLIENT_MODEL_ID_PATTERN.fullmatch(model_id)
            or model_id in seen
        ):
            continue
        raw_name = record.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else model_id
        if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
            name = model_id
        options.append(ModelOption(id=model_id, name=name[:160]))
        seen.add(model_id)

    if not options:
        raise ModelCatalogUnavailable("官方模型目录暂时不可用")
    return options


class ModelCatalogService:
    """优先读取官方动态目录，无正式接口时使用集中维护的推荐项。"""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _read_catalog(
        self,
        client: httpx.AsyncClient,
        vendor: str,
        url: str,
        api_key: str,
    ) -> tuple[int, bytes]:
        """流式读取受限大小的目录，非成功响应不保留上游正文。"""
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"output_modalities": "text"} if vendor == "openrouter" else None
        async with client.stream(
            "GET", url, headers=headers, params=params
        ) as response:
            status_code = response.status_code
            if status_code != 200:
                return status_code, b""
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_MODEL_CATALOG_BYTES:
                        raise ModelCatalogUnavailable("官方模型目录暂时不可用")
                except ValueError:
                    pass
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_MODEL_CATALOG_BYTES:
                    raise ModelCatalogUnavailable("官方模型目录暂时不可用")
            return status_code, bytes(content)

    async def _get(self, vendor: str, url: str, api_key: str) -> tuple[int, bytes]:
        if self._client is not None:
            return await self._read_catalog(self._client, vendor, url, api_key)
        async with httpx.AsyncClient(
            timeout=MODEL_CATALOG_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            return await self._read_catalog(client, vendor, url, api_key)

    async def list_models(self, vendor: str, api_key: str) -> ModelCatalog:
        """读取模型目录；错误只抛稳定中文类型，不透传 Key 或响应正文。"""
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("用户 API Key 不能为空")
        normalized_vendor = vendor.strip().lower()
        if normalized_vendor not in CLIENT_MODEL_VENDORS:
            raise ValueError(f"不支持的模型供应商：{normalized_vendor!r}")
        curated = CURATED_MODEL_OPTIONS.get(normalized_vendor)
        if curated is not None:
            return ModelCatalog(
                vendor=normalized_vendor,
                source="curated",
                models=tuple(
                    ModelOption(id=model_id, name=name) for model_id, name in curated
                ),
            )

        url = official_model_catalog_url(normalized_vendor)
        request_failed = False
        try:
            status_code, content = await self._get(
                normalized_vendor,
                url,
                normalized_key,
            )
        except httpx.HTTPError:
            request_failed = True
            status_code, content = 0, b""
        if request_failed:
            raise ModelCatalogUnavailable("官方模型目录暂时不可用")

        if status_code in {401, 403}:
            raise ModelCatalogCredentialError("API Key 无效或无权读取官方模型目录")
        if status_code != 200:
            raise ModelCatalogUnavailable("官方模型目录暂时不可用")
        json_failed = False
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, ValueError):
            json_failed = True
            payload = None
        if json_failed:
            raise ModelCatalogUnavailable("官方模型目录暂时不可用")
        return ModelCatalog(
            vendor=normalized_vendor,
            source="official_api",
            models=tuple(_parse_model_options(payload)),
        )

    async def require_model(
        self,
        *,
        vendor: str,
        model: str,
        api_key: str,
    ) -> SelectedModel:
        """再次读取当前目录，确保提交的模型仍属于所选官方厂商。"""
        normalized_vendor = vendor.strip().lower()
        normalized_model = model.strip()
        catalog = await self.list_models(normalized_vendor, api_key)
        if normalized_model not in {option.id for option in catalog.models}:
            source = (
                "官方模型目录" if catalog.source == "official_api" else "推荐模型清单"
            )
            raise ValueError(f"所选模型在厂商当前{source}中不存在")
        return SelectedModel(vendor=normalized_vendor, model=normalized_model)


__all__ = [
    "ModelCatalogCredentialError",
    "ModelCatalogError",
    "ModelCatalog",
    "ModelCatalogService",
    "ModelCatalogUnavailable",
    "ModelOption",
    "SelectedModel",
    "official_model_catalog_url",
]
