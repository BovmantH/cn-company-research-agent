"""FastAPI 与企业情报模块之间的最小运行时边界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .config import CapabilityPolicy, CapabilityState, ProfessionalDataSettings
from .ledger import InMemoryUsageLedger, UsageLedger
from .provider import CompanyIntelligenceProvider
from .resolution import CompanyResolutionService, PublicResolution


@dataclass
class CompanyIntelligenceRuntime:
    settings: ProfessionalDataSettings
    ledger: UsageLedger
    provider: CompanyIntelligenceProvider | None = None
    provider_ready: bool = False
    deployment_budget_exhausted: bool = False

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "CompanyIntelligenceRuntime":
        """创建默认运行时；内存账本不满足生产付费能力的持久化要求。"""
        return cls(
            settings=ProfessionalDataSettings.from_env(env),
            ledger=InMemoryUsageLedger(),
        )

    def capability_state(self) -> CapabilityState:
        return CapabilityPolicy(self.settings).evaluate(
            provider_ready=self.provider_ready,
            persistent_ledger=self.ledger.persistent,
            deployment_budget_exhausted=self.deployment_budget_exhausted,
        )

    async def resolve_company(
        self, *, query: str, idempotency_key: str, client_ip: str
    ) -> PublicResolution:
        """把 HTTP 层输入交给带预算、幂等和 Token 保护的解析编排器。"""
        service = CompanyResolutionService(
            settings=self.settings,
            ledger=self.ledger,
            provider=self.provider,
            provider_ready=self.provider_ready,
            deployment_budget_exhausted=self.deployment_budget_exhausted,
        )
        return await service.resolve(
            query=query,
            idempotency_key=idempotency_key,
            client_ip=client_ip,
        )
