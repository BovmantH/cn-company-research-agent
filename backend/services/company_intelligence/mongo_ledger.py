"""基于 MongoDB 事务的生产级用量账本。"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from pymongo import ASCENDING, ReadPreference
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from .ledger import (
    BudgetLimits,
    BudgetRequest,
    OperationStatus,
    ReservationDecision,
    quote_reservation,
    utc_day,
)

T = TypeVar("T")
TransactionRunner = Callable[[Callable[[Any], T]], T]
MAJORITY_WRITE_CONCERN = WriteConcern("majority")
FINALIZED_OPERATION_RETENTION = timedelta(hours=48)


class MongoLedgerUnavailable(RuntimeError):
    """MongoDB 不满足持久账本所需的连接、索引或事务条件。"""


class MongoUsageLedger:
    """用多文档事务持久化预算、幂等操作和一次性 Token。"""

    persistent = True

    def __init__(
        self,
        database: Database[dict[str, Any]],
        *,
        now_factory: Callable[[], datetime] | None = None,
        transaction_runner: TransactionRunner[Any] | None = None,
    ) -> None:
        self._database = database
        self._operations = database.get_collection(
            "company_intelligence_operations",
            write_concern=MAJORITY_WRITE_CONCERN,
        )
        self._usage_counters = database.get_collection(
            "company_intelligence_usage_counters",
            write_concern=MAJORITY_WRITE_CONCERN,
        )
        self._consumed_tokens = database.get_collection(
            "company_intelligence_consumed_tokens",
            write_concern=MAJORITY_WRITE_CONCERN,
        )
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._pass_session = transaction_runner is None
        self._transaction_runner = transaction_runner or self._run_transaction

        try:
            self._create_indexes()
            if transaction_runner is None:
                self._verify_transaction_support()
        except Exception as exc:
            raise MongoLedgerUnavailable(
                "MongoDB 持久账本需要可用索引和副本集或分片集群事务"
            ) from exc

    def _create_indexes(self) -> None:
        """创建幂等唯一索引与清理索引；TTL 不参与正确性判定。"""
        self._operations.create_index(
            [("requester_id", ASCENDING), ("idempotency_key_hash", ASCENDING)],
            unique=True,
            name="requester_idempotency_unique",
        )
        self._operations.create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="finalized_operation_expiry",
        )
        self._usage_counters.create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="usage_counter_expiry",
        )
        self._consumed_tokens.create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="consumed_token_expiry",
        )

    def _run_transaction(self, callback: Callable[[Any], T]) -> T:
        """让 PyMongo 负责瞬时事务错误的回滚与 callback 重试。"""
        with self._database.client.start_session() as session:
            return session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
                read_preference=ReadPreference.PRIMARY,
            )

    def _verify_transaction_support(self) -> None:
        """执行只读事务探针，拒绝不支持事务的 standalone MongoDB。"""
        self._run_transaction(
            lambda session: self._usage_counters.find_one(
                {"_id": "__transaction_probe__"},
                **self._session_kwargs(session),
            )
        )

    def _session_kwargs(self, session: Any) -> dict[str, Any]:
        return {"session": session} if self._pass_session else {}

    def _now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now_factory 必须返回带时区的时间")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _idempotency_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _counter_expiry(now: datetime) -> datetime:
        return now + timedelta(hours=48)

    def _existing_operation(
        self, request: BudgetRequest, *, session: Any = None
    ) -> dict[str, Any] | None:
        return self._operations.find_one(
            {
                "requester_id": request.requester_id,
                "idempotency_key_hash": self._idempotency_hash(request.idempotency_key),
            },
            **self._session_kwargs(session),
        )

    @staticmethod
    def _decision_from_existing(
        existing: dict[str, Any], request: BudgetRequest
    ) -> ReservationDecision:
        if (
            existing["plan"] != request.plan
            or tuple(existing["plan_fingerprint"])
            != tuple(sorted(request.capabilities))
            or existing["request_fingerprint"] != request.request_fingerprint
        ):
            return ReservationDecision(False, reason="idempotency_conflict")

        status = OperationStatus(existing["operation_status"])
        result_json = existing.get("operation_result_json")
        result = json.loads(result_json) if result_json is not None else None
        return ReservationDecision(
            allowed=True,
            reservation_id=str(existing["_id"]),
            replayed=True,
            job_id=str(existing["job_id"]),
            operation_status=status,
            result=copy.deepcopy(result),
            reason=(
                str(existing["operation_reason"])
                if status == OperationStatus.FAILED
                else None
            ),
        )

    def _ensure_counter(self, counter_id: str, document: dict[str, Any]) -> None:
        try:
            self._usage_counters.update_one(
                {"_id": counter_id}, {"$setOnInsert": document}, upsert=True
            )
        except DuplicateKeyError:
            # 两个进程首次访问同一日期时，唯一 _id 已保证其中一个初始化成功。
            pass

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
        """在同一 Mongo 事务中消费 Token 并预留预算。"""
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
        """在事务中串行化日计数，并原子完成幂等检查与预算预留。"""
        quote = quote_reservation(request, limits)
        if isinstance(quote, ReservationDecision):
            existing = self._existing_operation(request)
            return (
                self._decision_from_existing(existing, request)
                if existing is not None
                else quote
            )

        now = self._now()
        if token_id is not None and (
            token_expires_at is None or not re.fullmatch(r"[0-9a-f]{32}", token_id)
        ):
            existing = self._existing_operation(request)
            return (
                self._decision_from_existing(existing, request)
                if existing is not None
                else ReservationDecision(False, reason="invalid_token")
            )
        if token_expires_at is not None and token_expires_at <= int(now.timestamp()):
            existing = self._existing_operation(request)
            return (
                self._decision_from_existing(existing, request)
                if existing is not None
                else ReservationDecision(False, reason="token_already_used")
            )
        day = utc_day(now)
        expires_at = self._counter_expiry(now)
        deployment_counter_id = f"deployment:{day}"
        requester_counter_id = f"requester:{day}:{request.requester_id}"
        self._ensure_counter(
            deployment_counter_id,
            {
                "scope": "deployment",
                "day": day,
                "job_count": 0,
                "accounted_points": 0,
                "accounted_calls": 0,
                "updated_at": now,
            },
        )
        self._ensure_counter(
            requester_counter_id,
            {
                "scope": "requester",
                "day": day,
                "requester_id": request.requester_id,
                "job_count": 0,
                "updated_at": now,
                "expires_at": expires_at,
            },
        )
        reservation_id = uuid.uuid4().hex

        def reserve_in_transaction(session: Any) -> ReservationDecision:
            session_kwargs = self._session_kwargs(session)
            existing = self._existing_operation(request, session=session)
            if existing is not None:
                return self._decision_from_existing(existing, request)

            deployment = self._usage_counters.find_one(
                {"_id": deployment_counter_id}, **session_kwargs
            )
            requester = self._usage_counters.find_one(
                {"_id": requester_counter_id}, **session_kwargs
            )
            if deployment is None or requester is None:
                raise MongoLedgerUnavailable("MongoDB 用量计数器初始化失败")
            if int(deployment["job_count"]) >= limits.daily_job_limit:
                return ReservationDecision(False, reason="daily_job_limit")
            if (
                int(deployment["accounted_points"]) + quote.points
                > limits.daily_point_budget
            ):
                return ReservationDecision(False, reason="daily_point_budget")
            if int(requester["job_count"]) >= limits.requester_daily_limit:
                return ReservationDecision(False, reason="requester_daily_limit")

            if token_id is not None and token_expires_at is not None:
                self._consumed_tokens.insert_one(
                    {
                        "_id": token_id,
                        "schema_version": 1,
                        "consumed_at": now,
                        "expires_at": datetime.fromtimestamp(
                            token_expires_at, tz=timezone.utc
                        ),
                    },
                    **session_kwargs,
                )

            self._operations.insert_one(
                {
                    "_id": reservation_id,
                    "schema_version": 1,
                    "requester_id": request.requester_id,
                    "idempotency_key_hash": self._idempotency_hash(
                        request.idempotency_key
                    ),
                    "job_id": request.job_id,
                    "day": day,
                    "plan": request.plan,
                    "capabilities": list(request.capabilities),
                    "plan_fingerprint": list(quote.plan_fingerprint),
                    "request_fingerprint": request.request_fingerprint,
                    "original_reserved_points": quote.points,
                    "original_reserved_calls": quote.calls,
                    "accounted_points": quote.points,
                    "accounted_calls": quote.calls,
                    "settled": False,
                    "actual_points": None,
                    "actual_calls": None,
                    "settled_at": None,
                    "operation_status": OperationStatus.IN_PROGRESS.value,
                    "operation_result_json": None,
                    "operation_reason": None,
                    "execution_claimed": False,
                    "execution_claimed_at": None,
                    "created_at": now,
                    "finalized_at": None,
                    "expires_at": None,
                },
                **session_kwargs,
            )
            deployment_update = self._usage_counters.update_one(
                {"_id": deployment_counter_id},
                {
                    "$inc": {
                        "job_count": 1,
                        "accounted_points": quote.points,
                        "accounted_calls": quote.calls,
                    },
                    "$set": {"updated_at": now},
                },
                **session_kwargs,
            )
            requester_update = self._usage_counters.update_one(
                {"_id": requester_counter_id},
                {"$inc": {"job_count": 1}, "$set": {"updated_at": now}},
                **session_kwargs,
            )
            if (
                deployment_update.matched_count != 1
                or requester_update.matched_count != 1
            ):
                raise MongoLedgerUnavailable("MongoDB 用量计数器在预留期间丢失")
            return ReservationDecision(
                True,
                reservation_id=reservation_id,
                job_id=request.job_id,
                operation_status=OperationStatus.IN_PROGRESS,
            )

        try:
            return self._transaction_runner(reserve_in_transaction)
        except DuplicateKeyError:
            existing = self._existing_operation(request)
            if existing is not None:
                return self._decision_from_existing(existing, request)
            if (
                token_id is not None
                and self._consumed_tokens.find_one({"_id": token_id}) is not None
            ):
                return ReservationDecision(False, reason="token_already_used")
            raise

    def claim_operation(self, reservation_id: str) -> bool:
        """用条件单文档更新跨进程领取一次进行中的付费操作。"""
        updated = self._operations.update_one(
            {
                "_id": reservation_id,
                "operation_status": OperationStatus.IN_PROGRESS.value,
                "execution_claimed": False,
            },
            {
                "$set": {
                    "execution_claimed": True,
                    "execution_claimed_at": self._now(),
                }
            },
        )
        if updated.modified_count == 1:
            return True
        if self._operations.find_one({"_id": reservation_id}) is None:
            raise KeyError("unknown reservation")
        return False

    def settle(
        self, reservation_id: str, *, actual_points: int, actual_calls: int
    ) -> None:
        """事务化写入不可变实际用量，并释放部署日计数中的预留差额。"""
        if actual_points < 0 or actual_calls < 0:
            raise ValueError("actual usage must be non-negative")
        now = self._now()

        def settle_in_transaction(session: Any) -> None:
            session_kwargs = self._session_kwargs(session)
            item = self._operations.find_one({"_id": reservation_id}, **session_kwargs)
            if item is None:
                raise KeyError("unknown reservation")
            original_points = int(item["original_reserved_points"])
            original_calls = int(item["original_reserved_calls"])
            if actual_points > original_points:
                raise ValueError("actual points exceed reservation")
            if actual_calls > original_calls:
                raise ValueError("actual calls exceed reservation")
            if bool(item["settled"]):
                if (
                    int(item["actual_points"]) == actual_points
                    and int(item["actual_calls"]) == actual_calls
                ):
                    return
                raise ValueError("reservation already settled with different usage")

            operation_update: dict[str, Any] = {
                "accounted_points": actual_points,
                "accounted_calls": actual_calls,
                "actual_points": actual_points,
                "actual_calls": actual_calls,
                "settled": True,
                "settled_at": now,
            }
            if item["operation_status"] != OperationStatus.IN_PROGRESS.value:
                operation_update["expires_at"] = now + FINALIZED_OPERATION_RETENTION
            updated = self._operations.update_one(
                {"_id": reservation_id, "settled": False},
                {"$set": operation_update},
                **session_kwargs,
            )
            if updated.modified_count != 1:
                raise RuntimeError("reservation settlement lost atomic race")
            counter_update = self._usage_counters.update_one(
                {"_id": f"deployment:{item['day']}"},
                {
                    "$inc": {
                        "accounted_points": -(original_points - actual_points),
                        "accounted_calls": -(original_calls - actual_calls),
                    },
                    "$set": {"updated_at": now},
                },
                **session_kwargs,
            )
            if counter_update.matched_count != 1:
                raise MongoLedgerUnavailable("MongoDB 用量计数器在结算期间丢失")

        self._transaction_runner(settle_in_transaction)

    def consume_token(self, token_id: str, expires_at: int) -> bool:
        """通过唯一 `_id` 原子消费 Token；TTL 延迟不会允许二次消费。"""
        now = self._now()
        if expires_at < int(now.timestamp()):
            return False
        try:
            self._consumed_tokens.insert_one(
                {
                    "_id": token_id,
                    "schema_version": 1,
                    "consumed_at": now,
                    "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc),
                }
            )
        except DuplicateKeyError:
            return False
        return True

    @staticmethod
    def _encode_result(result: dict[str, Any]) -> str:
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("operation result exceeds size limit")
        return encoded

    def complete_operation(self, reservation_id: str, result: dict[str, Any]) -> None:
        """原子进入成功终态；同一规范 JSON 结果可安全重放。"""
        encoded = self._encode_result(result)
        now = self._now()
        updated = self._operations.update_one(
            {
                "_id": reservation_id,
                "operation_status": OperationStatus.IN_PROGRESS.value,
            },
            {
                "$set": {
                    "operation_status": OperationStatus.COMPLETED.value,
                    "operation_result_json": encoded,
                    "operation_reason": None,
                    "finalized_at": now,
                }
            },
        )
        if updated.modified_count == 1:
            return
        item = self._operations.find_one({"_id": reservation_id})
        if item is None:
            raise KeyError("unknown reservation")
        if (
            item["operation_status"] == OperationStatus.COMPLETED.value
            and item["operation_result_json"] == encoded
        ):
            return
        if item["operation_status"] == OperationStatus.COMPLETED.value:
            raise ValueError("operation already completed with different result")
        raise ValueError("operation is not in progress")

    def fail_operation(self, reservation_id: str, safe_reason: str) -> None:
        """原子进入失败终态，只允许稳定原因码与同值幂等重放。"""
        if not re.fullmatch(r"[a-z0-9_]{1,80}", safe_reason):
            raise ValueError("safe_reason must be a stable reason code")
        now = self._now()
        updated = self._operations.update_one(
            {
                "_id": reservation_id,
                "operation_status": OperationStatus.IN_PROGRESS.value,
            },
            {
                "$set": {
                    "operation_status": OperationStatus.FAILED.value,
                    "operation_result_json": None,
                    "operation_reason": safe_reason,
                    "finalized_at": now,
                }
            },
        )
        if updated.modified_count == 1:
            return
        item = self._operations.find_one({"_id": reservation_id})
        if item is None:
            raise KeyError("unknown reservation")
        if (
            item["operation_status"] == OperationStatus.FAILED.value
            and item["operation_reason"] == safe_reason
        ):
            return
        if item["operation_status"] == OperationStatus.FAILED.value:
            raise ValueError("operation already failed with different reason")
        raise ValueError("operation is not in progress")

    def finalize_operation(
        self,
        reservation_id: str,
        *,
        result: dict[str, Any] | None,
        safe_reason: str | None,
        actual_points: int,
        actual_calls: int,
    ) -> None:
        """在一个事务内写入终态、实际用量并释放预留差额。"""
        if (result is None) == (safe_reason is None):
            raise ValueError("result 和 safe_reason 必须且只能提供一个")
        if safe_reason is not None and not re.fullmatch(
            r"[a-z0-9_]{1,80}", safe_reason
        ):
            raise ValueError("safe_reason must be a stable reason code")
        if actual_points < 0 or actual_calls < 0:
            raise ValueError("actual usage must be non-negative")

        encoded = self._encode_result(result) if result is not None else None
        desired_status = (
            OperationStatus.COMPLETED if result is not None else OperationStatus.FAILED
        )
        now = self._now()

        def finalize_in_transaction(session: Any) -> None:
            session_kwargs = self._session_kwargs(session)
            item = self._operations.find_one({"_id": reservation_id}, **session_kwargs)
            if item is None:
                raise KeyError("unknown reservation")
            original_points = int(item["original_reserved_points"])
            original_calls = int(item["original_reserved_calls"])
            if actual_points > original_points:
                raise ValueError("actual points exceed reservation")
            if actual_calls > original_calls:
                raise ValueError("actual calls exceed reservation")

            status = OperationStatus(item["operation_status"])
            same_terminal = (
                status == desired_status
                and item["operation_result_json"] == encoded
                and item["operation_reason"] == safe_reason
            )
            if status != OperationStatus.IN_PROGRESS and not same_terminal:
                raise ValueError("operation already finalized differently")
            if bool(item["settled"]):
                if (
                    int(item["actual_points"]) != actual_points
                    or int(item["actual_calls"]) != actual_calls
                ):
                    raise ValueError("reservation already settled with different usage")
                if same_terminal:
                    return

            update_fields: dict[str, Any] = {
                "operation_status": desired_status.value,
                "operation_result_json": encoded,
                "operation_reason": safe_reason,
                "finalized_at": now,
                "expires_at": now + FINALIZED_OPERATION_RETENTION,
            }
            if not bool(item["settled"]):
                update_fields.update(
                    {
                        "accounted_points": actual_points,
                        "accounted_calls": actual_calls,
                        "actual_points": actual_points,
                        "actual_calls": actual_calls,
                        "settled": True,
                        "settled_at": now,
                    }
                )
            updated = self._operations.update_one(
                {
                    "_id": reservation_id,
                    "operation_status": item["operation_status"],
                    "settled": item["settled"],
                },
                {"$set": update_fields},
                **session_kwargs,
            )
            if updated.matched_count != 1:
                raise RuntimeError("operation finalization lost atomic race")
            if bool(item["settled"]):
                return

            counter_update = self._usage_counters.update_one(
                {"_id": f"deployment:{item['day']}"},
                {
                    "$inc": {
                        "accounted_points": -(original_points - actual_points),
                        "accounted_calls": -(original_calls - actual_calls),
                    },
                    "$set": {"updated_at": now},
                },
                **session_kwargs,
            )
            if counter_update.matched_count != 1:
                raise MongoLedgerUnavailable("MongoDB 用量计数器在终态结算期间丢失")

        self._transaction_runner(finalize_in_transaction)
