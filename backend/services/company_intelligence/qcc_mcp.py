"""企查查远端 MCP 的连接、工具发现与付费工具白名单边界。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from .config import ProfessionalDataSettings


@dataclass(frozen=True)
class QccToolBinding:
    server: str
    tool: str


CAPABILITY_BINDINGS: Mapping[str, QccToolBinding] = MappingProxyType(
    {
        "identity.resolve": QccToolBinding("qcc-company", "get_company_by_query"),
        "company.registration": QccToolBinding(
            "qcc-company", "get_company_registration_info"
        ),
        "company.shareholders": QccToolBinding("qcc-company", "get_shareholder_info"),
        "company.changes": QccToolBinding("qcc-company", "get_change_records"),
        "risk.case_filings": QccToolBinding("qcc-risk", "get_case_filing_info"),
        "risk.judicial_documents": QccToolBinding("qcc-risk", "get_judicial_documents"),
        "risk.enforcement": QccToolBinding("qcc-risk", "get_judgment_debtor_info"),
        "risk.dishonest": QccToolBinding("qcc-risk", "get_dishonest_info"),
        "risk.high_consumption": QccToolBinding(
            "qcc-risk", "get_high_consumption_restriction"
        ),
        "risk.bankruptcy": QccToolBinding("qcc-risk", "get_bankruptcy_reorganization"),
        "risk.serious_violation": QccToolBinding("qcc-risk", "get_serious_violation"),
    }
)


ClientFactory = Callable[[str, str, str], AbstractAsyncContextManager[Any]]

_TRUSTED_QCC_HOSTS = frozenset({"agent.qcc.com"})
_MAX_TOOL_PAGES = 100
_MAX_DISCOVERED_TOOLS = 1_000


class QccMcpUnavailable(RuntimeError):
    """MCP 连接、工具发现或 Schema 不满足固定调用计划。"""


class QccMcpCallFailed(RuntimeError):
    """已允许的 MCP 工具调用没有返回可安全解析的结构化结果。"""


@asynccontextmanager
async def _remote_client(_server_name: str, url: str, api_key: str):
    """创建带服务端 Bearer 鉴权的 Streamable HTTP MCP Client。"""
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx2.AsyncClient(
        headers=headers,
        follow_redirects=False,
    ) as http_client:
        transport = streamable_http_client(url, http_client=http_client)
        async with Client(
            transport,
            raise_exceptions=True,
            read_timeout_seconds=30,
        ) as client:
            yield client


class QccMcpClientPool:
    """维护两个 MCP Server 的生命周期，只暴露固定逻辑能力。"""

    def __init__(
        self,
        settings: ProfessionalDataSettings,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or _remote_client
        self._lifecycle_lock = asyncio.Lock()
        self._closed = False
        self._exit_stack: AsyncExitStack | None = None
        self._clients: dict[str, Any] = {}
        self._available_capabilities: frozenset[str] = frozenset()

    @property
    def ready(self) -> bool:
        return (
            self._exit_stack is not None
            and self._available_capabilities == frozenset(CAPABILITY_BINDINGS)
        )

    @property
    def available_capabilities(self) -> frozenset[str]:
        return self._available_capabilities

    async def initialize(self) -> None:
        """连接两个 Server 并完成全量分页工具发现；初始化本身不调用工具。"""
        async with self._lifecycle_lock:
            if self._closed:
                raise QccMcpUnavailable("MCP 客户端池已关闭")
            if self._exit_stack is not None:
                return
            if not self._settings.enabled or not self._settings.api_key:
                return

            server_urls = {
                "qcc-company": self._settings.company_mcp_url,
                "qcc-risk": self._settings.risk_mcp_url,
            }
            for url in server_urls.values():
                self._validate_server_url(url)

            clients: dict[str, Any] = {}
            stack = AsyncExitStack()
            await stack.__aenter__()
            try:
                for server_name, url in server_urls.items():
                    context = self._client_factory(
                        server_name, url, self._settings.api_key
                    )
                    clients[server_name] = await stack.enter_async_context(context)

                discovered = {
                    server_name: await self._discover_tools(client)
                    for server_name, client in clients.items()
                }
                for capability, binding in CAPABILITY_BINDINGS.items():
                    tool = discovered[binding.server].get(binding.tool)
                    if tool is None:
                        raise QccMcpUnavailable(f"MCP 服务缺少必需工具: {capability}")
                    if not self._accepts_search_key(tool.input_schema):
                        raise QccMcpUnavailable(f"MCP 必需工具结构不兼容: {capability}")
            except BaseException as error:
                # MCP SDK 的 AnyIO 上下文不能携带业务异常退出，否则可能用
                # ExceptionGroup 可能覆盖原始的默认关闭原因；这里先无异常关闭。
                try:
                    await stack.aclose()
                except BaseException:
                    pass
                if isinstance(error, QccMcpUnavailable):
                    raise
                if isinstance(error, asyncio.CancelledError):
                    raise
                if not isinstance(error, Exception):
                    raise
                raise QccMcpUnavailable("MCP 初始化或工具发现失败") from None

            self._clients = clients
            self._available_capabilities = frozenset(CAPABILITY_BINDINGS)
            self._exit_stack = stack

    @staticmethod
    def _validate_server_url(url: str) -> None:
        """只允许把 Bearer Key 发送给企查查官方 HTTPS 主机。"""
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise QccMcpUnavailable("MCP 服务地址不可信") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _TRUSTED_QCC_HOSTS
            or port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise QccMcpUnavailable("MCP 服务地址不可信")

    @staticmethod
    async def _discover_tools(client: Any) -> dict[str, Any]:
        """遍历工具发现分页，并限制服务端可消耗的分页与内存。"""
        tools: dict[str, Any] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page_number in range(_MAX_TOOL_PAGES):
            result = await client.list_tools(cursor=cursor)
            for tool in result.tools:
                if tool.name in tools:
                    raise QccMcpUnavailable(f"MCP 工具发现返回重复工具: {tool.name}")
                tools[tool.name] = tool
                if len(tools) > _MAX_DISCOVERED_TOOLS:
                    raise QccMcpUnavailable("MCP 工具发现超过安全数量限制")
            cursor = result.next_cursor
            if cursor is None:
                return tools
            if cursor in seen_cursors:
                raise QccMcpUnavailable("MCP 工具发现返回循环游标")
            seen_cursors.add(cursor)
        raise QccMcpUnavailable("MCP 工具发现超过安全分页限制")

    @staticmethod
    def _accepts_search_key(schema: dict[str, Any]) -> bool:
        properties = schema.get("properties")
        required = schema.get("required")
        return (
            schema.get("type") == "object"
            and isinstance(properties, dict)
            and isinstance(properties.get("searchKey"), dict)
            and properties["searchKey"].get("type") == "string"
            and isinstance(required, list)
            and set(required) == {"searchKey"}
        )

    @staticmethod
    def _validate_search_key(search_key: str) -> str:
        if (
            not isinstance(search_key, str)
            or not 1 <= len(search_key) <= 200
            or any(ord(char) < 32 or ord(char) == 127 for char in search_key)
        ):
            raise ValueError("search_key 格式不合法")
        return search_key

    async def call(self, capability: str, search_key: str) -> dict[str, Any]:
        """把一个内部能力路由到固定工具；不接受任何上游原始工具名。"""
        binding = CAPABILITY_BINDINGS.get(capability)
        if binding is None:
            raise ValueError(f"不允许调用该能力: {capability}")
        if not self.ready:
            raise QccMcpUnavailable("MCP 客户端尚未就绪")
        normalized_key = self._validate_search_key(search_key)
        try:
            result = await self._clients[binding.server].call_tool(
                binding.tool, {"searchKey": normalized_key}
            )
        except Exception:
            raise QccMcpCallFailed("MCP 工具调用失败") from None
        if result.is_error:
            raise QccMcpCallFailed("MCP 工具调用失败")

        payload = result.structured_content
        if payload is None:
            for content in result.content:
                text = getattr(content, "text", None)
                if isinstance(text, str):
                    if len(text.encode("utf-8")) > 2_000_000:
                        raise QccMcpCallFailed("MCP 工具响应超过安全大小限制")
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    break
        if not isinstance(payload, dict):
            raise QccMcpCallFailed("MCP 工具未返回结构化对象")

        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            raise QccMcpCallFailed("MCP 工具返回不可序列化结果") from None
        if len(encoded.encode("utf-8")) > 2_000_000:
            raise QccMcpCallFailed("MCP 工具响应超过安全大小限制")
        return json.loads(encoded)

    async def aclose(self) -> None:
        """关闭两个 Client 及底层 HTTP 连接，并清除就绪状态。"""
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            stack = self._exit_stack
            self._exit_stack = None
            self._clients = {}
            self._available_capabilities = frozenset()
            if stack is not None:
                await stack.aclose()

    async def __aenter__(self) -> QccMcpClientPool:
        await self.initialize()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()
