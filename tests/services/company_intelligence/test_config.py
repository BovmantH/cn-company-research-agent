from backend.services.company_intelligence.config import (
    FIXED_PLAN_WORST_CASE_POINTS,
    CapabilityPolicy,
    CapabilityReason,
    ProfessionalDataSettings,
)


def _env(**overrides: str) -> dict[str, str]:
    values = {
        "QCC_MCP_ENABLED": "true",
        "QCC_API_KEY": "test-key",
        "QCC_MAX_CALLS_PER_JOB": "11",
        "QCC_MAX_CONCURRENCY": "3",
        "QCC_DAILY_JOB_LIMIT": "20",
        "QCC_REQUESTER_DAILY_LIMIT": "2",
        "QCC_DAILY_POINT_BUDGET": "5000",
        "QCC_MAX_POINTS_PER_JOB": str(FIXED_PLAN_WORST_CASE_POINTS),
        "APP_SIGNING_SECRET": "s" * 32,
    }
    values.update(overrides)
    return values


def test_disabled_by_default() -> None:
    state = CapabilityPolicy(ProfessionalDataSettings.from_env({})).evaluate(
        provider_ready=True, persistent_ledger=True
    )
    assert state.enabled is False
    assert state.reason == CapabilityReason.NOT_CONFIGURED


def test_requires_persistent_ledger_for_public_mode() -> None:
    state = CapabilityPolicy(ProfessionalDataSettings.from_env(_env())).evaluate(
        provider_ready=True, persistent_ledger=False
    )
    assert state.reason == CapabilityReason.LEDGER_UNAVAILABLE


def test_rejects_budget_below_fixed_plan_worst_case() -> None:
    settings = ProfessionalDataSettings.from_env(
        _env(QCC_MAX_POINTS_PER_JOB=str(FIXED_PLAN_WORST_CASE_POINTS - 1))
    )
    state = CapabilityPolicy(settings).evaluate(
        provider_ready=True, persistent_ledger=True
    )
    assert state.reason == CapabilityReason.BUDGET_NOT_CONFIGURED


def test_enabled_only_when_every_gate_passes() -> None:
    state = CapabilityPolicy(ProfessionalDataSettings.from_env(_env())).evaluate(
        provider_ready=True, persistent_ledger=True
    )
    assert state.as_dict() == {
        "enabled": True,
        "provider": "qcc_mcp",
        "billing_mode": "deployment_byok",
        "requires_confirmation": True,
        "reason": None,
    }


def test_invalid_numeric_configuration_fails_closed() -> None:
    settings = ProfessionalDataSettings.from_env(_env(QCC_MAX_CALLS_PER_JOB="eleven"))
    state = CapabilityPolicy(settings).evaluate(
        provider_ready=True, persistent_ledger=True
    )
    assert state.reason == CapabilityReason.BUDGET_NOT_CONFIGURED
