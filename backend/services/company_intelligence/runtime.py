"""FastAPI 与企业情报模块之间的最小运行时边界。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping

from pymongo.database import Database

from .collection import (
    ProfessionalCollectionService,
    ProfessionalPreparation,
)
from .config import CapabilityPolicy, CapabilityState, ProfessionalDataSettings
from .ledger import InMemoryUsageLedger, UsageLedger
from .models import ProfessionalEvidence
from .mongo_ledger import MongoUsageLedger
from .provider import CompanyIntelligenceProvider
from .resolution import CompanyResolutionService, PublicResolution


@dataclass
class CompanyIntelligenceRuntime:
    settings: ProfessionalDataSettings
    ledger: UsageLedger
    provider: CompanyIntelligenceProvider | None = None
    provider_ready: bool = False
    deployment_budget_exhausted: bool = False
    _professional_limiter: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # 非法并发配置会由 CapabilityPolicy 关闭能力；这里仍需构造安全对象，
        # 保证运维可读取 /capabilities，而不是让应用在导入阶段崩溃。
        self._professional_limiter = asyncio.Semaphore(
            max(1, self.settings.max_concurrency)
        )

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

    def configure_mongo_ledger(
        self, database: Database[dict[str, Any]]
    ) -> None:
        """仅在索引和事务探针成功后，用持久账本替换内存账本。"""
        ledger = MongoUsageLedger(database)
        self.ledger = ledger

    def _professional_service(self) -> ProfessionalCollectionService:
        """基于当前 Provider/账本创建编排器，并复用部署级进程内并发门。"""
        return ProfessionalCollectionService(
            settings=self.settings,
            ledger=self.ledger,
            provider=self.provider,
            provider_ready=self.provider_ready,
            concurrency_limiter=self._professional_limiter,
            deployment_budget_exhausted=self.deployment_budget_exhausted,
        )

    def prepare_professional_research(
        self,
        *,
        job_id: str,
        resolution_token: str,
        client_ip: str,
    ) -> ProfessionalPreparation:
        """验证已确认主体，并原子消费 Token、预留固定专业调用计划。"""
        return self._professional_service().prepare(
            job_id=job_id,
            resolution_token=resolution_token,
            client_ip=client_ip,
        )

    async def collect_professional_research(
        self,
        preparation: ProfessionalPreparation,
    ) -> ProfessionalEvidence:
        """执行已准入的固定计划；所有请求共享同一个进程内并发上限。"""
        return await self._professional_service().collect(preparation)

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
