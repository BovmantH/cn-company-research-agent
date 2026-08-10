from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import mongomock
import pytest

from backend.services.company_intelligence.config import (
    DATA_CAPABILITIES,
    TOOL_COST_CATALOG,
)
from backend.services.company_intelligence.ledger import (
    BudgetLimits,
    BudgetRequest,
    OperationStatus,
    operation_fingerprint,
)
from backend.services.company_intelligence.mongo_ledger import (
    MongoLedgerUnavailable,
    MongoUsageLedger,
)

T = TypeVar("T")
pytestmark = pytest.mark.filterwarnings(
    "ignore:datetime.datetime.utcnow.*:DeprecationWarning"
)
FULL_PLAN = tuple(DATA_CAPABILITIES)
FULL_PLAN_POINTS = sum(TOOL_COST_CATALOG[name] for name in FULL_PLAN)
NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)
LIMITS = BudgetLimits(
    max_points_per_job=220,
    max_calls_per_job=11,
    daily_point_budget=FULL_PLAN_POINTS * 2,
    daily_job_limit=8,
    requester_daily_limit=2,
)


class LockedTransactionRunner:
    """让 mongomock 以共享锁模拟事务边界；真实原子性由 Mongo 集成测试验证。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def __call__(self, callback: Callable[[Any], T]) -> T:
        with self._lock:
            return callback(None)


@pytest.fixture
def ledger_pair() -> tuple[MongoUsageLedger, MongoUsageLedger]:
    client = mongomock.MongoClient(tz_aware=True)
    database = client[f"ledger_{uuid.uuid4().hex}"]
    transaction_runner = LockedTransactionRunner()
    kwargs = {
        "now_factory": lambda: NOW,
        "transaction_runner": transaction_runner,
    }
    return MongoUsageLedger(database, **kwargs), MongoUsageLedger(database, **kwargs)


def _request(key: str, job: str, requester: str = "requester-a") -> BudgetRequest:
    return BudgetRequest(
        idempotency_key=key,
        job_id=job,
        requester_id=requester,
        plan="professional_research",
        capabilities=FULL_PLAN,
        request_fingerprint=operation_fingerprint("query-a"),
    )


def test_reservation_replays_after_ledger_is_recreated(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    first = first_ledger.reserve(_request("same-key", "job-1"), LIMITS)
    replay = second_ledger.reserve(_request("same-key", "job-2"), LIMITS)

    assert first.allowed and replay.allowed
    assert replay.replayed is True
    assert replay.reservation_id == first.reservation_id
    assert replay.job_id == "job-1"


def test_two_ledger_instances_cannot_overspend_daily_budget(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    barrier = threading.Barrier(8)

    def reserve(index: int) -> bool:
        barrier.wait()
        ledger = first_ledger if index % 2 else second_ledger
        return ledger.reserve(
            _request(f"key-{index}", f"job-{index}", f"requester-{index}"),
            LIMITS,
        ).allowed

    with ThreadPoolExecutor(max_workers=8) as executor:
        decisions = list(executor.map(reserve, range(8)))

    assert sum(decisions) == 2
    counter = first_ledger._usage_counters.find_one({"_id": "deployment:2026-08-09"})
    assert counter["job_count"] == 2
    assert counter["accounted_points"] == FULL_PLAN_POINTS * 2


def test_same_key_from_two_instances_counts_once(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    barrier = threading.Barrier(2)

    def reserve(ledger: MongoUsageLedger):
        barrier.wait()
        return ledger.reserve(_request("same-key", uuid.uuid4().hex), LIMITS)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(reserve, ledger_pair))

    assert first.reservation_id == second.reservation_id
    assert sum((first.replayed, second.replayed)) == 1
    counter = first_ledger._usage_counters.find_one({"_id": "deployment:2026-08-09"})
    assert counter["job_count"] == 1
    assert counter["accounted_points"] == FULL_PLAN_POINTS


def test_same_key_with_different_request_is_conflict(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    assert first_ledger.reserve(_request("same-key", "job-1"), LIMITS).allowed
    changed = BudgetRequest(
        idempotency_key="same-key",
        job_id="job-2",
        requester_id="requester-a",
        plan="professional_research",
        capabilities=FULL_PLAN,
        request_fingerprint=operation_fingerprint("different-query"),
    )

    decision = second_ledger.reserve(changed, LIMITS)
    assert decision.allowed is False
    assert decision.reason == "idempotency_conflict"


def test_same_key_with_different_plan_is_conflict(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    assert first_ledger.reserve(_request("same-key", "job-1"), LIMITS).allowed
    changed = BudgetRequest(
        idempotency_key="same-key",
        job_id="job-2",
        requester_id="requester-a",
        plan="identity_resolution",
        capabilities=FULL_PLAN,
        request_fingerprint=operation_fingerprint("query-a"),
    )

    decision = second_ledger.reserve(changed, LIMITS)
    assert decision.allowed is False
    assert decision.reason == "idempotency_conflict"


def test_requester_limit_is_shared_across_instances(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    limits = BudgetLimits(
        max_points_per_job=220,
        max_calls_per_job=11,
        daily_point_budget=FULL_PLAN_POINTS * 4,
        daily_job_limit=4,
        requester_daily_limit=1,
    )
    assert first_ledger.reserve(_request("one", "job-1"), limits).allowed

    blocked = second_ledger.reserve(_request("two", "job-2"), limits)
    assert blocked.allowed is False
    assert blocked.reason == "requester_daily_limit"


def test_settlement_is_persistent_immutable_and_releases_difference(
    ledger_pair,
) -> None:
    first_ledger, second_ledger = ledger_pair
    reservation = first_ledger.reserve(_request("settle", "job-1"), LIMITS)
    assert reservation.reservation_id

    first_ledger.settle(reservation.reservation_id, actual_points=20, actual_calls=1)
    second_ledger.settle(reservation.reservation_id, actual_points=20, actual_calls=1)
    with pytest.raises(ValueError, match="已按不同用量结算"):
        second_ledger.settle(
            reservation.reservation_id, actual_points=0, actual_calls=0
        )

    counter = first_ledger._usage_counters.find_one({"_id": "deployment:2026-08-09"})
    assert counter["accounted_points"] == 20
    assert counter["accounted_calls"] == 1


def test_settlement_rejects_unknown_and_overflow(ledger_pair) -> None:
    first_ledger, _ = ledger_pair
    with pytest.raises(KeyError, match="未知的预算预留"):
        first_ledger.settle("missing", actual_points=0, actual_calls=0)

    reservation = first_ledger.reserve(_request("overflow", "job-1"), LIMITS)
    assert reservation.reservation_id
    with pytest.raises(ValueError, match="积分超过预留"):
        first_ledger.settle(
            reservation.reservation_id,
            actual_points=FULL_PLAN_POINTS + 1,
            actual_calls=len(FULL_PLAN),
        )


def test_terminal_result_and_failure_replay_across_instances(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    completed = first_ledger.reserve(_request("completed", "job-1"), LIMITS)
    assert completed.reservation_id
    first_ledger.complete_operation(
        completed.reservation_id, {"kind": "not_found", "items": []}
    )

    replay = second_ledger.reserve(_request("completed", "job-2"), LIMITS)
    assert replay.operation_status == OperationStatus.COMPLETED
    assert replay.result == {"kind": "not_found", "items": []}

    failed = first_ledger.reserve(_request("failed", "job-3", "requester-b"), LIMITS)
    assert failed.reservation_id
    first_ledger.fail_operation(failed.reservation_id, "provider_unavailable")
    failed_replay = second_ledger.reserve(
        _request("failed", "job-4", "requester-b"), LIMITS
    )
    assert failed_replay.operation_status == OperationStatus.FAILED
    assert failed_replay.reason == "provider_unavailable"


def test_terminal_transitions_are_immutable_but_same_retry_is_idempotent(
    ledger_pair,
) -> None:
    first_ledger, second_ledger = ledger_pair
    completed = first_ledger.reserve(_request("completed", "job-1"), LIMITS)
    assert completed.reservation_id
    result = {"kind": "not_found", "items": []}
    first_ledger.complete_operation(completed.reservation_id, result)
    second_ledger.complete_operation(completed.reservation_id, result)
    with pytest.raises(ValueError, match="不同结果完成"):
        second_ledger.complete_operation(completed.reservation_id, {"kind": "blocked"})
    with pytest.raises(ValueError, match="不在执行中"):
        second_ledger.fail_operation(completed.reservation_id, "provider_unavailable")


def test_finalize_atomically_persists_terminal_and_actual_usage(
    ledger_pair,
) -> None:
    first_ledger, second_ledger = ledger_pair
    reservation = first_ledger.reserve(_request("finalize", "job-1"), LIMITS)
    assert reservation.reservation_id
    result = {"kind": "not_found", "items": []}

    first_ledger.finalize_operation(
        reservation.reservation_id,
        result=result,
        safe_reason=None,
        actual_points=20,
        actual_calls=1,
    )
    second_ledger.finalize_operation(
        reservation.reservation_id,
        result=result,
        safe_reason=None,
        actual_points=20,
        actual_calls=1,
    )

    stored = first_ledger._operations.find_one({"_id": reservation.reservation_id})
    assert stored["operation_status"] == OperationStatus.COMPLETED.value
    assert stored["settled"] is True
    assert stored["actual_points"] == 20
    assert stored["expires_at"] == NOW + timedelta(hours=48)
    counter = first_ledger._usage_counters.find_one({"_id": "deployment:2026-08-09"})
    assert counter["accounted_points"] == 20
    assert counter["accounted_calls"] == 1


def test_critical_collections_use_majority_write_concern(ledger_pair) -> None:
    first_ledger, _ = ledger_pair

    assert first_ledger._operations.write_concern.document["w"] == "majority"
    assert first_ledger._usage_counters.write_concern.document["w"] == "majority"
    assert first_ledger._consumed_tokens.write_concern.document["w"] == "majority"


def test_only_requester_counter_expires_after_48_hours(ledger_pair) -> None:
    first_ledger, _ = ledger_pair
    assert first_ledger.reserve(_request("retention", "job-1"), LIMITS).allowed

    deployment = first_ledger._usage_counters.find_one({"_id": "deployment:2026-08-09"})
    requester = first_ledger._usage_counters.find_one(
        {"_id": "requester:2026-08-09:requester-a"}
    )
    assert "expires_at" not in deployment
    assert requester["expires_at"] == NOW + timedelta(hours=48)


def test_token_is_consumed_once_across_instances(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    expires_at = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())

    assert first_ledger.consume_token("token-id", expires_at) is True
    assert second_ledger.consume_token("token-id", expires_at) is False


def test_reserve_with_token_is_atomic_and_replayable_across_instances(
    ledger_pair,
) -> None:
    first_ledger, second_ledger = ledger_pair
    token_id = "d" * 32
    expires_at = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())

    first = first_ledger.reserve_with_token(
        _request("professional-token", "job-1"),
        LIMITS,
        token_id=token_id,
        token_expires_at=expires_at,
    )
    replay = second_ledger.reserve_with_token(
        _request("professional-token", "job-2"),
        LIMITS,
        token_id=token_id,
        token_expires_at=expires_at,
    )

    assert first.allowed is True
    assert replay.allowed is True
    assert replay.replayed is True
    assert replay.reservation_id == first.reservation_id
    assert first_ledger._consumed_tokens.count_documents({}) == 1


def test_same_token_cannot_reserve_two_jobs_across_instances(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    token_id = "e" * 32
    expires_at = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())
    barrier = threading.Barrier(2)

    def reserve(index: int):
        barrier.wait()
        ledger = first_ledger if index == 0 else second_ledger
        return ledger.reserve_with_token(
            _request(f"token-key-{index}", f"job-{index}"),
            LIMITS,
            token_id=token_id,
            token_expires_at=expires_at,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(reserve, range(2)))

    assert sum(decision.allowed for decision in decisions) == 1
    assert {decision.reason for decision in decisions if not decision.allowed} == {
        "token_already_used"
    }
    counter = first_ledger._usage_counters.find_one({"_id": "deployment:2026-08-09"})
    assert counter["job_count"] == 1
    assert counter["accounted_points"] == FULL_PLAN_POINTS
    assert first_ledger._consumed_tokens.count_documents({}) == 1


def test_operation_claim_is_atomic_across_instances(ledger_pair) -> None:
    first_ledger, second_ledger = ledger_pair
    reservation = first_ledger.reserve(_request("claim", "job-1"), LIMITS)
    assert reservation.reservation_id
    barrier = threading.Barrier(2)

    def claim(ledger: MongoUsageLedger) -> bool:
        barrier.wait()
        return ledger.claim_operation(reservation.reservation_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, ledger_pair))

    assert sum(outcomes) == 1
    stored = first_ledger._operations.find_one({"_id": reservation.reservation_id})
    assert stored["execution_claimed"] is True
    assert stored["execution_claimed_at"] == NOW


def test_raw_idempotency_key_is_not_persisted(ledger_pair) -> None:
    first_ledger, _ = ledger_pair
    secret_key = "raw-client-idempotency-key"
    assert first_ledger.reserve(_request(secret_key, "job-1"), LIMITS).allowed

    stored = first_ledger._operations.find_one({})
    assert secret_key not in repr(stored)
    assert len(stored["idempotency_key_hash"]) == 64


def test_default_constructor_fails_closed_without_transaction_support() -> None:
    database = mongomock.MongoClient()["standalone"]

    with pytest.raises(MongoLedgerUnavailable, match="事务"):
        MongoUsageLedger(database)
