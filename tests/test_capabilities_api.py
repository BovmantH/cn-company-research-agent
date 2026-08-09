from fastapi.testclient import TestClient

from application import app
from backend.services.company_intelligence.config import (
    FIXED_PLAN_WORST_CASE_POINTS,
    ProfessionalDataSettings,
)
from backend.services.company_intelligence.runtime import CompanyIntelligenceRuntime


class PersistentLedgerStub:
    persistent = True


def _enabled_settings() -> ProfessionalDataSettings:
    return ProfessionalDataSettings.from_env(
        {
            "QCC_MCP_ENABLED": "true",
            "QCC_API_KEY": "secret-that-must-not-be-returned",
            "QCC_MAX_CALLS_PER_JOB": "11",
            "QCC_MAX_CONCURRENCY": "3",
            "QCC_DAILY_JOB_LIMIT": "20",
            "QCC_REQUESTER_DAILY_LIMIT": "2",
            "QCC_DAILY_POINT_BUDGET": "5000",
            "QCC_MAX_POINTS_PER_JOB": str(FIXED_PLAN_WORST_CASE_POINTS),
            "APP_SIGNING_SECRET": "s" * 32,
        }
    )


def test_capabilities_is_safely_disabled_by_default() -> None:
    original = app.state.company_intelligence
    app.state.company_intelligence = CompanyIntelligenceRuntime.from_env({})
    try:
        response = TestClient(app).get("/capabilities")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    assert response.json() == {
        "professional_company_data": {
            "enabled": False,
            "provider": "qcc_mcp",
            "billing_mode": "deployment_byok",
            "requires_confirmation": True,
            "reason": "not_configured",
        }
    }


def test_capabilities_exposes_no_secret_when_enabled() -> None:
    original = app.state.company_intelligence
    app.state.company_intelligence = CompanyIntelligenceRuntime(
        settings=_enabled_settings(),
        ledger=PersistentLedgerStub(),
        provider_ready=True,
    )
    try:
        response = TestClient(app).get("/capabilities")
    finally:
        app.state.company_intelligence = original

    assert response.status_code == 200
    assert response.json()["professional_company_data"]["enabled"] is True
    assert "secret-that-must-not-be-returned" not in response.text
