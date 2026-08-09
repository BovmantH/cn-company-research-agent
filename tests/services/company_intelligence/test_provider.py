from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.services.company_intelligence.models import (
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    ResolveKind,
    ResolveResult,
    SourceMetadata,
)
from backend.services.company_intelligence.provider import (
    FakeCompanyIntelligenceProvider,
)


@pytest.mark.asyncio
async def test_fake_provider_requires_every_discovered_capability() -> None:
    provider = FakeCompanyIntelligenceProvider(capabilities=frozenset())
    await provider.initialize()
    assert provider.ready is False


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic_and_auditable() -> None:
    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    resolution = ResolveResult(kind=ResolveKind.EXACT, identities=[identity])
    registration = EvidenceCollection(
        capability="company.registration",
        status=CollectionStatus.SUCCEEDED_EMPTY,
        source=SourceMetadata(
            server="qcc-company",
            capability="company.registration",
            queried_subject=identity.credit_code,
            queried_at=datetime.now(timezone.utc),
            status=CollectionStatus.SUCCEEDED_EMPTY,
        ),
    )
    provider = FakeCompanyIntelligenceProvider(
        resolutions={"示例科技": resolution},
        calls={"company.registration": registration},
    )
    await provider.initialize()

    assert provider.ready is True
    assert await provider.resolve("示例科技") == resolution
    assert await provider.call("company.registration", identity) == registration
    assert provider.call_log == [
        ("identity.resolve", "示例科技"),
        ("company.registration", "91320594MA1N00000X"),
    ]


@pytest.mark.asyncio
async def test_fake_provider_never_calls_identity_through_generic_tool_path() -> None:
    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    provider = FakeCompanyIntelligenceProvider()
    await provider.initialize()
    with pytest.raises(ValueError, match="not allowed"):
        await provider.call("identity.resolve", identity)


def test_evidence_collection_rejects_raw_provider_records() -> None:
    source = SourceMetadata(
        server="qcc-company",
        capability="company.registration",
        queried_subject="91320594MA1N00000X",
        status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
    )
    with pytest.raises(ValidationError):
        EvidenceCollection(
            capability="company.registration",
            status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
            records=[{"raw": "provider payload"}],
            source=source,
        )


@pytest.mark.asyncio
async def test_fake_provider_rejects_cross_capability_or_subject_result() -> None:
    identity = CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )
    wrong_capability = EvidenceCollection(
        capability="company.shareholders",
        status=CollectionStatus.SUCCEEDED_EMPTY,
        source=SourceMetadata(
            server="qcc-company",
            capability="company.shareholders",
            queried_subject=identity.credit_code,
            status=CollectionStatus.SUCCEEDED_EMPTY,
        ),
    )
    provider = FakeCompanyIntelligenceProvider(
        calls={"company.registration": wrong_capability}
    )
    await provider.initialize()
    with pytest.raises(ValueError, match="capability mismatch"):
        await provider.call("company.registration", identity)
