"""从固定官方端点读取 Web 用户可选择的模型目录。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from .client_model import (
    CLIENT_MODEL_ID_PATTERN,
    GLM_WEB_SEARCH_MODELS,
    QWEN_RESPONSES_WEB_SEARCH_MODELS,
    WEB_SEARCH_MODEL_ALLOWLISTS,
    SelectedModel,
)
from .provider_registry import CLIENT_MODEL_VENDORS, VENDOR_REGISTRY
from .qwen_config import normalize_qwen_workspace_id

MODEL_CATALOG_TIMEOUT_SECONDS = 15.0
MAX_MODEL_CATALOG_BYTES = 2_000_000
MAX_MODEL_COUNT = 1_000
OPENROUTER_RESEARCH_ENDPOINTS = frozenset(
    {"/api/v1/chat/completions", "/api/v1/responses"}
)
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
    vendor: config.model_catalog_url
    for vendor, config in VENDOR_REGISTRY.items()
    if config.model_catalog_url is not None
}
DYNAMIC_MODEL_VENDORS = frozenset(OFFICIAL_MODEL_CATALOG_URLS)
# 百炼未指定业务空间时使用推荐清单；智谱暂未找到正式目录接口。
CURATED_MODEL_OPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "qwen": tuple(
        (model_id, model_id.replace("qwen", "Qwen").replace("-", " ").title())
        for model_id in QWEN_RESPONSES_WEB_SEARCH_MODELS
    ),
    "glm": tuple(
        (
            model_id,
            model_id.replace("glm-", "GLM-").replace("-flash", " Flash"),
        )
        for model_id in GLM_WEB_SEARCH_MODELS
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
    if "output_modalities" in record:
        return (
            isinstance(record["output_modalities"], list)
            and "text" in record["output_modalities"]
        )
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


def _supports_openrouter_research(record: Mapping[str, Any]) -> bool:
    """只开放同时支持当前生成、托管检索协议且未到期的模型。"""
    supported_parameters = record.get("supported_parameters")
    endpoints = record.get("endpoints")
    if (
        not isinstance(supported_parameters, list)
        or not all(isinstance(value, str) for value in supported_parameters)
        or not {"tools", "tool_choice"}.issubset(supported_parameters)
        or not isinstance(endpoints, list)
        or not all(isinstance(value, str) for value in endpoints)
        or not OPENROUTER_RESEARCH_ENDPOINTS.issubset(endpoints)
    ):
        return False

    expiration = record.get("expiration_date")
    if expiration is None:
        return True
    if not isinstance(expiration, str) or len(expiration) != 10:
        return False
    try:
        # 官方目录使用日期；到期当日保守停用，不把未知时间推迟成仍可调用。
        return date.fromisoformat(expiration) > datetime.now(UTC).date()
    except ValueError:
        return False


def _parse_model_options(payload: object, vendor: str) -> list[ModelOption]:
    """将 OpenAI 兼容目录收窄为无敏感字段的文本模型列表。"""
    if not isinstance(payload, Mapping):
        raise ModelCatalogUnavailable("官方模型目录暂时不可用")
    records = payload.get("data")
    if not isinstance(records, list) or not records:
        raise ModelCatalogUnavailable("官方模型目录暂时不可用")

    options: list[ModelOption] = []
    seen: set[str] = set()
    model_allowlist = WEB_SEARCH_MODEL_ALLOWLISTS.get(vendor)
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
        if model_allowlist is not None and model_id not in model_allowlist:
            continue
        shutdown = record.get("shutdown_date")
        if shutdown is not None:
            try:
                if (
                    not isinstance(shutdown, str)
                    or datetime.fromisoformat(shutdown).date()
                    <= datetime.now(UTC).date()
                ):
                    continue
            except ValueError:
                continue
        if vendor == "openrouter" and not _supports_openrouter_research(record):
            continue
        raw_name = record.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else model_id
        if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
            name = model_id
        options.append(ModelOption(id=model_id, name=name[:160]))
        seen.add(model_id)

    if not options:
        raise ModelCatalogUnavailable("官方模型目录暂时不可用")
    if vendor == "openrouter":
        # OpenRouter 用稳定的 :free 路由后缀标识免费变体；稳定排序保留各组原顺序。
        options.sort(key=lambda option: not option.id.endswith(":free"))
    return options


class ModelCatalogService:
    """优先读取官方动态目录，无正式接口时使用集中维护的推荐项。"""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _list_qwen_workspace(self, workspace: str, api_key: str) -> ModelCatalog:
        """有界分页读取百炼专用目录，不把普通兼容路由当目录接口。"""
        if not api_key.strip():
            raise ValueError("读取该厂商的官方模型目录需要 API Key")
        records: list[dict[str, Any]] = []
        for page in range(1, 11):
            url = str(
                httpx.URL(
                    f"https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/models",
                    params={
                        "page_no": page,
                        "page_size": 100,
                        "providers": "qwen",
                        "capabilities": "TG",
                        "features": "web-search",
                    },
                )
            )
            failed = False
            try:
                status, content = await self._get("qwen", url, api_key.strip())
            except httpx.HTTPError:
                failed = True
                status, content = 0, b""
            if failed:
                raise ModelCatalogUnavailable("百炼模型目录暂时不可用")
            if status in {401, 403}:
                raise ModelCatalogCredentialError("API Key 无权读取百炼业务空间")
            payload = None
            if status == 200:
                try:
                    payload = json.loads(content)
                except (ValueError, UnicodeDecodeError):
                    pass
            if not isinstance(payload, Mapping) or payload.get("success") is not True:
                raise ModelCatalogUnavailable("百炼模型目录返回格式异常")
            output = payload.get("output")
            if not isinstance(output, Mapping) or not isinstance(
                output.get("models"), list
            ):
                raise ModelCatalogUnavailable("百炼模型目录返回格式异常")
            for record in output["models"]:
                if (
                    not isinstance(record, Mapping)
                    or not isinstance(record.get("features"), list)
                    or "web-search" not in record["features"]
                ):
                    continue
                records.append({"id": record.get("model"), "name": record.get("name")})
            total = output.get("total")
            if type(total) is not int or total < 0:
                raise ModelCatalogUnavailable("百炼模型目录分页信息异常")
            if page * 100 >= total:
                break
        else:
            raise ModelCatalogUnavailable("百炼模型目录超过分页上限")
        return ModelCatalog(
            vendor="qwen",
            source="official_api",
            models=tuple(_parse_model_options({"data": records}, "qwen")),
        )

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

    async def list_models(
        self, vendor: str, api_key: str, *, workspace_id: str | None = None
    ) -> ModelCatalog:
        """读取模型目录；错误只抛稳定中文类型，不透传 Key 或响应正文。"""
        normalized_vendor = vendor.strip().lower()
        workspace = normalize_qwen_workspace_id(workspace_id)
        if workspace and normalized_vendor != "qwen":
            raise ValueError("业务空间 ID 仅适用于百炼")
        if workspace:
            return await self._list_qwen_workspace(workspace, api_key)
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

        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("读取该厂商的官方模型目录需要 API Key")
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
            models=tuple(_parse_model_options(payload, normalized_vendor)),
        )

    async def require_model(
        self,
        *,
        vendor: str,
        model: str,
        api_key: str,
        workspace_id: str | None = None,
    ) -> SelectedModel:
        """再次读取当前目录，确保提交的模型仍属于所选官方厂商。"""
        normalized_vendor = vendor.strip().lower()
        normalized_model = model.strip()
        catalog = await self.list_models(
            normalized_vendor, api_key, workspace_id=workspace_id
        )
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
