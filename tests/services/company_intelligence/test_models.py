from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.services.company_intelligence.models import (
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    ProfessionalEvidence,
    RegistrationRecord,
    ResolveKind,
    ResolveResult,
    SourceMetadata,
)
from backend.services.company_intelligence.config import DATA_CAPABILITIES


def _registration() -> RegistrationRecord:
    return RegistrationRecord(
        legal_representative="张三",
        source=SourceMetadata(
            server="qcc-company",
            capability="company.registration",
            queried_subject="示例科技有限公司",
            queried_at=datetime.now(timezone.utc),
            status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
        ),
    )


def test_succeeded_with_records_requires_records() -> None:
    with pytest.raises(ValidationError):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
        )


def test_succeeded_empty_cannot_carry_records() -> None:
    with pytest.raises(ValidationError):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_EMPTY,
            records=[_registration()],
        )


def test_failed_is_not_equivalent_to_empty() -> None:
    failed = EvidenceCollection(
        capability="risk.enforcement",
        status=CollectionStatus.FAILED,
        reason_code="provider_timeout",
    )
    empty = EvidenceCollection(
        capability="risk.enforcement",
        status=CollectionStatus.SUCCEEDED_EMPTY,
    )
    assert failed.status != empty.status


def test_resolve_exact_requires_one_identity() -> None:
    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    result = ResolveResult(kind=ResolveKind.EXACT, identities=[identity])
    assert result.identities == [identity]

    with pytest.raises(ValidationError):
        ResolveResult(kind=ResolveKind.EXACT)


def test_collection_rejects_cross_capability_record() -> None:
    with pytest.raises(ValidationError, match="不允许记录类型"):
        EvidenceCollection(
            capability="risk.enforcement",
            status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
            records=[_registration()],
        )


def test_collection_rejects_mismatched_source_status() -> None:
    record = _registration().model_copy(
        update={
            "source": _registration().source.model_copy(
                update={"status": CollectionStatus.PARTIAL}
            )
        }
    )
    with pytest.raises(ValidationError, match="status 与集合不一致"):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
            records=[record],
        )


def test_identity_rejects_invalid_credit_code_and_naive_time() -> None:
    with pytest.raises(ValidationError, match="信用代码"):
        CompanyIdentity(
            canonical_name="示例科技有限公司",
            credit_code="??",
            original_query="示例科技",
        )
    with pytest.raises(ValidationError, match="时区"):
        CompanyIdentity(
            canonical_name="示例科技有限公司",
            credit_code="91320594MA1N00000X",
            original_query="示例科技",
            resolved_at=datetime.now(),
        )


def test_professional_evidence_requires_every_capability_status() -> None:
    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    complete = {
        capability: EvidenceCollection(
            capability=capability,
            status=CollectionStatus.NOT_REQUESTED,
        )
        for capability in DATA_CAPABILITIES
    }
    evidence = ProfessionalEvidence(identity=identity, collections=complete)
    assert set(evidence.collections) == set(DATA_CAPABILITIES)

    incomplete = dict(complete)
    incomplete.pop(DATA_CAPABILITIES[0])
    with pytest.raises(ValidationError, match="覆盖不完整"):
        ProfessionalEvidence(identity=identity, collections=incomplete)


def test_professional_evidence_rejects_key_capability_mismatch() -> None:
    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    collections = {
        capability: EvidenceCollection(
            capability=capability,
            status=CollectionStatus.NOT_REQUESTED,
        )
        for capability in DATA_CAPABILITIES
    }
    first, second = DATA_CAPABILITIES[:2]
    collections[first] = collections[second]
    with pytest.raises(ValidationError, match="key 必须"):
        ProfessionalEvidence(identity=identity, collections=collections)
