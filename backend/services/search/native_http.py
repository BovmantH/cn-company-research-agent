"""原生联网适配器共用的受限 JSON 请求边界。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

NATIVE_SEARCH_TIMEOUT_SECONDS = 60.0
MAX_NATIVE_SEARCH_RESPONSE_BYTES = 2_000_000


class NativeSearchUnavailable(RuntimeError):
    """厂商原生联网暂时不可用，异常中不保留上游正文。"""


class NativeSearchRequestError(NativeSearchUnavailable):
    """只携带操作和状态码，禁止保留 HTTP 请求、响应或上游异常链。"""

    def __init__(self, *, status_code: int, operation: str, provider_name: str):
        super().__init__(f"{provider_name}网页检索服务请求失败")
        self.status_code = status_code
        self.operation = operation


class NativeSearchResponseInvalid(RuntimeError):
    """厂商返回的成功响应不符合已核对契约。"""


async def _read_response(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    provider_name: str,
    operation: str,
) -> Mapping[str, Any]:
    """流式读取受限大小的 JSON，拒绝保留错误正文和异常链。"""
    failed_status: int | None = None
    content = bytearray()
    try:
        async with client.stream(
            "POST",
            url,
            headers=dict(headers),
            json=dict(payload),
        ) as response:
            if response.status_code != 200:
                failed_status = response.status_code
            else:
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > MAX_NATIVE_SEARCH_RESPONSE_BYTES:
                            raise NativeSearchResponseInvalid(
                                f"{provider_name}联网搜索返回格式异常"
                            ) from None
                    except ValueError:
                        pass
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_NATIVE_SEARCH_RESPONSE_BYTES:
                        raise NativeSearchResponseInvalid(
                            f"{provider_name}联网搜索返回格式异常"
                        ) from None
    except (NativeSearchUnavailable, NativeSearchResponseInvalid):
        raise
    except httpx.TimeoutException:
        failed_status = 408
    except httpx.HTTPError:
        failed_status = 503
    if failed_status is not None:
        raise NativeSearchRequestError(
            status_code=failed_status, operation=operation, provider_name=provider_name
        )

    json_failed = False
    try:
        decoded = json.loads(content)
    except (UnicodeDecodeError, ValueError):
        json_failed = True
        decoded = None
    if json_failed:
        raise NativeSearchResponseInvalid(f"{provider_name}联网搜索返回格式异常")
    if not isinstance(decoded, Mapping):
        raise NativeSearchResponseInvalid(
            f"{provider_name}联网搜索返回格式异常"
        ) from None
    return decoded


async def post_native_search_json(
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    provider_name: str,
    client: httpx.AsyncClient | None,
    operation: str = "search",
) -> Mapping[str, Any]:
    """复用注入的测试客户端；生产调用使用一次性客户端并及时关闭。"""
    if client is not None:
        return await _read_response(
            client,
            url=url,
            headers=headers,
            payload=payload,
            provider_name=provider_name,
            operation=operation,
        )
    async with httpx.AsyncClient(
        timeout=NATIVE_SEARCH_TIMEOUT_SECONDS,
        follow_redirects=False,
    ) as transient_client:
        return await _read_response(
            transient_client,
            url=url,
            headers=headers,
            payload=payload,
            provider_name=provider_name,
            operation=operation,
        )


__all__ = [
    "NativeSearchResponseInvalid",
    "NativeSearchUnavailable",
    "NativeSearchRequestError",
    "post_native_search_json",
]
