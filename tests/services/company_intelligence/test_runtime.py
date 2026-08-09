from __future__ import annotations

import pytest

import backend.services.company_intelligence.runtime as runtime_module
from backend.services.company_intelligence.mongo_ledger import MongoLedgerUnavailable
from backend.services.company_intelligence.runtime import CompanyIntelligenceRuntime


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
