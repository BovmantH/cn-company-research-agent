from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from application import app
from backend.services.company_intelligence.config import (
    FIXED_PLAN_WORST_CASE_POINTS,
    ProfessionalDataSettings,
)
from backend.services.company_intelligence.ledger import InMemoryUsageLedger
from backend.services.company_intelligence.models import (
    CompanyIdentity,
    ResolveKind,
    ResolveResult,
)
from backend.services.company_intelligence.provider import (
    FakeCompanyIntelligenceProvider,
)
from backend.services.company_intelligence.resolution import ResolutionInProgress
from backend.services.company_intelligence.runtime import CompanyIntelligenceRuntime


def _settings(**overrides: str) -> ProfessionalDataSettings:
    env = {
        "QCC_MCP_ENABLED": "true",
        "QCC_API_KEY": "qcc-secret-value",
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


def _identity(query: str = "示例科技") -> CompanyIdentity:
    return CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        registration_status="存续",
        region="江苏省",
        provider_subject_id="internal-provider-id",
        original_query=query,
    )


def _runtime(provider: FakeCompanyIntelligenceProvider) -> CompanyIntelligenceRuntime:
    return CompanyIntelligenceRuntime(
        settings=_settings(),
        ledger=InMemoryUsageLedger(),
        provider=provider,
        provider_ready=True,
    )


def _post(client: TestClient, query: str, key: str = "resolve-key-001"):
    return client.post(
        "/companies/resolve",
        json={"query": query},
        headers={"Idempotency-Key": key},
    )


def test_missing_idempotency_key_is_rejected() -> None:
    response = TestClient(app).post("/companies/resolve", json={"query": "示例科技"})
    assert response.status_code == 422


def test_invalid_idempotency_key_is_rejected() -> None:
    response = TestClient(app).post(
        "/companies/resolve",
        json={"query": "示例科技"},
        headers={"Idempotency-Key": "short"},
    )
    assert response.status_code == 422


def test_disabled_capability_never_calls_provider() -> None:
    provider = FakeCompanyIntelligenceProvider()
    original = app.state.company_intelligence
    app.state.company_intelligence = CompanyIntelligenceRuntime.from_env({})
    app.state.company_intelligence.provider = provider
    try:
        response = _post(TestClient(app), "示例科技")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    assert response.json()["kind"] == "blocked"
    assert response.json()["reason"] == "not_configured"
    assert provider.call_log == []


def test_exact_resolution_returns_minimal_identity_and_signed_token() -> None:
    provider = FakeCompanyIntelligenceProvider(
        resolutions={
            "示例科技": ResolveResult(kind=ResolveKind.EXACT, identities=[_identity()])
        }
    )
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        response = _post(TestClient(app), "示例科技")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "exact"
    assert body["identity"]["company_name"] == "示例科技有限公司"
    assert body["identity"]["credit_code"] == "91320594MA1N00000X"
    assert body["identity"]["resolution_token"].count(".") == 1
    assert "provider_subject_id" not in response.text
    assert "original_query" not in response.text
    assert "qcc-secret-value" not in response.text


def test_same_key_and_query_replays_without_second_provider_call() -> None:
    provider = FakeCompanyIntelligenceProvider(
        resolutions={
            "示例科技": ResolveResult(kind=ResolveKind.EXACT, identities=[_identity()])
        }
    )
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        client = TestClient(app)
        first = _post(client, "示例科技")
        second = _post(client, "示例科技")
    finally:
        app.state.company_intelligence = original

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert provider.call_log == [("identity.resolve", "示例科技")]


def test_same_key_with_different_query_returns_conflict() -> None:
    provider = FakeCompanyIntelligenceProvider(
        resolutions={
            "示例科技": ResolveResult(kind=ResolveKind.EXACT, identities=[_identity()])
        }
    )
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        client = TestClient(app)
        assert _post(client, "示例科技").status_code == 200
        conflict = _post(client, "另一家公司")
    finally:
        app.state.company_intelligence = original

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "idempotency_conflict"
    assert provider.call_log == [("identity.resolve", "示例科技")]


def test_candidates_receive_distinct_tokens_and_no_internal_fields() -> None:
    first = _identity("示例")
    second = CompanyIdentity(
        canonical_name="示例科技集团有限公司",
        credit_code="91320594MA1N00001R",
        registration_status="存续",
        region="上海市",
        provider_subject_id="second-internal-id",
        original_query="示例",
    )
    provider = FakeCompanyIntelligenceProvider(
        resolutions={
            "示例": ResolveResult(
                kind=ResolveKind.CANDIDATES, identities=[first, second]
            )
        }
    )
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        response = _post(TestClient(app), "示例", "resolve-key-candidates")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "candidates"
    assert body["identity"] is None
    assert len(body["candidates"]) == 2
    assert (
        body["candidates"][0]["resolution_token"]
        != body["candidates"][1]["resolution_token"]
    )
    assert "provider_subject_id" not in response.text


def test_not_found_is_distinct_from_provider_failure() -> None:
    provider = FakeCompanyIntelligenceProvider(
        resolutions={"不存在公司": ResolveResult(kind=ResolveKind.NOT_FOUND)}
    )
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        response = _post(TestClient(app), "不存在公司", "resolve-key-not-found")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    assert response.json() == {
        "kind": "not_found",
        "identity": None,
        "candidates": [],
        "reason": None,
    }


def test_provider_block_reason_is_mapped_to_public_reason() -> None:
    provider = FakeCompanyIntelligenceProvider(
        resolutions={
            "示例科技": ResolveResult(
                kind=ResolveKind.BLOCKED,
                reason_code="Authorization_Bearer_upstream_secret",
            )
        }
    )
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        response = _post(TestClient(app), "示例科技", "resolve-key-blocked")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    assert response.json()["reason"] == "provider_unavailable"
    assert "upstream_secret" not in response.text


def test_provider_exception_is_mapped_without_secret_leak(caplog) -> None:
    class FailingProvider(FakeCompanyIntelligenceProvider):
        async def resolve(self, query: str) -> ResolveResult:
            self.call_log.append(("identity.resolve", query))
            raise RuntimeError("Authorization: Bearer upstream-secret")

    provider = FailingProvider()
    original = app.state.company_intelligence
    app.state.company_intelligence = _runtime(provider)
    try:
        response = _post(TestClient(app), "示例科技")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    assert response.json() == {
        "kind": "blocked",
        "identity": None,
        "candidates": [],
        "reason": "provider_unavailable",
    }
    assert "upstream-secret" not in response.text
    assert "upstream-secret" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_replay_does_not_start_second_provider_call() -> None:
    class BlockingProvider(FakeCompanyIntelligenceProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def resolve(self, query: str) -> ResolveResult:
            self.call_log.append(("identity.resolve", query))
            self.started.set()
            await self.release.wait()
            return ResolveResult(kind=ResolveKind.EXACT, identities=[_identity(query)])

    provider = BlockingProvider()
    runtime = _runtime(provider)
    first = asyncio.create_task(
        runtime.resolve_company(
            query="示例科技",
            idempotency_key="resolve-key-concurrent",
            client_ip="127.0.0.1",
        )
    )
    await provider.started.wait()

    with pytest.raises(ResolutionInProgress):
        await runtime.resolve_company(
            query="示例科技",
            idempotency_key="resolve-key-concurrent",
            client_ip="127.0.0.1",
        )
    provider.release.set()
    result = await first

    assert result.kind == ResolveKind.EXACT
    assert provider.call_log == [("identity.resolve", "示例科技")]
