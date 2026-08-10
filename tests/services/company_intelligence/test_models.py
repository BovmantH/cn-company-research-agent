from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.services.company_intelligence.models import (
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    JudicialCaseRecord,
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


def _source(
    capability: str,
    status: CollectionStatus,
    *,
    queried_at: datetime | None = None,
) -> SourceMetadata:
    server = "qcc-company" if capability.startswith("company.") else "qcc-risk"
    return SourceMetadata(
        server=server,
        capability=capability,
        queried_subject="示例科技有限公司",
        queried_at=queried_at or datetime.now(timezone.utc),
        status=status,
    )


def test_succeeded_with_records_requires_records() -> None:
    with pytest.raises(ValidationError):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
            source=_source(
                "company.registration", CollectionStatus.SUCCEEDED_WITH_RECORDS
            ),
        )


def test_succeeded_empty_cannot_carry_records() -> None:
    with pytest.raises(ValidationError):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_EMPTY,
            records=[_registration()],
            source=_source("company.registration", CollectionStatus.SUCCEEDED_EMPTY),
        )


def test_failed_is_not_equivalent_to_empty() -> None:
    failed = EvidenceCollection(
        capability="risk.enforcement",
        status=CollectionStatus.FAILED,
        source=_source("risk.enforcement", CollectionStatus.FAILED),
        reason_code="provider_timeout",
    )
    empty = EvidenceCollection(
        capability="risk.enforcement",
        status=CollectionStatus.SUCCEEDED_EMPTY,
        source=_source("risk.enforcement", CollectionStatus.SUCCEEDED_EMPTY),
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
            source=_source("risk.enforcement", CollectionStatus.SUCCEEDED_WITH_RECORDS),
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
            source=_source(
                "company.registration", CollectionStatus.SUCCEEDED_WITH_RECORDS
            ),
        )


def test_provider_statuses_require_collection_source() -> None:
    with pytest.raises(ValidationError, match="集合级来源"):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_EMPTY,
        )
    with pytest.raises(ValidationError, match="集合级来源"):
        EvidenceCollection(
            capability="risk.enforcement",
            status=CollectionStatus.FAILED,
            reason_code="provider_error",
        )


def test_partial_requires_valid_record_reason_and_matching_collection_source() -> None:
    queried_at = datetime.now(timezone.utc)
    source = _source(
        "company.registration",
        CollectionStatus.PARTIAL,
        queried_at=queried_at,
    )
    record = _registration().model_copy(
        update={"source": source.model_copy(update={"record_id": "record-1"})}
    )

    collection = EvidenceCollection(
        capability="company.registration",
        status=CollectionStatus.PARTIAL,
        records=[record],
        source=source,
        reason_code="provider_record_invalid",
    )

    assert collection.records == [record]
    with pytest.raises(ValidationError, match="至少一条"):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.PARTIAL,
            source=source,
            reason_code="provider_record_invalid",
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
            reason_code="not_requested",
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
            reason_code="not_requested",
        )
        for capability in DATA_CAPABILITIES
    }
    first, second = DATA_CAPABILITIES[:2]
    collections[first] = collections[second]
    with pytest.raises(ValidationError, match="key 必须"):
        ProfessionalEvidence(identity=identity, collections=collections)


def test_non_success_status_requires_safe_reason_and_forbids_source_without_call() -> (
    None
):
    with pytest.raises(ValidationError, match="稳定原因码"):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.NOT_REQUESTED,
        )
    with pytest.raises(ValidationError, match="不得包含来源"):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.UNAVAILABLE,
            reason_code="provider_unavailable",
            source=_source("company.registration", CollectionStatus.UNAVAILABLE),
        )
    with pytest.raises(ValidationError):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.FAILED,
            reason_code="Authorization_Bearer_secret",
            source=_source("company.registration", CollectionStatus.FAILED),
        )


def test_collection_source_cannot_impersonate_record_or_another_subject() -> None:
    with pytest.raises(ValidationError, match="记录 ID"):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_EMPTY,
            source=_source(
                "company.registration", CollectionStatus.SUCCEEDED_EMPTY
            ).model_copy(update={"record_id": "record-1"}),
        )

    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    collections = {
        capability: EvidenceCollection(
            capability=capability,
            status=CollectionStatus.NOT_REQUESTED,
            reason_code="not_requested",
        )
        for capability in DATA_CAPABILITIES
    }
    collections["company.registration"] = EvidenceCollection(
        capability="company.registration",
        status=CollectionStatus.SUCCEEDED_EMPTY,
        source=_source("company.registration", CollectionStatus.SUCCEEDED_EMPTY),
    )
    with pytest.raises(ValidationError, match="统一社会信用代码"):
        ProfessionalEvidence(identity=identity, collections=collections)


def test_evidence_text_and_party_lists_have_safe_bounds() -> None:
    source = _source("company.registration", CollectionStatus.SUCCEEDED_WITH_RECORDS)
    with pytest.raises(ValidationError, match="控制字符"):
        RegistrationRecord(legal_representative="张三\n伪造字段", source=source)
    with pytest.raises(ValidationError):
        RegistrationRecord(business_scope="业" * 20_001, source=source)

    case_source = _source("risk.case_filings", CollectionStatus.SUCCEEDED_WITH_RECORDS)
    with pytest.raises(ValidationError):
        JudicialCaseRecord(
            case_number="（2026）苏01民初1号",
            plaintiffs=["原告"] * 201,
            source=case_source,
        )
    with pytest.raises(ValidationError):
        JudicialCaseRecord(
            case_number="（2026）苏01民初1号",
            plaintiffs=["原" * 301],
            source=case_source,
        )
