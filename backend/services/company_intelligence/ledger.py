"""预算、幂等和一次性 Token 的账本接口。"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol

from .config import DATA_CAPABILITIES, TOOL_COST_CATALOG


def utc_day(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class BudgetLimits:
    max_points_per_job: int
    max_calls_per_job: int
    daily_point_budget: int
    daily_job_limit: int
    requester_daily_limit: int


@dataclass(frozen=True)
class BudgetRequest:
    idempotency_key: str
    job_id: str
    requester_id: str
    plan: Literal["identity_resolution", "professional_research"]
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ReservationDecision:
    allowed: bool
    reservation_id: str | None = None
    reason: str | None = None
    replayed: bool = False
    job_id: str | None = None


class UsageLedger(Protocol):
    @property
    def persistent(self) -> bool: ...

    def reserve(
        self, request: BudgetRequest, limits: BudgetLimits
    ) -> ReservationDecision: ...

    def settle(self, reservation_id: str, *, actual_points: int, actual_calls: int) -> None: ...

    def consume_token(self, token_id: str, expires_at: int) -> bool: ...


class InMemoryUsageLedger:
    """仅供本地开发和测试使用；进程重启会清空所有限制。"""

    persistent = False

    def __init__(self, now_factory: Callable[[], datetime] | None = None) -> None:
        self._lock = threading.Lock()
        self._reservations: dict[str, dict[str, object]] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._consumed_tokens: dict[str, int] = {}
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    def reserve(
        self, request: BudgetRequest, limits: BudgetLimits
    ) -> ReservationDecision:
        with self._lock:
            plan_fingerprint = tuple(sorted(request.capabilities))
            idempotency_scope = (request.requester_id, request.idempotency_key)
            if existing_id := self._idempotency.get(idempotency_scope):
                existing = self._reservations[existing_id]
                if tuple(existing["plan_fingerprint"]) != plan_fingerprint:
                    return ReservationDecision(False, reason="idempotency_conflict")
                return ReservationDecision(
                    allowed=True,
                    reservation_id=existing_id,
                    replayed=True,
                    job_id=str(existing["job_id"]),
                )

            expected_plan = (
                ("identity.resolve",)
                if request.plan == "identity_resolution"
                else tuple(DATA_CAPABILITIES)
            )
            if (
                tuple(request.capabilities) != expected_plan
                or len(request.capabilities) != len(set(request.capabilities))
                or any(name not in TOOL_COST_CATALOG for name in request.capabilities)
            ):
                return ReservationDecision(False, reason="invalid_call_plan")
            calls = len(request.capabilities)
            points = sum(TOOL_COST_CATALOG[name] for name in request.capabilities)

            if points > limits.max_points_per_job:
                return ReservationDecision(False, reason="job_point_limit")
            if calls > limits.max_calls_per_job:
                return ReservationDecision(False, reason="job_call_limit")

            day = utc_day(self._now_factory())

            day_items = [
                item
                for item in self._reservations.values()
                if item["day"] == day
            ]
            if len(day_items) >= limits.daily_job_limit:
                return ReservationDecision(False, reason="daily_job_limit")
            if sum(int(item["reserved_points"]) for item in day_items) + points > limits.daily_point_budget:
                return ReservationDecision(False, reason="daily_point_budget")
            requester_jobs = sum(
                1 for item in day_items if item["requester_id"] == request.requester_id
            )
            if requester_jobs >= limits.requester_daily_limit:
                return ReservationDecision(False, reason="requester_daily_limit")

            reservation_id = uuid.uuid4().hex
            self._reservations[reservation_id] = {
                "job_id": request.job_id,
                "requester_id": request.requester_id,
                "day": day,
                "plan_fingerprint": plan_fingerprint,
                "reserved_points": points,
                "reserved_calls": calls,
                "original_reserved_points": points,
                "original_reserved_calls": calls,
                "actual_points": None,
                "actual_calls": None,
                "settled": False,
            }
            self._idempotency[idempotency_scope] = reservation_id
            return ReservationDecision(
                True, reservation_id=reservation_id, job_id=request.job_id
            )

    def settle(
        self, reservation_id: str, *, actual_points: int, actual_calls: int
    ) -> None:
        with self._lock:
            item = self._reservations.get(reservation_id)
            if item is None:
                raise KeyError("unknown reservation")
            if actual_points < 0 or actual_calls < 0:
                raise ValueError("actual usage must be non-negative")
            if actual_points > int(item["original_reserved_points"]):
                raise ValueError("actual points exceed reservation")
            if actual_calls > int(item["original_reserved_calls"]):
                raise ValueError("actual calls exceed reservation")
            if bool(item["settled"]):
                if (
                    int(item["actual_points"]) == actual_points
                    and int(item["actual_calls"]) == actual_calls
                ):
                    return
                raise ValueError("reservation already settled with different usage")
            item["reserved_points"] = actual_points
            item["reserved_calls"] = actual_calls
            item["actual_points"] = actual_points
            item["actual_calls"] = actual_calls
            item["settled"] = True

    def consume_token(self, token_id: str, expires_at: int) -> bool:
        now = int(datetime.now(timezone.utc).timestamp())
        with self._lock:
            self._consumed_tokens = {
                key: exp for key, exp in self._consumed_tokens.items() if exp >= now
            }
            if expires_at < now or token_id in self._consumed_tokens:
                return False
            self._consumed_tokens[token_id] = expires_at
            return True
