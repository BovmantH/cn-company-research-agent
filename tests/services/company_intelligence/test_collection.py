from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.services.company_intelligence.collection import (
    PreparationKind,
    ProfessionalCollectionAlreadyClaimed,
    ProfessionalCollectionService,
)
from backend.services.company_intelligence.config import (
    DATA_CAPABILITIES,
    FIXED_PLAN_WORST_CASE_POINTS,
    ProfessionalDataSettings,
    TOOL_COST_CATALOG,
)
from backend.services.company_intelligence.ledger import InMemoryUsageLedger
from backend.services.company_intelligence.models import (
    CAPABILITY_CONTRACTS,
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    SourceMetadata,
)
from backend.services.company_intelligence.provider import (
    FakeCompanyIntelligenceProvider,
)
from backend.services.company_intelligence.tokens import (
    ResolutionTokenService,
    requester_fingerprint,
)


def _settings(**overrides: str) -> ProfessionalDataSettings:
    env = {
        "QCC_MCP_ENABLED": "true",
        "QCC_API_KEY": "test-key",
        "QCC_MAX_CALLS_PER_JOB": "11",
        "QCC_MAX_CONCURRENCY": "3",
        "QCC_DAILY_JOB_LIMIT": "20",
        "QCC_REQUESTER_DAILY_LIMIT": "5",
        "QCC_DAILY_POINT_BUDGET": "5000",
        "QCC_MAX_POINTS_PER_JOB": str(FIXED_PLAN_WORST_CASE_POINTS),
        "APP_SIGNING_SECRET": "s" * 32,
        "QCC_ALLOW_UNSAFE_MEMORY_LEDGER": "true",
    }
    env.update(overrides)
    return ProfessionalDataSettings.from_env(env)


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        provider_subject_id="provider-id",
        original_query="示例科技",
        match_method="user_selected",
    )


def _token(
    ledger: InMemoryUsageLedger,
    settings: ProfessionalDataSettings,
    *,
    client_ip: str = "127.0.0.1",
) -> str:
    requester = requester_fingerprint(client_ip, settings.signing_secret)
    return ResolutionTokenService(settings.signing_secret, ledger).issue(
        _identity(), requester
    )


def _empty_result(capability: str) -> EvidenceCollection:
    return EvidenceCollection(
        capability=capability,
        status=CollectionStatus.SUCCEEDED_EMPTY,
        source=SourceMetadata(
            server=CAPABILITY_CONTRACTS[capability][0],
            capability=capability,
            queried_subject=_identity().credit_code,
            queried_at=datetime.now(timezone.utc),
            status=CollectionStatus.SUCCEEDED_EMPTY,
        ),
    )


def _service(
    ledger: InMemoryUsageLedger,
    provider: FakeCompanyIntelligenceProvider | None,
    *,
    settings: ProfessionalDataSettings | None = None,
    provider_ready: bool = True,
    concurrency_limiter: asyncio.Semaphore | None = None,
) -> ProfessionalCollectionService:
    resolved_settings = settings or _settings()
    return ProfessionalCollectionService(
        settings=resolved_settings,
        ledger=ledger,
        provider=provider,
        provider_ready=provider_ready,
        concurrency_limiter=concurrency_limiter
        or asyncio.Semaphore(resolved_settings.max_concurrency),
    )


@pytest.mark.asyncio
async def test_prepare_collect_and_completed_replay_use_fixed_plan_once() -> None:
    ledger = InMemoryUsageLedger()
    settings = _settings()
    provider = FakeCompanyIntelligenceProvider(
        calls={capability: _empty_result(capability) for capability in DATA_CAPABILITIES}
    )
    service = _service(ledger, provider, settings=settings)
    token = _token(ledger, settings)

    prepared = service.prepare(
        job_id="job-1", resolution_token=token, client_ip="127.0.0.1"
    )
    in_progress = service.prepare(
        job_id="job-2", resolution_token=token, client_ip="127.0.0.1"
    )
    evidence = await service.collect(prepared)
    replay = service.prepare(
        job_id="job-3", resolution_token=token, client_ip="127.0.0.1"
    )

    assert prepared.kind == PreparationKind.READY
    assert in_progress.kind == PreparationKind.IN_PROGRESS
    assert in_progress.job_id == "job-1"
    assert set(evidence.collections) == set(DATA_CAPABILITIES)
    assert replay.kind == PreparationKind.REPLAYED
    assert replay.job_id == "job-1"
    assert replay.evidence == evidence
    assert [entry[0] for entry in provider.call_log] == list(DATA_CAPABILITIES)
    reservation = ledger._reservations[prepared.reservation_id]
    assert reservation["actual_calls"] == len(DATA_CAPABILITIES)
    assert reservation["actual_points"] == sum(
        TOOL_COST_CATALOG[capability] for capability in DATA_CAPABILITIES
    )


def test_invalid_token_or_disabled_capability_never_reserves_budget() -> None:
    ledger = InMemoryUsageLedger()
    provider = FakeCompanyIntelligenceProvider()
    invalid = _service(ledger, provider).prepare(
        job_id="job-1",
        resolution_token="invalid-token",
        client_ip="127.0.0.1",
    )
    disabled_settings = _settings(QCC_MCP_ENABLED="false")
    disabled = _service(
        ledger, provider, settings=disabled_settings
    ).prepare(
        job_id="job-2",
        resolution_token="still-not-inspected",
        client_ip="127.0.0.1",
    )

    assert invalid.kind == PreparationKind.BLOCKED
    assert invalid.reason_code == "identity_unconfirmed"
    assert disabled.kind == PreparationKind.BLOCKED
    assert disabled.reason_code == "not_configured"
    assert ledger._reservations == {}


@pytest.mark.asyncio
async def test_single_provider_failure_degrades_only_that_capability(caplog) -> None:
    class PartlyFailingProvider(FakeCompanyIntelligenceProvider):
        async def call(self, capability, identity):
            if capability == "risk.enforcement":
                self.call_log.append((capability, identity.credit_code))
                raise RuntimeError("Authorization: Bearer upstream-secret")
            return await super().call(capability, identity)

    ledger = InMemoryUsageLedger()
    settings = _settings()
    provider = PartlyFailingProvider(
        calls={capability: _empty_result(capability) for capability in DATA_CAPABILITIES}
    )
    service = _service(ledger, provider, settings=settings)
    prepared = service.prepare(
        job_id="job-1",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )

    evidence = await service.collect(prepared)

    assert evidence.collections["risk.enforcement"].status == CollectionStatus.FAILED
    assert (
        evidence.collections["risk.enforcement"].reason_code
        == "provider_call_failed"
    )
    assert evidence.collections["company.registration"].status == CollectionStatus.SUCCEEDED_EMPTY
    assert "upstream-secret" not in caplog.text


@pytest.mark.asyncio
async def test_collection_respects_configured_concurrency_limit() -> None:
    class ConcurrencyProvider(FakeCompanyIntelligenceProvider):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.maximum = 0

        async def call(self, capability, identity):
            self.call_log.append((capability, identity.credit_code))
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return _empty_result(capability)

    ledger = InMemoryUsageLedger()
    settings = _settings(QCC_MAX_CONCURRENCY="2")
    provider = ConcurrencyProvider()
    service = _service(ledger, provider, settings=settings)
    prepared = service.prepare(
        job_id="job-1",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )

    await service.collect(prepared)

    assert provider.maximum == 2


@pytest.mark.asyncio
async def test_concurrency_limit_is_shared_across_jobs() -> None:
    class ConcurrencyProvider(FakeCompanyIntelligenceProvider):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.maximum = 0

        async def call(self, capability, identity):
            self.call_log.append((capability, identity.credit_code))
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return _empty_result(capability)

    ledger = InMemoryUsageLedger()
    settings = _settings(QCC_MAX_CONCURRENCY="2")
    provider = ConcurrencyProvider()
    limiter = asyncio.Semaphore(settings.max_concurrency)
    service = _service(
        ledger,
        provider,
        settings=settings,
        concurrency_limiter=limiter,
    )
    first = service.prepare(
        job_id="job-1",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )
    second = service.prepare(
        job_id="job-2",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )

    await asyncio.gather(service.collect(first), service.collect(second))

    assert provider.maximum == 2
    assert len(provider.call_log) == len(DATA_CAPABILITIES) * 2


@pytest.mark.asyncio
async def test_ready_preparation_cannot_execute_twice() -> None:
    ledger = InMemoryUsageLedger()
    settings = _settings()
    provider = FakeCompanyIntelligenceProvider(
        calls={capability: _empty_result(capability) for capability in DATA_CAPABILITIES}
    )
    service = _service(ledger, provider, settings=settings)
    prepared = service.prepare(
        job_id="job-1",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )

    await service.collect(prepared)
    with pytest.raises(ProfessionalCollectionAlreadyClaimed):
        await service.collect(prepared)

    assert len(provider.call_log) == len(DATA_CAPABILITIES)


@pytest.mark.asyncio
async def test_cancellation_waits_for_siblings_before_finalizing() -> None:
    class CancellingProvider(FakeCompanyIntelligenceProvider):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0

        async def call(self, capability, identity):
            self.call_log.append((capability, identity.credit_code))
            self.active += 1
            try:
                if capability == DATA_CAPABILITIES[0]:
                    await asyncio.sleep(0)
                    raise asyncio.CancelledError
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    ledger = InMemoryUsageLedger()
    settings = _settings(QCC_MAX_CONCURRENCY="3")
    provider = CancellingProvider()
    service = _service(ledger, provider, settings=settings)
    prepared = service.prepare(
        job_id="job-1",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )

    with pytest.raises(asyncio.CancelledError):
        await service.collect(prepared)

    assert provider.active == 0
    reservation = ledger._reservations[prepared.reservation_id]
    assert reservation["operation_status"] == "failed"
    assert reservation["actual_calls"] == len(provider.call_log)
    assert reservation["actual_points"] == sum(
        TOOL_COST_CATALOG[capability]
        for capability, _ in provider.call_log
    )


@pytest.mark.asyncio
async def test_provider_becoming_unavailable_releases_full_reservation() -> None:
    ledger = InMemoryUsageLedger()
    settings = _settings()
    service = _service(ledger, None, settings=settings, provider_ready=True)
    prepared = service.prepare(
        job_id="job-1",
        resolution_token=_token(ledger, settings),
        client_ip="127.0.0.1",
    )

    evidence = await service.collect(prepared)

    assert {
        collection.status for collection in evidence.collections.values()
    } == {CollectionStatus.UNAVAILABLE}
    reservation = ledger._reservations[prepared.reservation_id]
    assert reservation["actual_calls"] == 0
    assert reservation["actual_points"] == 0
