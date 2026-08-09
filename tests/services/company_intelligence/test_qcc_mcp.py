from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.server import MCPServer

from backend.services.company_intelligence.config import ProfessionalDataSettings
from backend.services.company_intelligence.qcc_mcp import (
    CAPABILITY_BINDINGS,
    QccMcpCallFailed,
    QccMcpClientPool,
    QccMcpUnavailable,
)


def _settings(*, enabled: bool = True, api_key: str = "test-api-key"):
    return ProfessionalDataSettings.from_env(
        {
            "QCC_MCP_ENABLED": "true" if enabled else "false",
            "QCC_API_KEY": api_key,
        }
    )


def _register_tool(
    server: MCPServer,
    *,
    tool_name: str,
    capability: str,
    calls: list[tuple[str, str]],
    wrong_schema: bool = False,
    fail_with_secret: bool = False,
) -> None:
    if fail_with_secret:

        def handler(searchKey: str) -> dict[str, object]:
            raise RuntimeError(f"Authorization: Bearer secret for {searchKey}")

    elif wrong_schema:

        def handler(searchKey: int) -> dict[str, object]:
            return {"Result": [searchKey]}

    else:

        def handler(searchKey: str) -> dict[str, object]:
            calls.append((capability, searchKey))
            return {"Result": [{"capability": capability, "key": searchKey}]}

    server.tool(name=tool_name)(handler)


def _servers(
    *,
    omitted_capability: str | None = None,
    wrong_schema_capability: str | None = None,
    failing_capability: str | None = None,
    include_extra: bool = False,
) -> tuple[dict[str, MCPServer], list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []
    servers = {
        "qcc-company": MCPServer("qcc-company-test"),
        "qcc-risk": MCPServer("qcc-risk-test"),
    }
    for capability, binding in CAPABILITY_BINDINGS.items():
        if capability == omitted_capability:
            continue
        _register_tool(
            servers[binding.server],
            tool_name=binding.tool,
            capability=capability,
            calls=calls,
            wrong_schema=capability == wrong_schema_capability,
            fail_with_secret=capability == failing_capability,
        )
    if include_extra:
        _register_tool(
            servers["qcc-company"],
            tool_name="get_contact_info",
            capability="forbidden.contact",
            calls=calls,
        )
    return servers, calls


def _client_factory(
    servers: dict[str, MCPServer],
) -> Callable[[str, str, str], AbstractAsyncContextManager[Client]]:
    def create(server_name: str, _url: str, _api_key: str):
        return Client(servers[server_name], raise_exceptions=True)

    return create


@pytest.mark.asyncio
async def test_initialize_binds_all_required_tools_without_calling_them() -> None:
    servers, calls = _servers(include_extra=True)
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )

    await pool.initialize()

    assert pool.ready is True
    assert pool.available_capabilities == frozenset(CAPABILITY_BINDINGS)
    assert "forbidden.contact" not in pool.available_capabilities
    assert calls == []
    await pool.aclose()


@pytest.mark.asyncio
async def test_missing_required_tool_fails_closed() -> None:
    servers, _ = _servers(omitted_capability="risk.enforcement")
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )

    with pytest.raises(QccMcpUnavailable, match="必需工具"):
        await pool.initialize()

    assert pool.ready is False
    assert pool.available_capabilities == frozenset()


@pytest.mark.asyncio
async def test_second_server_failure_closes_first_client() -> None:
    servers, _ = _servers()
    closed: list[str] = []

    @asynccontextmanager
    async def factory(server_name: str, _url: str, _api_key: str):
        if server_name == "qcc-risk":
            raise RuntimeError("Authorization: Bearer secret")
        try:
            async with Client(servers[server_name]) as client:
                yield client
        finally:
            closed.append(server_name)

    pool = QccMcpClientPool(_settings(), client_factory=factory)

    with pytest.raises(QccMcpUnavailable) as raised:
        await pool.initialize()

    assert "secret" not in str(raised.value)
    assert closed == ["qcc-company"]
    assert pool.ready is False


@pytest.mark.asyncio
async def test_concurrent_initialize_opens_each_client_once() -> None:
    opened: list[str] = []
    closed: list[str] = []

    class DiscoveryClient:
        def __init__(self, server_name: str) -> None:
            self.server_name = server_name

        async def list_tools(self, *, cursor=None):
            assert cursor is None
            tools = [
                SimpleNamespace(
                    name=binding.tool,
                    input_schema={
                        "type": "object",
                        "properties": {"searchKey": {"type": "string"}},
                        "required": ["searchKey"],
                    },
                )
                for binding in CAPABILITY_BINDINGS.values()
                if binding.server == self.server_name
            ]
            return SimpleNamespace(tools=tools, next_cursor=None)

    @asynccontextmanager
    async def factory(server_name: str, _url: str, _api_key: str):
        opened.append(server_name)
        try:
            await asyncio.sleep(0)
            yield DiscoveryClient(server_name)
        finally:
            closed.append(server_name)

    pool = QccMcpClientPool(_settings(), client_factory=factory)

    await asyncio.gather(pool.initialize(), pool.initialize())

    assert opened == ["qcc-company", "qcc-risk"]
    assert pool.ready is True
    await pool.aclose()
    assert closed == ["qcc-risk", "qcc-company"]


@pytest.mark.asyncio
async def test_closed_pool_cannot_be_reinitialized() -> None:
    servers, _ = _servers()
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )
    await pool.initialize()
    await pool.aclose()

    with pytest.raises(QccMcpUnavailable, match="已关闭"):
        await pool.initialize()

    assert pool.ready is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://agent.qcc.com/mcp/company/stream",
        "https://agent.qcc.com.evil.example/mcp/company/stream",
        "https://user:password@agent.qcc.com/mcp/company/stream",
        "https://agent.qcc.com:8443/mcp/company/stream",
    ],
)
async def test_untrusted_server_url_is_rejected_before_key_is_sent(
    unsafe_url: str,
) -> None:
    created = 0

    def fail_if_called(*_args):
        nonlocal created
        created += 1
        raise AssertionError("client factory must not be called")

    settings = replace(_settings(), company_mcp_url=unsafe_url)
    pool = QccMcpClientPool(settings, client_factory=fail_if_called)

    with pytest.raises(QccMcpUnavailable, match="URL 不可信"):
        await pool.initialize()

    assert created == 0


@pytest.mark.asyncio
async def test_tool_discovery_has_page_limit() -> None:
    class EndlessClient:
        def __init__(self) -> None:
            self.pages = 0

        async def list_tools(self, *, cursor=None):
            self.pages += 1
            return SimpleNamespace(
                tools=[], next_cursor=f"page-{self.pages}"
            )

    client = EndlessClient()

    with pytest.raises(QccMcpUnavailable, match="分页限制"):
        await QccMcpClientPool._discover_tools(client)

    assert client.pages == 100


@pytest.mark.asyncio
async def test_wrong_search_key_schema_fails_closed() -> None:
    servers, _ = _servers(wrong_schema_capability="company.registration")
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )

    with pytest.raises(QccMcpUnavailable, match="Schema"):
        await pool.initialize()
    assert pool.ready is False


@pytest.mark.asyncio
async def test_disabled_or_missing_key_never_creates_client() -> None:
    created = 0

    def fail_if_called(*_args):
        nonlocal created
        created += 1
        raise AssertionError("client factory must not be called")

    disabled = QccMcpClientPool(
        _settings(enabled=False), client_factory=fail_if_called
    )
    missing_key = QccMcpClientPool(
        _settings(api_key=""), client_factory=fail_if_called
    )

    await disabled.initialize()
    await missing_key.initialize()

    assert disabled.ready is False
    assert missing_key.ready is False
    assert created == 0


@pytest.mark.asyncio
async def test_call_routes_only_whitelisted_capability() -> None:
    servers, calls = _servers(include_extra=True)
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )
    await pool.initialize()

    payload = await pool.call("risk.enforcement", "91320594MA1N00000X")

    assert payload == {
        "Result": [
            {
                "capability": "risk.enforcement",
                "key": "91320594MA1N00000X",
            }
        ]
    }
    assert calls == [("risk.enforcement", "91320594MA1N00000X")]
    with pytest.raises(ValueError, match="capability not allowed"):
        await pool.call("forbidden.contact", "示例公司")
    await pool.aclose()


@pytest.mark.asyncio
async def test_call_rejects_control_characters_before_provider() -> None:
    servers, calls = _servers()
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )
    await pool.initialize()

    with pytest.raises(ValueError, match="search_key"):
        await pool.call("identity.resolve", "示例\n公司")
    assert calls == []
    await pool.aclose()


@pytest.mark.asyncio
async def test_call_exception_does_not_expose_upstream_secret() -> None:
    servers, _ = _servers(failing_capability="identity.resolve")
    pool = QccMcpClientPool(
        _settings(), client_factory=_client_factory(servers)
    )
    await pool.initialize()

    with pytest.raises(QccMcpCallFailed) as raised:
        await pool.call("identity.resolve", "示例公司")

    assert "secret" not in str(raised.value)
    await pool.aclose()
