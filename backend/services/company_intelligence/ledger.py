"""预算、幂等和一次性 Token 的账本接口。"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Literal, Protocol

from .config import DATA_CAPABILITIES, TOOL_COST_CATALOG


def utc_day(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).date().isoformat()


def operation_fingerprint(value: str) -> str:
    """把规范化请求内容压成账本可比较、不可逆的摘要。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class OperationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class BudgetLimits:
    """每次可计费预留计为一次任务；主体识别与专业采集分别计数。"""

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
    request_fingerprint: str


@dataclass(frozen=True)
class ReservationDecision:
    allowed: bool
    reservation_id: str | None = None
    reason: str | None = None
    replayed: bool = False
    job_id: str | None = None
    operation_status: OperationStatus | None = None
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReservationQuote:
    """由服务端固定计划计算出的预算预留，不接受客户端提供价格或调用数。"""

    plan_fingerprint: tuple[str, ...]
    points: int
    calls: int


def quote_reservation(
    request: BudgetRequest, limits: BudgetLimits
) -> ReservationQuote | ReservationDecision:
    """校验固定调用计划并计算最坏情况用量；拒绝结果可直接返回给调用方。"""
    if not re.fullmatch(r"[0-9a-f]{64}", request.request_fingerprint):
        return ReservationDecision(False, reason="invalid_request_fingerprint")

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

    quote = ReservationQuote(
        plan_fingerprint=tuple(sorted(request.capabilities)),
        calls=len(request.capabilities),
        points=sum(TOOL_COST_CATALOG[name] for name in request.capabilities),
    )
    if quote.points > limits.max_points_per_job:
        return ReservationDecision(False, reason="job_point_limit")
    if quote.calls > limits.max_calls_per_job:
        return ReservationDecision(False, reason="job_call_limit")
    return quote


class UsageLedger(Protocol):
    @property
    def persistent(self) -> bool: ...

    def reserve(
        self, request: BudgetRequest, limits: BudgetLimits
    ) -> ReservationDecision:
        """原子执行幂等检查、固定计划校验和预算预留。"""
        ...

    def reserve_with_token(
        self,
        request: BudgetRequest,
        limits: BudgetLimits,
        *,
        token_id: str,
        token_expires_at: int,
    ) -> ReservationDecision:
        """重放优先；新操作原子完成一次性 Token 消费和预算预留。"""
        ...

    def claim_operation(self, reservation_id: str) -> bool:
        """让一个执行者原子领取进行中的操作；重复领取返回 False。"""
        ...

    def settle(
        self, reservation_id: str, *, actual_points: int, actual_calls: int
    ) -> None:
        """以不超过原预留的实际用量不可变结算，并支持同值重放。"""
        ...

    def consume_token(self, token_id: str, expires_at: int) -> bool:
        """原子检查并标记一个尚未过期的一次性 Token。"""
        ...

    def complete_operation(self, reservation_id: str, result: dict[str, Any]) -> None:
        """把进行中操作转为成功终态；完全相同的终态重放必须幂等。"""
        ...

    def fail_operation(self, reservation_id: str, safe_reason: str) -> None:
        """把进行中操作转为失败终态；只接受稳定原因码和同值重放。"""
        ...

    def finalize_operation(
        self,
        reservation_id: str,
        *,
        result: dict[str, Any] | None,
        safe_reason: str | None,
        actual_points: int,
        actual_calls: int,
    ) -> None:
        """原子写入成功或失败终态及实际用量，避免终态与结算分离。"""
        ...


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
        return self._reserve(request, limits)

    def reserve_with_token(
        self,
        request: BudgetRequest,
        limits: BudgetLimits,
        *,
        token_id: str,
        token_expires_at: int,
    ) -> ReservationDecision:
        """在同一把锁内消费 Token 并创建预算预留，避免中间崩溃窗口。"""
        return self._reserve(
            request,
            limits,
            token_id=token_id,
            token_expires_at=token_expires_at,
        )

    def _reserve(
        self,
        request: BudgetRequest,
        limits: BudgetLimits,
        *,
        token_id: str | None = None,
        token_expires_at: int | None = None,
    ) -> ReservationDecision:
        """在同一把锁内校验幂等请求、固定调用计划和预算，并完成预留。"""
        with self._lock:
            plan_fingerprint = tuple(sorted(request.capabilities))
            idempotency_scope = (request.requester_id, request.idempotency_key)
            if existing_id := self._idempotency.get(idempotency_scope):
                existing = self._reservations[existing_id]
                if (
                    tuple(existing["plan_fingerprint"]) != plan_fingerprint
                    or existing["request_fingerprint"] != request.request_fingerprint
                ):
                    return ReservationDecision(False, reason="idempotency_conflict")
                operation_status = OperationStatus(str(existing["operation_status"]))
                return ReservationDecision(
                    allowed=True,
                    reservation_id=existing_id,
                    replayed=True,
                    job_id=str(existing["job_id"]),
                    operation_status=operation_status,
                    result=copy.deepcopy(existing["operation_result"]),
                    reason=(
                        str(existing["operation_reason"])
                        if operation_status == OperationStatus.FAILED
                        else None
                    ),
                )

            quote = quote_reservation(request, limits)
            if isinstance(quote, ReservationDecision):
                return quote

            day = utc_day(self._now_factory())

            day_items = [
                item
                for item in self._reservations.values()
                if item["day"] == day
            ]
            if len(day_items) >= limits.daily_job_limit:
                return ReservationDecision(False, reason="daily_job_limit")
            if (
                sum(int(item["reserved_points"]) for item in day_items)
                + quote.points
                > limits.daily_point_budget
            ):
                return ReservationDecision(False, reason="daily_point_budget")
            requester_jobs = sum(
                1 for item in day_items if item["requester_id"] == request.requester_id
            )
            if requester_jobs >= limits.requester_daily_limit:
                return ReservationDecision(False, reason="requester_daily_limit")

            if token_id is not None:
                if (
                    token_expires_at is None
                    or not re.fullmatch(r"[0-9a-f]{32}", token_id)
                ):
                    return ReservationDecision(False, reason="invalid_token")
                current_timestamp = int(self._now_factory().timestamp())
                self._consumed_tokens = {
                    key: exp
                    for key, exp in self._consumed_tokens.items()
                    if exp > current_timestamp
                }
                if (
                    token_expires_at <= current_timestamp
                    or token_id in self._consumed_tokens
                ):
                    return ReservationDecision(False, reason="token_already_used")
                self._consumed_tokens[token_id] = token_expires_at

            reservation_id = uuid.uuid4().hex
            self._reservations[reservation_id] = {
                "job_id": request.job_id,
                "requester_id": request.requester_id,
                "day": day,
                "plan_fingerprint": quote.plan_fingerprint,
                "request_fingerprint": request.request_fingerprint,
                "reserved_points": quote.points,
                "reserved_calls": quote.calls,
                "original_reserved_points": quote.points,
                "original_reserved_calls": quote.calls,
                "actual_points": None,
                "actual_calls": None,
                "settled": False,
                "operation_status": OperationStatus.IN_PROGRESS.value,
                "operation_result": None,
                "operation_reason": None,
                "execution_claimed": False,
            }
            self._idempotency[idempotency_scope] = reservation_id
            return ReservationDecision(
                True,
                reservation_id=reservation_id,
                job_id=request.job_id,
                operation_status=OperationStatus.IN_PROGRESS,
            )

    def claim_operation(self, reservation_id: str) -> bool:
        """在锁内把未领取的进行中操作置为已领取，禁止重复付费执行。"""
        with self._lock:
            item = self._reservations.get(reservation_id)
            if item is None:
                raise KeyError("unknown reservation")
            if (
                item["operation_status"] != OperationStatus.IN_PROGRESS.value
                or bool(item["execution_claimed"])
            ):
                return False
            item["execution_claimed"] = True
            return True

    def settle(
        self, reservation_id: str, *, actual_points: int, actual_calls: int
    ) -> None:
        """以实际用量不可变结算；同值重放幂等，且实际用量不得超过预留。"""
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
        """原子记录一次性 Token；过期或已经消费时返回 False。"""
        now = int(datetime.now(timezone.utc).timestamp())
        with self._lock:
            self._consumed_tokens = {
                key: exp for key, exp in self._consumed_tokens.items() if exp >= now
            }
            if expires_at < now or token_id in self._consumed_tokens:
                return False
            self._consumed_tokens[token_id] = expires_at
            return True

    def complete_operation(
        self, reservation_id: str, result: dict[str, Any]
    ) -> None:
        """把进行中操作置为成功终态；只允许完全相同的结果幂等重放。"""
        # JSON round-trip both verifies persistence compatibility and breaks aliases.
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("operation result exceeds size limit")
        safe_result = json.loads(encoded)
        with self._lock:
            item = self._reservations.get(reservation_id)
            if item is None:
                raise KeyError("unknown reservation")
            status = OperationStatus(str(item["operation_status"]))
            if status == OperationStatus.COMPLETED:
                if item["operation_result"] == safe_result:
                    return
                raise ValueError("operation already completed with different result")
            if status != OperationStatus.IN_PROGRESS:
                raise ValueError("operation is not in progress")
            item["operation_result"] = safe_result
            item["operation_reason"] = None
            item["operation_status"] = OperationStatus.COMPLETED.value

    def fail_operation(self, reservation_id: str, safe_reason: str) -> None:
        """把进行中操作置为失败终态，并且只持久化稳定、安全的原因码。"""
        if not re.fullmatch(r"[a-z0-9_]{1,80}", safe_reason):
            raise ValueError("safe_reason must be a stable reason code")
        with self._lock:
            item = self._reservations.get(reservation_id)
            if item is None:
                raise KeyError("unknown reservation")
            status = OperationStatus(str(item["operation_status"]))
            if status == OperationStatus.FAILED:
                if item["operation_reason"] == safe_reason:
                    return
                raise ValueError("operation already failed with different reason")
            if status != OperationStatus.IN_PROGRESS:
                raise ValueError("operation is not in progress")
            item["operation_result"] = None
            item["operation_reason"] = safe_reason
            item["operation_status"] = OperationStatus.FAILED.value

    def finalize_operation(
        self,
        reservation_id: str,
        *,
        result: dict[str, Any] | None,
        safe_reason: str | None,
        actual_points: int,
        actual_calls: int,
    ) -> None:
        """在同一把锁内完成终态转换与不可变结算。"""
        if (result is None) == (safe_reason is None):
            raise ValueError("result 和 safe_reason 必须且只能提供一个")
        if safe_reason is not None and not re.fullmatch(
            r"[a-z0-9_]{1,80}", safe_reason
        ):
            raise ValueError("safe_reason must be a stable reason code")
        safe_result: dict[str, Any] | None = None
        if result is not None:
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 1_000_000:
                raise ValueError("operation result exceeds size limit")
            safe_result = json.loads(encoded)
        if actual_points < 0 or actual_calls < 0:
            raise ValueError("actual usage must be non-negative")

        desired_status = (
            OperationStatus.COMPLETED if result is not None else OperationStatus.FAILED
        )
        with self._lock:
            item = self._reservations.get(reservation_id)
            if item is None:
                raise KeyError("unknown reservation")
            original_points = int(item["original_reserved_points"])
            original_calls = int(item["original_reserved_calls"])
            if actual_points > original_points:
                raise ValueError("actual points exceed reservation")
            if actual_calls > original_calls:
                raise ValueError("actual calls exceed reservation")

            status = OperationStatus(str(item["operation_status"]))
            if status != OperationStatus.IN_PROGRESS:
                same_terminal = (
                    status == desired_status
                    and item["operation_result"] == safe_result
                    and item["operation_reason"] == safe_reason
                )
                if not same_terminal:
                    raise ValueError("operation already finalized differently")
            if bool(item["settled"]):
                if (
                    int(item["actual_points"]) == actual_points
                    and int(item["actual_calls"]) == actual_calls
                ):
                    if status == OperationStatus.IN_PROGRESS:
                        item["operation_status"] = desired_status.value
                        item["operation_result"] = safe_result
                        item["operation_reason"] = safe_reason
                    return
                raise ValueError("reservation already settled with different usage")

            item["operation_status"] = desired_status.value
            item["operation_result"] = safe_result
            item["operation_reason"] = safe_reason
            item["reserved_points"] = actual_points
            item["reserved_calls"] = actual_calls
            item["actual_points"] = actual_points
            item["actual_calls"] = actual_calls
            item["settled"] = True
