"""专业企业数据固定调用计划的准入、并发采集与结算。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import StrEnum

from .config import (
    DATA_CAPABILITIES,
    TOOL_COST_CATALOG,
    CapabilityPolicy,
    ProfessionalDataSettings,
)
from .ledger import (
    BudgetLimits,
    BudgetRequest,
    OperationStatus,
    UsageLedger,
    operation_fingerprint,
)
from .models import (
    CAPABILITY_CONTRACTS,
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    ProfessionalEvidence,
    SourceMetadata,
)
from .provider import CompanyIntelligenceProvider
from .tokens import (
    ResolutionTokenError,
    ResolutionTokenService,
    requester_fingerprint,
)

logger = logging.getLogger(__name__)


class PreparationKind(StrEnum):
    READY = "ready"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"


class ProfessionalCollectionAlreadyClaimed(RuntimeError):
    """同一专业采集操作已经由其他执行器领取。"""


@dataclass(frozen=True)
class ProfessionalPreparation:
    """专业分支准入结果；reservation_id 只在服务端内部流转。"""

    kind: PreparationKind
    job_id: str | None = None
    identity: CompanyIdentity | None = None
    reservation_id: str | None = None
    evidence: ProfessionalEvidence | None = None
    reason_code: str | None = None


class ProfessionalCollectionService:
    """在固定预算内采集全部工商司法能力，并生成完整覆盖 Evidence。"""

    def __init__(
        self,
        *,
        settings: ProfessionalDataSettings,
        ledger: UsageLedger,
        provider: CompanyIntelligenceProvider | None,
        provider_ready: bool,
        concurrency_limiter: asyncio.Semaphore,
        deployment_budget_exhausted: bool = False,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.provider = provider
        self.provider_ready = provider_ready
        self.concurrency_limiter = concurrency_limiter
        self.deployment_budget_exhausted = deployment_budget_exhausted

    def _budget_limits(self) -> BudgetLimits:
        return BudgetLimits(
            max_points_per_job=self.settings.max_points_per_job,
            max_calls_per_job=self.settings.max_calls_per_job,
            daily_point_budget=self.settings.daily_point_budget,
            daily_job_limit=self.settings.daily_job_limit,
            requester_daily_limit=self.settings.requester_daily_limit,
        )

    def _blocked_capability_reason(self) -> str | None:
        state = CapabilityPolicy(self.settings).evaluate(
            provider_ready=self.provider_ready,
            persistent_ledger=self.ledger.persistent,
            deployment_budget_exhausted=self.deployment_budget_exhausted,
        )
        return state.reason.value if state.reason else None

    @staticmethod
    def _identity_fingerprint(identity: CompanyIdentity) -> str:
        payload = json.dumps(
            {
                "canonical_name": identity.canonical_name,
                "credit_code": identity.credit_code,
                "provider_subject_id": identity.provider_subject_id,
                "original_query": identity.original_query,
                "match_method": identity.match_method,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return operation_fingerprint(payload)

    def prepare(
        self,
        *,
        job_id: str,
        resolution_token: str,
        client_ip: str,
    ) -> ProfessionalPreparation:
        """先验证部署与签名主体，再原子消费 Token 并预留固定计划。"""
        blocked_reason = self._blocked_capability_reason()
        if blocked_reason:
            return ProfessionalPreparation(
                kind=PreparationKind.BLOCKED,
                reason_code=blocked_reason,
            )

        requester_id = requester_fingerprint(client_ip, self.settings.signing_secret)
        token_service = ResolutionTokenService(
            self.settings.signing_secret, self.ledger
        )
        try:
            claims = token_service.verify(resolution_token, requester_id)
            identity = CompanyIdentity(
                canonical_name=claims.canonical_name,
                credit_code=claims.credit_code,
                provider_subject_id=claims.provider_subject_id,
                original_query=claims.original_query,
                match_method=claims.match_method,
            )
        except (ResolutionTokenError, ValueError):
            return ProfessionalPreparation(
                kind=PreparationKind.BLOCKED,
                reason_code="identity_unconfirmed",
            )

        decision = self.ledger.reserve_with_token(
            BudgetRequest(
                idempotency_key=f"professional:{claims.jti}",
                job_id=job_id,
                requester_id=requester_id,
                plan="professional_research",
                capabilities=tuple(DATA_CAPABILITIES),
                request_fingerprint=self._identity_fingerprint(identity),
            ),
            self._budget_limits(),
            token_id=claims.jti,
            token_expires_at=claims.exp,
        )
        if not decision.allowed:
            reason = (
                "identity_unconfirmed"
                if decision.reason in {"invalid_token", "token_already_used"}
                else "idempotency_conflict"
                if decision.reason == "idempotency_conflict"
                else "budget_blocked"
            )
            return ProfessionalPreparation(
                kind=PreparationKind.BLOCKED,
                reason_code=reason,
            )

        if decision.replayed:
            if decision.operation_status == OperationStatus.IN_PROGRESS:
                return ProfessionalPreparation(
                    kind=PreparationKind.IN_PROGRESS,
                    job_id=decision.job_id,
                )
            if (
                decision.operation_status == OperationStatus.COMPLETED
                and decision.result is not None
            ):
                try:
                    evidence = ProfessionalEvidence.model_validate(decision.result)
                except ValueError:
                    return ProfessionalPreparation(
                        kind=PreparationKind.BLOCKED,
                        job_id=decision.job_id,
                        reason_code="provider_unavailable",
                    )
                return ProfessionalPreparation(
                    kind=PreparationKind.REPLAYED,
                    job_id=decision.job_id,
                    evidence=evidence,
                )
            return ProfessionalPreparation(
                kind=PreparationKind.BLOCKED,
                job_id=decision.job_id,
                reason_code=decision.reason or "provider_unavailable",
            )

        if not decision.reservation_id:
            return ProfessionalPreparation(
                kind=PreparationKind.BLOCKED,
                reason_code="provider_unavailable",
            )
        return ProfessionalPreparation(
            kind=PreparationKind.READY,
            job_id=decision.job_id or job_id,
            identity=identity,
            reservation_id=decision.reservation_id,
        )

    @staticmethod
    def _unavailable_collection(capability: str) -> EvidenceCollection:
        return EvidenceCollection(
            capability=capability,
            status=CollectionStatus.UNAVAILABLE,
            reason_code="provider_unavailable",
        )

    @staticmethod
    def _failed_collection(
        capability: str,
        identity: CompanyIdentity,
    ) -> EvidenceCollection:
        server = CAPABILITY_CONTRACTS[capability][0]
        return EvidenceCollection(
            capability=capability,
            status=CollectionStatus.FAILED,
            source=SourceMetadata(
                server=server,
                capability=capability,
                queried_subject=identity.credit_code,
                status=CollectionStatus.FAILED,
            ),
            reason_code="provider_call_failed",
        )

    def _finalize_interrupted(
        self,
        reservation_id: str,
        attempted: list[str],
    ) -> None:
        """按已进入供应商调用的能力结算失败终态，不暴露原始异常。"""
        actual_points = sum(TOOL_COST_CATALOG[capability] for capability in attempted)
        try:
            self.ledger.finalize_operation(
                reservation_id,
                result=None,
                safe_reason="professional_collection_interrupted",
                actual_points=actual_points,
                actual_calls=len(attempted),
            )
        except Exception as finalize_error:
            logger.warning(
                "专业采集失败终态写入失败，异常类型=%s",
                type(finalize_error).__name__,
            )

    async def collect(
        self, preparation: ProfessionalPreparation
    ) -> ProfessionalEvidence:
        """并发执行固定十项计划；单项异常降级，终态与实际用量原子落账。"""
        if (
            preparation.kind != PreparationKind.READY
            or preparation.identity is None
            or preparation.reservation_id is None
        ):
            raise ValueError("只有 ready 的专业数据准备结果可以执行采集")

        identity = preparation.identity
        reservation_id = preparation.reservation_id
        if not self.ledger.claim_operation(reservation_id):
            raise ProfessionalCollectionAlreadyClaimed(
                "专业采集操作已被领取，禁止重复执行"
            )

        attempted: list[str] = []

        async def call_capability(capability: str) -> EvidenceCollection:
            async with self.concurrency_limiter:
                if self.provider is None or not self.provider_ready:
                    return self._unavailable_collection(capability)
                attempted.append(capability)
                try:
                    result = await self.provider.call(capability, identity)
                    if (
                        result.capability != capability
                        or result.status
                        not in {
                            CollectionStatus.SUCCEEDED_WITH_RECORDS,
                            CollectionStatus.SUCCEEDED_EMPTY,
                            CollectionStatus.PARTIAL,
                            CollectionStatus.FAILED,
                        }
                        or result.source is None
                        or result.source.queried_subject != identity.credit_code
                    ):
                        raise ValueError("provider result contract mismatch")
                    return result
                except Exception as exc:
                    logger.warning(
                        "QCC 专业能力调用失败，capability=%s，异常类型=%s",
                        capability,
                        type(exc).__name__,
                    )
                    return self._failed_collection(capability, identity)

        tasks = [
            asyncio.create_task(call_capability(capability))
            for capability in DATA_CAPABILITIES
        ]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._finalize_interrupted(reservation_id, attempted)
            raise

        try:
            evidence = ProfessionalEvidence(
                identity=identity,
                collections=dict(zip(DATA_CAPABILITIES, results, strict=True)),
            )
            actual_calls = len(attempted)
            actual_points = sum(
                TOOL_COST_CATALOG[capability] for capability in attempted
            )
            self.ledger.finalize_operation(
                reservation_id,
                result=evidence.model_dump(mode="json"),
                safe_reason=None,
                actual_points=actual_points,
                actual_calls=actual_calls,
            )
            return evidence
        except BaseException:
            self._finalize_interrupted(reservation_id, attempted)
            raise
