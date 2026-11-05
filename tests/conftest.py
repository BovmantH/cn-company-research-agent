"""共享 pytest fixtures。"""

from __future__ import annotations

import ipaddress
import os
import socket

import pytest

_DEPLOYMENT_ENV_NAMES = frozenset(
    {
        "MONGODB_URI",
        "APP_SIGNING_SECRET",
        "ALLOWED_ORIGINS",
        "TRUSTED_PROXY_CIDRS",
        "SEARCH_PROVIDER",
        "OPENCODE_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "TAVILY_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "ZAI_API_KEY",
        "MIMO_API_KEY",
        "XIAOMI_API_KEY",
        "MINIMAX_API_KEY",
    }
)
_DEPLOYMENT_ENV_PREFIXES = ("LLM_", "QCC_", "RESEARCH_")


def _deployment_env_names() -> set[str]:
    return set(_DEPLOYMENT_ENV_NAMES) | {
        name for name in os.environ if name.startswith(_DEPLOYMENT_ENV_PREFIXES)
    }


# 必须早于收集阶段的 import application，fixture 执行时才隔离已经太迟。
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
for _env_name in _deployment_env_names():
    os.environ.pop(_env_name, None)


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """单测显式注入所需配置，不继承开发机部署账户和基础设施。"""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in _deployment_env_names():
        monkeypatch.delenv(name, raising=False)


def _is_local_host(host: object) -> bool:
    if host is None or host in {"", "localhost", b"localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """允许本机测试通信和内存 Transport，默认禁止真实厂商及数据库连接。"""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex

    def require_local_address(address) -> None:
        if isinstance(address, tuple) and not _is_local_host(address[0]):
            raise AssertionError("测试禁止真实网络，请使用内存桩或 MockTransport")

    def connect(connection, address):
        require_local_address(address)
        return original_connect(connection, address)

    def connect_ex(connection, address):
        require_local_address(address)
        return original_connect_ex(connection, address)

    def create_connection(address, *args, **kwargs):
        require_local_address(address)
        return original_create_connection(address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local_host(host):
            raise AssertionError("测试禁止真实网络，请使用内存桩或 MockTransport")
        return original_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host):
        if not _is_local_host(host):
            raise AssertionError("测试禁止真实网络，请使用内存桩或 MockTransport")
        return original_gethostbyname(host)

    def gethostbyname_ex(host):
        if not _is_local_host(host):
            raise AssertionError("测试禁止真实网络，请使用内存桩或 MockTransport")
        return original_gethostbyname_ex(host)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", gethostbyname_ex)
