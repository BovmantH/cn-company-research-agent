from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from backend.services.company_intelligence.config import DATA_CAPABILITIES
from backend.services.company_intelligence.ledger import (
    BudgetLimits,
    BudgetRequest,
    InMemoryUsageLedger,
    OperationStatus,
    operation_fingerprint,
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
        request_fingerprint=operation_fingerprint("query-a"),
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
        request_fingerprint=operation_fingerprint("query-a"),
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
        assert "超过预留" in str(exc)
    else:
        raise AssertionError("预期超出预留的结算会失败")


def test_settlement_is_immutable_but_same_retry_is_idempotent() -> None:
    ledger = InMemoryUsageLedger()
    decision = ledger.reserve(_request("one", "job-1"), LIMITS)
    assert decision.reservation_id
    ledger.settle(decision.reservation_id, actual_points=20, actual_calls=1)
    ledger.settle(decision.reservation_id, actual_points=20, actual_calls=1)
    try:
        ledger.settle(decision.reservation_id, actual_points=0, actual_calls=0)
    except ValueError as exc:
        assert "已按不同用量结算" in str(exc)
    else:
        raise AssertionError("冲突的二次结算必须失败")


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
        request_fingerprint=operation_fingerprint("query-a"),
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
        request_fingerprint=operation_fingerprint("query-a"),
    )
    unknown = BudgetRequest(
        idempotency_key="unknown",
        job_id="job-2",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=("cheap.fake.tool",),
        request_fingerprint=operation_fingerprint("query-a"),
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
        request_fingerprint=operation_fingerprint("query-a"),
    )
    assert ledger.reserve(resolution, LIMITS).allowed

    lowball = BudgetRequest(
        idempotency_key="lowball",
        job_id="job-1",
        requester_id="requester-b",
        plan="professional_research",
        capabilities=("company.registration",),
        request_fingerprint=operation_fingerprint("query-a"),
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


def test_same_key_and_plan_with_different_request_fingerprint_is_conflict() -> None:
    ledger = InMemoryUsageLedger()
    assert ledger.reserve(_request("same", "job-1"), LIMITS).allowed
    changed_query = BudgetRequest(
        idempotency_key="same",
        job_id="job-2",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=FULL_PLAN,
        request_fingerprint=operation_fingerprint("query-b"),
    )
    decision = ledger.reserve(changed_query, LIMITS)
    assert decision.allowed is False
    assert decision.reason == "idempotency_conflict"


def test_completed_operation_result_is_replayed_without_mutable_alias() -> None:
    ledger = InMemoryUsageLedger()
    first = ledger.reserve(_request("same", "job-1"), LIMITS)
    assert first.reservation_id
    ledger.complete_operation(first.reservation_id, {"kind": "not_found", "items": []})

    replay = ledger.reserve(_request("same", "job-2"), LIMITS)
    assert replay.replayed is True
    assert replay.operation_status == OperationStatus.COMPLETED
    assert replay.result == {"kind": "not_found", "items": []}
    assert replay.result is not None
    replay.result["items"].append("tampered")

    second_replay = ledger.reserve(_request("same", "job-3"), LIMITS)
    assert second_replay.result == {"kind": "not_found", "items": []}


def test_in_progress_and_failed_operation_states_are_visible_to_replayers() -> None:
    ledger = InMemoryUsageLedger()
    first = ledger.reserve(_request("same", "job-1"), LIMITS)
    assert first.reservation_id
    in_progress = ledger.reserve(_request("same", "job-2"), LIMITS)
    assert in_progress.operation_status == OperationStatus.IN_PROGRESS

    ledger.fail_operation(first.reservation_id, "provider_unavailable")
    failed = ledger.reserve(_request("same", "job-3"), LIMITS)
    assert failed.operation_status == OperationStatus.FAILED
    assert failed.reason == "provider_unavailable"


def test_finalize_operation_atomically_sets_terminal_and_usage() -> None:
    ledger = InMemoryUsageLedger()
    first = ledger.reserve(_request("finalize", "job-1"), LIMITS)
    assert first.reservation_id
    result = {"kind": "not_found", "items": []}

    ledger.finalize_operation(
        first.reservation_id,
        result=result,
        safe_reason=None,
        actual_points=20,
        actual_calls=1,
    )
    ledger.finalize_operation(
        first.reservation_id,
        result=result,
        safe_reason=None,
        actual_points=20,
        actual_calls=1,
    )

    replay = ledger.reserve(_request("finalize", "job-2"), LIMITS)
    assert replay.operation_status == OperationStatus.COMPLETED
    assert replay.result == result
    with pytest.raises(ValueError, match="已按不同用量结算"):
        ledger.finalize_operation(
            first.reservation_id,
            result=result,
            safe_reason=None,
            actual_points=0,
            actual_calls=0,
        )


def test_reserve_with_token_replays_without_consuming_twice() -> None:
    ledger = InMemoryUsageLedger()
    token_id = "a" * 32
    expires_at = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())

    first = ledger.reserve_with_token(
        _request("professional-token", "job-1"),
        LIMITS,
        token_id=token_id,
        token_expires_at=expires_at,
    )
    replay = ledger.reserve_with_token(
        _request("professional-token", "job-2"),
        LIMITS,
        token_id=token_id,
        token_expires_at=expires_at,
    )

    assert first.allowed is True
    assert replay.allowed is True
    assert replay.replayed is True
    assert replay.reservation_id == first.reservation_id


def test_same_token_cannot_create_two_different_reservations() -> None:
    ledger = InMemoryUsageLedger()
    token_id = "b" * 32
    expires_at = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())
    limits = BudgetLimits(
        max_points_per_job=220,
        max_calls_per_job=11,
        daily_point_budget=440,
        daily_job_limit=2,
        requester_daily_limit=2,
    )

    def reserve(index: int):
        return ledger.reserve_with_token(
            _request(f"token-key-{index}", f"job-{index}"),
            limits,
            token_id=token_id,
            token_expires_at=expires_at,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(reserve, range(2)))

    assert sum(decision.allowed for decision in decisions) == 1
    assert {decision.reason for decision in decisions if not decision.allowed} == {
        "token_already_used"
    }


def test_budget_rejection_does_not_consume_token() -> None:
    ledger = InMemoryUsageLedger()
    token_id = "c" * 32
    expires_at = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())
    blocked_limits = BudgetLimits(
        max_points_per_job=1,
        max_calls_per_job=11,
        daily_point_budget=440,
        daily_job_limit=2,
        requester_daily_limit=2,
    )

    blocked = ledger.reserve_with_token(
        _request("blocked-token", "job-1"),
        blocked_limits,
        token_id=token_id,
        token_expires_at=expires_at,
    )

    assert blocked.reason == "job_point_limit"
    assert ledger.consume_token(token_id, expires_at) is True


def test_operation_can_be_claimed_by_only_one_executor() -> None:
    ledger = InMemoryUsageLedger()
    reservation = ledger.reserve(_request("claim", "job-1"), LIMITS)
    assert reservation.reservation_id

    assert ledger.claim_operation(reservation.reservation_id) is True
    assert ledger.claim_operation(reservation.reservation_id) is False

    with pytest.raises(KeyError, match="未知的预算预留"):
        ledger.claim_operation("missing")
