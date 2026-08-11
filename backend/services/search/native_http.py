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


class NativeSearchResponseInvalid(RuntimeError):
    """厂商返回的成功响应不符合已核对契约。"""


async def _read_response(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    provider_name: str,
) -> Mapping[str, Any]:
    """流式读取受限大小的 JSON，拒绝保留错误正文和异常链。"""
    request_failed = False
    content = bytearray()
    try:
        async with client.stream(
            "POST",
            url,
            headers=dict(headers),
            json=dict(payload),
        ) as response:
            if response.status_code != 200:
                raise NativeSearchUnavailable(
                    f"{provider_name}联网搜索暂时不可用"
                ) from None
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
    except httpx.HTTPError:
        request_failed = True
    if request_failed:
        raise NativeSearchUnavailable(f"{provider_name}联网搜索暂时不可用")

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
) -> Mapping[str, Any]:
    """复用注入的测试客户端；生产调用使用一次性客户端并及时关闭。"""
    if client is not None:
        return await _read_response(
            client,
            url=url,
            headers=headers,
            payload=payload,
            provider_name=provider_name,
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
        )


__all__ = [
    "NativeSearchResponseInvalid",
    "NativeSearchUnavailable",
    "post_native_search_json",
]
