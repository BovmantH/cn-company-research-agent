"""专业数据配置与公开能力判定。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

REQUIRED_CAPABILITIES: tuple[str, ...] = (
    "identity.resolve",
    "company.registration",
    "company.shareholders",
    "company.changes",
    "risk.case_filings",
    "risk.judicial_documents",
    "risk.enforcement",
    "risk.dishonest",
    "risk.high_consumption",
    "risk.bankruptcy",
    "risk.serious_violation",
)
DATA_CAPABILITIES: tuple[str, ...] = REQUIRED_CAPABILITIES[1:]

# 企查查官方说明当前单工具为 1/3/5/20 积分。具体工具价格可能变化，
# 因此本地准入一律按公开最高档 20 积分保守预留；上游账单仍是最终权威。
TOOL_COST_CATALOG: Mapping[str, int] = {
    capability: 20 for capability in REQUIRED_CAPABILITIES
}
TOOL_COST_CATALOG_VERIFIED_ON = "2026-08-09"
FIXED_PLAN_WORST_CASE_POINTS = sum(TOOL_COST_CATALOG.values())


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        # 配置拼写错误时必须默认关闭，不能静默退回一个可能允许付费调用的默认值。
        return -1


class CapabilityReason(StrEnum):
    NOT_CONFIGURED = "not_configured"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    LEDGER_UNAVAILABLE = "ledger_unavailable"
    BUDGET_NOT_CONFIGURED = "budget_not_configured"
    SIGNING_SECRET_MISSING = "signing_secret_missing"
    DEPLOYMENT_BUDGET_EXHAUSTED = "deployment_budget_exhausted"


@dataclass(frozen=True)
class ProfessionalDataSettings:
    enabled: bool
    api_key: str
    company_mcp_url: str
    risk_mcp_url: str
    max_calls_per_job: int
    max_concurrency: int
    daily_job_limit: int
    requester_daily_limit: int
    daily_point_budget: int
    max_points_per_job: int
    company_cache_ttl_hours: int
    risk_cache_ttl_hours: int
    empty_risk_cache_ttl_hours: int
    allowed_origins: tuple[str, ...]
    trusted_proxy_cidrs: tuple[str, ...]
    signing_secret: str
    allow_unsafe_memory_ledger: bool

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "ProfessionalDataSettings":
        """读取部署配置；任何非法数值都会在能力判定阶段按关闭处理。"""
        source = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return source.get(name, default)

        return cls(
            enabled=_as_bool(get("QCC_MCP_ENABLED")),
            api_key=get("QCC_API_KEY").strip(),
            company_mcp_url=get(
                "QCC_COMPANY_MCP_URL", "https://agent.qcc.com/mcp/company/stream"
            ).strip(),
            risk_mcp_url=get(
                "QCC_RISK_MCP_URL", "https://agent.qcc.com/mcp/risk/stream"
            ).strip(),
            max_calls_per_job=_as_int(get("QCC_MAX_CALLS_PER_JOB"), 11),
            max_concurrency=_as_int(get("QCC_MAX_CONCURRENCY"), 3),
            daily_job_limit=_as_int(get("QCC_DAILY_JOB_LIMIT"), 0),
            requester_daily_limit=_as_int(get("QCC_REQUESTER_DAILY_LIMIT"), 0),
            daily_point_budget=_as_int(get("QCC_DAILY_POINT_BUDGET"), 0),
            max_points_per_job=_as_int(get("QCC_MAX_POINTS_PER_JOB"), 0),
            company_cache_ttl_hours=_as_int(get("QCC_COMPANY_CACHE_TTL_HOURS"), 24),
            risk_cache_ttl_hours=_as_int(get("QCC_RISK_CACHE_TTL_HOURS"), 12),
            empty_risk_cache_ttl_hours=_as_int(
                get("QCC_EMPTY_RISK_CACHE_TTL_HOURS"), 6
            ),
            allowed_origins=tuple(
                value.strip()
                for value in get("ALLOWED_ORIGINS", "http://localhost:5174").split(",")
                if value.strip()
            ),
            trusted_proxy_cidrs=tuple(
                value.strip()
                for value in get("TRUSTED_PROXY_CIDRS").split(",")
                if value.strip()
            ),
            signing_secret=get("APP_SIGNING_SECRET").strip(),
            allow_unsafe_memory_ledger=_as_bool(get("QCC_ALLOW_UNSAFE_MEMORY_LEDGER")),
        )


@dataclass(frozen=True)
class CapabilityState:
    enabled: bool
    provider: str = "qcc_mcp"
    billing_mode: str = "deployment_byok"
    requires_confirmation: bool = True
    reason: CapabilityReason | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "billing_mode": self.billing_mode,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason.value if self.reason else None,
        }


class CapabilityPolicy:
    def __init__(self, settings: ProfessionalDataSettings) -> None:
        self.settings = settings

    def evaluate(
        self,
        *,
        provider_ready: bool,
        persistent_ledger: bool,
        deployment_budget_exhausted: bool = False,
    ) -> CapabilityState:
        """仅在密钥、签名、持久账本和全部预算护栏就绪时开放付费能力。"""
        cfg = self.settings
        if not cfg.enabled or not cfg.api_key:
            return CapabilityState(False, reason=CapabilityReason.NOT_CONFIGURED)
        if not cfg.signing_secret or len(cfg.signing_secret.encode("utf-8")) < 32:
            return CapabilityState(
                False, reason=CapabilityReason.SIGNING_SECRET_MISSING
            )
        if not persistent_ledger and not cfg.allow_unsafe_memory_ledger:
            return CapabilityState(False, reason=CapabilityReason.LEDGER_UNAVAILABLE)
        if (
            cfg.max_calls_per_job < len(REQUIRED_CAPABILITIES)
            or cfg.max_concurrency <= 0
            or cfg.daily_job_limit <= 0
            or cfg.requester_daily_limit <= 0
            or cfg.daily_point_budget <= 0
            or cfg.max_points_per_job < FIXED_PLAN_WORST_CASE_POINTS
            or cfg.company_cache_ttl_hours <= 0
            or cfg.risk_cache_ttl_hours <= 0
            or cfg.empty_risk_cache_ttl_hours <= 0
        ):
            return CapabilityState(False, reason=CapabilityReason.BUDGET_NOT_CONFIGURED)
        if deployment_budget_exhausted:
            return CapabilityState(
                False, reason=CapabilityReason.DEPLOYMENT_BUDGET_EXHAUSTED
            )
        if not provider_ready:
            return CapabilityState(False, reason=CapabilityReason.PROVIDER_UNAVAILABLE)
        return CapabilityState(True)
