"""原生联网适配器共用的来源校验与排序工具。"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

MAX_SOURCE_URL_LENGTH = 2_048


def is_public_web_url(url: str) -> bool:
    """只接受不含凭证、控制字符或非公网地址的 HTTP(S) 来源。"""
    if not url or len(url) > MAX_SOURCE_URL_LENGTH:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        # 主动读取端口以拒绝非法端口文本。
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False

    normalized_hostname = hostname.rstrip(".").lower()
    if (
        normalized_hostname == "localhost"
        or normalized_hostname.endswith(".localhost")
        or normalized_hostname.endswith(".local")
    ):
        return False
    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        # 不做 DNS 解析，避免校验动作本身产生网络访问；域名至少应包含一个点。
        return "." in normalized_hostname
    return address.is_global


def safe_string(value: object) -> str:
    """把可选上游文本收窄为空字符串或去除首尾空白的字符串。"""
    return value.strip() if isinstance(value, str) else ""


def ranked_source_score(index: int) -> float:
    """上游不提供分数时按原始排序生成可供筛选器使用的稳定分数。"""
    return max(0.0, 1.0 - index * 0.05)


__all__ = ["is_public_web_url", "ranked_source_score", "safe_string"]
