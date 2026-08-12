"""把模型厂商故障收敛为稳定、安全的公开错误。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx
from openai import APIConnectionError, APITimeoutError


@dataclass(frozen=True)
class PublicProviderFailure:
    """允许写入任务状态和 SSE 的最小错误信息。"""

    reason_code: str
    message: str


_STATUS_FAILURES: Final[dict[int, PublicProviderFailure]] = {
    400: PublicProviderFailure(
        "provider_request_invalid",
        "所选厂商不接受当前模型或请求参数，请重新加载模型列表后重试",
    ),
    401: PublicProviderFailure(
        "provider_authentication_failed",
        "所选厂商拒绝了 API Key，请检查 Key 是否正确或已失效",
    ),
    402: PublicProviderFailure(
        "provider_balance_insufficient",
        "所选厂商账户余额不足，请充值或改用免费模型后重试",
    ),
    403: PublicProviderFailure(
        "provider_permission_denied",
        "当前 API Key 无权使用所选模型或联网搜索，请检查厂商账户权限",
    ),
    404: PublicProviderFailure(
        "provider_model_unavailable",
        "所选模型不存在或已下线，请重新加载模型列表后选择其他模型",
    ),
    408: PublicProviderFailure(
        "provider_timeout",
        "所选厂商响应超时，请稍后重试",
    ),
    409: PublicProviderFailure(
        "provider_request_conflict",
        "所选厂商暂时无法处理当前请求，请稍后重试",
    ),
    422: PublicProviderFailure(
        "provider_request_invalid",
        "所选厂商不接受当前模型或请求参数，请重新加载模型列表后重试",
    ),
    429: PublicProviderFailure(
        "provider_rate_limited",
        "所选厂商请求过于频繁或免费额度已用完，请稍后重试或更换模型",
    ),
}
_PROVIDER_UNAVAILABLE = PublicProviderFailure(
    "provider_unavailable",
    "所选厂商服务暂时不可用，请稍后重试",
)
_PROVIDER_TIMEOUT = _STATUS_FAILURES[408]


def _exception_chain(exc: BaseException):
    """有限遍历显式或隐式异常链，不读取任何异常正文。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_provider_failure(
    exc: BaseException,
) -> PublicProviderFailure | None:
    """按异常类型和 HTTP 状态码映射公开错误，未知异常交给通用错误处理。"""
    chain = tuple(_exception_chain(exc))
    for current in chain:
        status_code = getattr(current, "status_code", None)
        if type(status_code) is not int:
            continue
        if failure := _STATUS_FAILURES.get(status_code):
            return failure
        if 500 <= status_code <= 599:
            return _PROVIDER_UNAVAILABLE

    if any(
        isinstance(current, (APITimeoutError, httpx.TimeoutException))
        for current in chain
    ):
        return _PROVIDER_TIMEOUT
    if any(
        isinstance(current, (APIConnectionError, httpx.NetworkError))
        for current in chain
    ):
        return _PROVIDER_UNAVAILABLE
    return None


__all__ = ["PublicProviderFailure", "classify_provider_failure"]
