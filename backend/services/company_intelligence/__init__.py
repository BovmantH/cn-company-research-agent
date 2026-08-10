"""企业工商与司法专业数据边界。

该包与 ``SearchProvider`` 分离：网页检索继续处理 URL/摘要，专业数据模块
只处理可审计的结构化企业事实、预算和 Provider 调用。
"""

from .collection import PreparationKind, ProfessionalPreparation
from .config import CapabilityPolicy, ProfessionalDataSettings
from .ledger import InMemoryUsageLedger, UsageLedger
from .models import (
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    ProfessionalEvidence,
    ResolveKind,
    ResolveResult,
)
from .mongo_ledger import MongoLedgerUnavailable, MongoUsageLedger
from .rendering import (
    MAX_PROFESSIONAL_APPENDIX_BYTES,
    render_professional_coverage_markdown,
    render_professional_evidence_markdown,
)
from .runtime import CompanyIntelligenceRuntime
from .tokens import ResolutionTokenService, requester_fingerprint

__all__ = [
    "CapabilityPolicy",
    "CollectionStatus",
    "CompanyIdentity",
    "CompanyIntelligenceRuntime",
    "EvidenceCollection",
    "InMemoryUsageLedger",
    "MongoLedgerUnavailable",
    "MongoUsageLedger",
    "MAX_PROFESSIONAL_APPENDIX_BYTES",
    "ProfessionalDataSettings",
    "ProfessionalEvidence",
    "ProfessionalPreparation",
    "PreparationKind",
    "ResolutionTokenService",
    "ResolveKind",
    "ResolveResult",
    "UsageLedger",
    "requester_fingerprint",
    "render_professional_coverage_markdown",
    "render_professional_evidence_markdown",
]
