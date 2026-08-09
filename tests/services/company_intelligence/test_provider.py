import pytest

from backend.services.company_intelligence.models import (
    CollectionStatus,
    CompanyIdentity,
    ProviderCallResult,
    ResolveKind,
    ResolveResult,
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
    registration = ProviderCallResult(
        capability="company.registration",
        status=CollectionStatus.SUCCEEDED_EMPTY,
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
