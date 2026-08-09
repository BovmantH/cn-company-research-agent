from concurrent.futures import ThreadPoolExecutor

from backend.services.company_intelligence.config import DATA_CAPABILITIES
from backend.services.company_intelligence.ledger import (
    BudgetLimits,
    BudgetRequest,
    InMemoryUsageLedger,
)


FULL_PLAN = tuple(DATA_CAPABILITIES)


LIMITS = BudgetLimits(
    max_points_per_job=220,
    max_calls_per_job=11,
    daily_point_budget=440,
    daily_job_limit=2,
    requester_daily_limit=1,
)


def _request(key: str, job: str, requester: str = "requester-a") -> BudgetRequest:
    return BudgetRequest(
        idempotency_key=key,
        job_id=job,
        requester_id=requester,
        plan="professional_research",
        capabilities=FULL_PLAN,
    )


def test_same_idempotency_key_replays_same_reservation() -> None:
    ledger = InMemoryUsageLedger()
    first = ledger.reserve(_request("same", "job-1"), LIMITS)
    second = ledger.reserve(_request("same", "job-2"), LIMITS)
    assert first.allowed and second.allowed
    assert second.replayed is True
    assert second.job_id == "job-1"
    assert second.reservation_id == first.reservation_id


def test_same_requester_and_key_with_different_payload_is_conflict() -> None:
    ledger = InMemoryUsageLedger()
    assert ledger.reserve(_request("same", "job-1"), LIMITS).allowed
    changed = BudgetRequest(
        idempotency_key="same",
        job_id="job-2",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=FULL_PLAN[:-1],
    )
    decision = ledger.reserve(changed, LIMITS)
    assert decision.allowed is False
    assert decision.reason == "idempotency_conflict"


def test_same_raw_key_is_namespaced_by_requester() -> None:
    ledger = InMemoryUsageLedger()
    assert ledger.reserve(_request("same", "job-1", "a"), LIMITS).allowed
    assert ledger.reserve(_request("same", "job-2", "b"), LIMITS).allowed


def test_requester_limit_blocks_before_second_reservation() -> None:
    ledger = InMemoryUsageLedger()
    assert ledger.reserve(_request("one", "job-1"), LIMITS).allowed
    blocked = ledger.reserve(_request("two", "job-2"), LIMITS)
    assert blocked.allowed is False
    assert blocked.reason == "requester_daily_limit"


def test_daily_budget_is_atomic_across_requesters() -> None:
    ledger = InMemoryUsageLedger()
    assert ledger.reserve(_request("one", "job-1", "a"), LIMITS).allowed
    assert ledger.reserve(_request("two", "job-2", "b"), LIMITS).allowed
    blocked = ledger.reserve(_request("three", "job-3", "c"), LIMITS)
    assert blocked.allowed is False
    assert blocked.reason in {"daily_job_limit", "daily_point_budget"}


def test_settlement_cannot_exceed_reservation() -> None:
    ledger = InMemoryUsageLedger()
    decision = ledger.reserve(_request("one", "job-1"), LIMITS)
    assert decision.reservation_id
    try:
        ledger.settle(decision.reservation_id, actual_points=221, actual_calls=11)
    except ValueError as exc:
        assert "exceed" in str(exc)
    else:
        raise AssertionError("expected settlement overflow to fail")


def test_settlement_is_immutable_but_same_retry_is_idempotent() -> None:
    ledger = InMemoryUsageLedger()
    decision = ledger.reserve(_request("one", "job-1"), LIMITS)
    assert decision.reservation_id
    ledger.settle(decision.reservation_id, actual_points=20, actual_calls=1)
    ledger.settle(decision.reservation_id, actual_points=20, actual_calls=1)
    try:
        ledger.settle(decision.reservation_id, actual_points=0, actual_calls=0)
    except ValueError as exc:
        assert "already settled" in str(exc)
    else:
        raise AssertionError("conflicting second settlement must fail")


def test_call_limit_is_checked_during_reservation() -> None:
    ledger = InMemoryUsageLedger()
    low_call_limits = BudgetLimits(
        max_points_per_job=220,
        max_calls_per_job=9,
        daily_point_budget=440,
        daily_job_limit=2,
        requester_daily_limit=1,
    )
    request = BudgetRequest(
        idempotency_key="too-many-calls",
        job_id="job-1",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=FULL_PLAN,
    )
    decision = ledger.reserve(request, low_call_limits)
    assert decision.allowed is False
    assert decision.reason == "job_call_limit"


def test_unknown_or_duplicate_capability_cannot_lowball_budget() -> None:
    ledger = InMemoryUsageLedger()
    duplicate = BudgetRequest(
        idempotency_key="duplicate",
        job_id="job-1",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=("identity.resolve", "identity.resolve"),
    )
    unknown = BudgetRequest(
        idempotency_key="unknown",
        job_id="job-2",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=("cheap.fake.tool",),
    )
    assert ledger.reserve(duplicate, LIMITS).reason == "invalid_call_plan"
    assert ledger.reserve(unknown, LIMITS).reason == "invalid_call_plan"


def test_only_fixed_plan_shapes_are_accepted() -> None:
    ledger = InMemoryUsageLedger()
    resolution = BudgetRequest(
        idempotency_key="resolution",
        job_id="resolve-1",
        requester_id="requester-a",
        plan="identity_resolution",
        capabilities=("identity.resolve",),
    )
    assert ledger.reserve(resolution, LIMITS).allowed

    lowball = BudgetRequest(
        idempotency_key="lowball",
        job_id="job-1",
        requester_id="requester-b",
        plan="professional_research",
        capabilities=("company.registration",),
    )
    assert ledger.reserve(lowball, LIMITS).reason == "invalid_call_plan"


def test_concurrent_reservations_cannot_overspend_daily_budget() -> None:
    ledger = InMemoryUsageLedger()

    def reserve(index: int) -> bool:
        return ledger.reserve(
            _request(f"key-{index}", f"job-{index}", f"requester-{index}"),
            LIMITS,
        ).allowed

    with ThreadPoolExecutor(max_workers=8) as executor:
        decisions = list(executor.map(reserve, range(8)))
    assert sum(decisions) == 2
