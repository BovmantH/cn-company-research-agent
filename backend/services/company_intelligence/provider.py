"""Company Intelligence Provider 的窄接口与测试实现。"""

from __future__ import annotations

from typing import Protocol

from .config import REQUIRED_CAPABILITIES
from .models import (
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    ResolveKind,
    ResolveResult,
)


class CompanyIntelligenceProvider(Protocol):
    """隔离外部企业数据服务，业务层只依赖归一化后的安全领域对象。"""

    @property
    def ready(self) -> bool: ...

    @property
    def available_capabilities(self) -> frozenset[str]: ...

    async def initialize(self) -> None: ...

    async def resolve(self, query: str) -> ResolveResult: ...

    async def call(
        self, capability: str, identity: CompanyIdentity
    ) -> EvidenceCollection: ...


class FakeCompanyIntelligenceProvider:
    """无网络、无费用的确定性 Provider，用于测试完整业务闭环。"""

    def __init__(
        self,
        *,
        resolutions: dict[str, ResolveResult] | None = None,
        calls: dict[str, EvidenceCollection] | None = None,
        capabilities: frozenset[str] | None = None,
    ) -> None:
        self._resolutions = resolutions or {}
        self._calls = calls or {}
        self._capabilities = (
            frozenset(REQUIRED_CAPABILITIES) if capabilities is None else capabilities
        )
        self._ready = False
        self.call_log: list[tuple[str, str]] = []

    @property
    def ready(self) -> bool:
        return self._ready and set(REQUIRED_CAPABILITIES).issubset(self._capabilities)

    @property
    def available_capabilities(self) -> frozenset[str]:
        return self._capabilities

    async def initialize(self) -> None:
        """模拟能力探测；只有完整实现必需能力时才进入就绪状态。"""
        self._ready = set(REQUIRED_CAPABILITIES).issubset(self._capabilities)

    async def resolve(self, query: str) -> ResolveResult:
        self.call_log.append(("identity.resolve", query))
        return self._resolutions.get(query, ResolveResult(kind=ResolveKind.NOT_FOUND))

    async def call(
        self, capability: str, identity: CompanyIdentity
    ) -> EvidenceCollection:
        if capability not in self._capabilities or capability == "identity.resolve":
            raise ValueError(f"不允许调用该能力: {capability}")
        self.call_log.append((capability, identity.credit_code))
        if capability not in self._calls:
            raise KeyError(f"未配置模拟结果: {capability}")
        result = self._calls[capability]
        if result.capability != capability:
            raise ValueError("数据提供方返回的能力不匹配")
        if result.status not in {
            CollectionStatus.SUCCEEDED_WITH_RECORDS,
            CollectionStatus.SUCCEEDED_EMPTY,
            CollectionStatus.PARTIAL,
            CollectionStatus.FAILED,
        }:
            raise ValueError("数据提供方返回了仅限编排层使用的状态")
        if (
            result.source is None
            or result.source.queried_subject != identity.credit_code
        ):
            raise ValueError("数据提供方返回的主体不匹配")
        return result
