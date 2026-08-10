from __future__ import annotations

import pytest

import backend.services.company_intelligence.runtime as runtime_module
from backend.services.company_intelligence.collection import (
    PreparationKind,
    ProfessionalPreparation,
)
from backend.services.company_intelligence.config import ProfessionalDataSettings
from backend.services.company_intelligence.ledger import InMemoryUsageLedger
from backend.services.company_intelligence.mongo_ledger import (
    MongoLedgerUnavailable,
)
from backend.services.company_intelligence.runtime import (
    CompanyIntelligenceRuntime,
)


class PersistentLedgerStub:
    persistent = True


def test_configure_mongo_ledger_replaces_memory_only_after_success(
    monkeypatch,
) -> None:
    runtime = CompanyIntelligenceRuntime.from_env({})
    persistent = PersistentLedgerStub()
    database = object()
    monkeypatch.setattr(
        runtime_module, "MongoUsageLedger", lambda candidate: persistent
    )

    runtime.configure_mongo_ledger(database)

    assert runtime.ledger is persistent


def test_configure_mongo_ledger_preserves_memory_when_bootstrap_fails(
    monkeypatch,
) -> None:
    runtime = CompanyIntelligenceRuntime.from_env({})
    original = runtime.ledger

    def fail(_database):
        raise MongoLedgerUnavailable("事务不可用")

    monkeypatch.setattr(runtime_module, "MongoUsageLedger", fail)

    with pytest.raises(MongoLedgerUnavailable, match="事务不可用"):
        runtime.configure_mongo_ledger(object())
    assert runtime.ledger is original


@pytest.mark.asyncio
async def test_professional_entrypoints_share_runtime_concurrency_limiter(
    monkeypatch,
) -> None:
    captured_limiters = []
    prepared = object()
    evidence = object()

    class CollectionServiceStub:
        def __init__(self, *, concurrency_limiter, **_kwargs) -> None:
            captured_limiters.append(concurrency_limiter)

        def prepare(self, **_kwargs):
            return prepared

        async def collect(self, candidate):
            assert candidate is prepared
            return evidence

    monkeypatch.setattr(
        runtime_module,
        "ProfessionalCollectionService",
        CollectionServiceStub,
    )
    settings = ProfessionalDataSettings.from_env({"QCC_MAX_CONCURRENCY": "2"})
    runtime = CompanyIntelligenceRuntime(
        settings=settings,
        ledger=InMemoryUsageLedger(),
    )

    preparation = runtime.prepare_professional_research(
        job_id="job-1",
        resolution_token="signed-token",
        client_ip="127.0.0.1",
    )
    result = await runtime.collect_professional_research(preparation)

    assert result is evidence
    assert len(captured_limiters) == 2
    assert captured_limiters[0] is captured_limiters[1]


def test_abandon_professional_research_finalizes_without_usage() -> None:
    class FinalizingLedgerStub:
        persistent = True

        def __init__(self) -> None:
            self.calls = []

        def finalize_operation(self, reservation_id, **kwargs) -> None:
            self.calls.append((reservation_id, kwargs))

    ledger = FinalizingLedgerStub()
    runtime = CompanyIntelligenceRuntime(
        settings=ProfessionalDataSettings.from_env({}),
        ledger=ledger,
    )

    runtime.abandon_professional_research(
        ProfessionalPreparation(
            kind=PreparationKind.READY,
            reservation_id="reservation-1",
        )
    )

    assert ledger.calls == [
        (
            "reservation-1",
            {
                "result": None,
                "safe_reason": "professional_start_failed",
                "actual_points": 0,
                "actual_calls": 0,
            },
        )
    ]
