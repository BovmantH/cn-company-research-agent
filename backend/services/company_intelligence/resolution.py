"""企业主体解析的预算、幂等与 Token 编排。"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from pydantic import Field, model_validator

from .config import CapabilityPolicy, ProfessionalDataSettings, TOOL_COST_CATALOG
from .ledger import (
    BudgetLimits,
    BudgetRequest,
    OperationStatus,
    UsageLedger,
    operation_fingerprint,
)
from .models import CompanyIdentity, ResolveKind, StrictModel
from .provider import CompanyIntelligenceProvider
from .tokens import ResolutionTokenService, requester_fingerprint


logger = logging.getLogger(__name__)


class IdempotencyConflict(RuntimeError):
    pass


class ResolutionInProgress(RuntimeError):
    pass


class PublicCompanyIdentity(StrictModel):
    company_name: str
    credit_code: str
    registration_status: str | None = None
    region: str | None = None
    resolution_token: str = Field(min_length=10, max_length=4096)


class PublicResolution(StrictModel):
    kind: ResolveKind
    identity: PublicCompanyIdentity | None = None
    candidates: list[PublicCompanyIdentity] = Field(default_factory=list, max_length=5)
    reason: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def enforce_shape(self) -> "PublicResolution":
        """保证公开状态与主体字段互斥，避免前端误用残留候选数据。"""
        if self.kind == ResolveKind.EXACT and (
            self.identity is None or self.candidates
        ):
            raise ValueError("exact 必须且只能包含 identity")
        if self.kind == ResolveKind.CANDIDATES and (
            self.identity is not None or not 1 < len(self.candidates) <= 5
        ):
            raise ValueError("candidates 必须且只能包含 2 至 5 个候选")
        if self.kind in {ResolveKind.NOT_FOUND, ResolveKind.BLOCKED} and (
            self.identity is not None or self.candidates
        ):
            raise ValueError(f"{self.kind} 不得包含主体")
        return self


class CompanyResolutionService:
    def __init__(
        self,
        *,
        settings: ProfessionalDataSettings,
        ledger: UsageLedger,
        provider: CompanyIntelligenceProvider | None,
        provider_ready: bool,
        deployment_budget_exhausted: bool = False,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.provider = provider
        self.provider_ready = provider_ready
        self.deployment_budget_exhausted = deployment_budget_exhausted

    def _blocked_capability_reason(self) -> str | None:
        state = CapabilityPolicy(self.settings).evaluate(
            provider_ready=self.provider_ready,
            persistent_ledger=self.ledger.persistent,
            deployment_budget_exhausted=self.deployment_budget_exhausted,
        )
        return state.reason.value if state.reason else None

    def _budget_limits(self) -> BudgetLimits:
        return BudgetLimits(
            max_points_per_job=self.settings.max_points_per_job,
            max_calls_per_job=self.settings.max_calls_per_job,
            daily_point_budget=self.settings.daily_point_budget,
            daily_job_limit=self.settings.daily_job_limit,
            requester_daily_limit=self.settings.requester_daily_limit,
        )

    def _public_identity(
        self,
        identity: CompanyIdentity,
        *,
        requester_id: str,
        match_method: Literal["exact", "user_selected"],
        original_query: str,
    ) -> PublicCompanyIdentity:
        """签发绑定请求方的一次性凭证，只向前端暴露确认主体所需字段。"""
        normalized = identity.model_copy(
            update={
                "match_method": match_method,
                "original_query": original_query,
            }
        )
        token = ResolutionTokenService(self.settings.signing_secret, self.ledger).issue(
            normalized, requester_id
        )
        return PublicCompanyIdentity(
            company_name=normalized.canonical_name,
            credit_code=normalized.credit_code,
            registration_status=normalized.registration_status,
            region=normalized.region,
            resolution_token=token,
        )

    async def resolve(
        self, *, query: str, idempotency_key: str, client_ip: str
    ) -> PublicResolution:
        """先完成能力判定和原子预留，再重放结果或发起一次付费解析调用。"""
        blocked_reason = self._blocked_capability_reason()
        if blocked_reason:
            return PublicResolution(kind=ResolveKind.BLOCKED, reason=blocked_reason)

        requester_id = requester_fingerprint(client_ip, self.settings.signing_secret)
        normalized_query = " ".join(query.strip().split())
        decision = self.ledger.reserve(
            BudgetRequest(
                idempotency_key=idempotency_key,
                job_id=f"resolve-{uuid.uuid4().hex}",
                requester_id=requester_id,
                plan="identity_resolution",
                capabilities=("identity.resolve",),
                request_fingerprint=operation_fingerprint(normalized_query),
            ),
            self._budget_limits(),
        )

        if not decision.allowed:
            if decision.reason == "idempotency_conflict":
                raise IdempotencyConflict
            return PublicResolution(kind=ResolveKind.BLOCKED, reason="budget_blocked")
        if not decision.reservation_id:
            return PublicResolution(
                kind=ResolveKind.BLOCKED, reason="provider_unavailable"
            )

        if decision.replayed:
            if decision.operation_status == OperationStatus.IN_PROGRESS:
                raise ResolutionInProgress
            if (
                decision.operation_status == OperationStatus.COMPLETED
                and decision.result
            ):
                return PublicResolution.model_validate(decision.result)
            return PublicResolution(
                kind=ResolveKind.BLOCKED,
                reason=decision.reason or "provider_unavailable",
            )

        if self.provider is None:
            self.ledger.finalize_operation(
                decision.reservation_id,
                result=None,
                safe_reason="provider_unavailable",
                actual_points=0,
                actual_calls=0,
            )
            return PublicResolution(
                kind=ResolveKind.BLOCKED, reason="provider_unavailable"
            )

        try:
            resolved = await self.provider.resolve(normalized_query)
            if resolved.kind == ResolveKind.EXACT:
                response = PublicResolution(
                    kind=ResolveKind.EXACT,
                    identity=self._public_identity(
                        resolved.identities[0],
                        requester_id=requester_id,
                        match_method="exact",
                        original_query=normalized_query,
                    ),
                )
            elif resolved.kind == ResolveKind.CANDIDATES:
                response = PublicResolution(
                    kind=ResolveKind.CANDIDATES,
                    candidates=[
                        self._public_identity(
                            identity,
                            requester_id=requester_id,
                            match_method="user_selected",
                            original_query=normalized_query,
                        )
                        for identity in resolved.identities
                    ],
                )
            elif resolved.kind == ResolveKind.NOT_FOUND:
                response = PublicResolution(kind=ResolveKind.NOT_FOUND)
            else:
                response = PublicResolution(
                    kind=ResolveKind.BLOCKED,
                    # 上游 reason_code 不属于公开契约，统一映射以避免泄漏错误正文。
                    reason="provider_unavailable",
                )
        except Exception as exc:
            # 不记录异常正文；上游错误可能含 Authorization 或账户信息。
            logger.warning("QCC 主体解析失败，异常类型=%s", type(exc).__name__)
            self.ledger.finalize_operation(
                decision.reservation_id,
                result=None,
                safe_reason="provider_unavailable",
                actual_points=TOOL_COST_CATALOG["identity.resolve"],
                actual_calls=1,
            )
            return PublicResolution(
                kind=ResolveKind.BLOCKED, reason="provider_unavailable"
            )

        self.ledger.finalize_operation(
            decision.reservation_id,
            result=response.model_dump(mode="json"),
            safe_reason=None,
            actual_points=TOOL_COST_CATALOG["identity.resolve"],
            actual_calls=1,
        )
        return response
