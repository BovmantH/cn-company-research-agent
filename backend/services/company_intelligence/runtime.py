"""FastAPI 与企业情报模块之间的最小运行时边界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .config import CapabilityPolicy, CapabilityState, ProfessionalDataSettings
from .ledger import InMemoryUsageLedger


class LedgerState(Protocol):
    @property
    def persistent(self) -> bool: ...


@dataclass
class CompanyIntelligenceRuntime:
    settings: ProfessionalDataSettings
    ledger: LedgerState
    provider_ready: bool = False
    deployment_budget_exhausted: bool = False

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "CompanyIntelligenceRuntime":
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
