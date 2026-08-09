"""在可信代理边界内解析客户端地址。"""

from __future__ import annotations

import ipaddress


def resolve_client_ip(
    *,
    peer_ip: str,
    forwarded_for: str | None,
    trusted_proxy_cidrs: tuple[str, ...],
) -> str:
    """返回规范客户端 IP；只有直接对端可信时才读取转发链。"""
    normalized_peer = peer_ip.strip().lower()
    try:
        peer = ipaddress.ip_address(normalized_peer)
    except ValueError:
        return normalized_peer

    try:
        trusted_networks = tuple(
            ipaddress.ip_network(value, strict=False) for value in trusted_proxy_cidrs
        )
    except ValueError:
        return str(peer)

    def is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(address in network for network in trusted_networks)

    if not forwarded_for or not is_trusted(peer):
        return str(peer)

    try:
        forwarded = [
            ipaddress.ip_address(value.strip())
            for value in forwarded_for.split(",")
            if value.strip()
        ]
    except ValueError:
        return str(peer)
    if not forwarded:
        return str(peer)

    for address in reversed(forwarded):
        if not is_trusted(address):
            return str(address)
    return str(forwarded[0])
