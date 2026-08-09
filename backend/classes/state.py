import json
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator, Sequence
from copy import deepcopy
from datetime import datetime
from threading import Lock
from typing import TypedDict, NotRequired, Required, Dict, List, Any, overload

#Define the input state
class InputState(TypedDict, total=False):
    company: Required[str]
    company_url: NotRequired[str]
    hq_location: NotRequired[str]
    industry: NotRequired[str]
    job_id: NotRequired[str]

class ResearchState(InputState):
    site_scrape: Dict[str, Any]
    messages: List[Any]
    financial_data: Dict[str, Any]
    news_data: Dict[str, Any]
    industry_data: Dict[str, Any]
    company_data: Dict[str, Any]
    curated_financial_data: Dict[str, Any]
    curated_news_data: Dict[str, Any]
    curated_industry_data: Dict[str, Any]
    curated_company_data: Dict[str, Any]
    financial_briefing: str
    news_briefing: str
    industry_briefing: str
    company_briefing: str
    references: List[str]
    briefings: Dict[str, Any]
    report: str

class JobEventLog(Sequence[dict[str, Any]]):
    """有界、只读的事件序列；只允许通过 append 增长并支持游标重放。"""

    def __init__(
        self,
        *,
        max_events: int = 5_000,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if max_events <= 0 or max_bytes <= 0:
            raise ValueError("event log limits must be positive")
        self._events: deque[tuple[dict[str, Any], int]] = deque()
        self._total_bytes = 0
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._next_event_id = 1
        self._lock = Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    @overload
    def __getitem__(self, index: int) -> dict[str, Any]: ...

    @overload
    def __getitem__(self, index: slice) -> list[dict[str, Any]]: ...

    def __getitem__(self, index):
        snapshot = self.snapshot()
        return snapshot[index]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.snapshot())

    def append(self, event: dict[str, Any]) -> None:
        """复制调用方事件并覆盖协议字段，避免外部篡改单调序列。"""
        if not isinstance(event, dict):
            raise TypeError("job event must be a dict")
        with self._lock:
            normalized = deepcopy(event)
            normalized["version"] = 1
            normalized["event_id"] = self._next_event_id
            encoded_size = len(
                json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if encoded_size > self._max_bytes:
                raise ValueError("single job event exceeds byte limit")
            self._next_event_id += 1
            self._events.append((normalized, encoded_size))
            self._total_bytes += encoded_size
            while len(self._events) > 1 and (
                len(self._events) > self._max_events
                or self._total_bytes > self._max_bytes
            ):
                _removed, removed_size = self._events.popleft()
                self._total_bytes -= removed_size

    def extend(self, events: Iterable[dict[str, Any]]) -> None:
        for event in events:
            self.append(event)

    def after(self, event_id: int) -> list[dict[str, Any]]:
        """返回指定 ID 之后的稳定副本，读取不会消费全局事件。"""
        with self._lock:
            return [
                deepcopy(event)
                for event, _size in self._events
                if int(event["event_id"]) > event_id
            ]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(event) for event, _size in self._events]

    def history_expired(self, event_id: int) -> bool:
        """判断游标是否早于当前有界保留窗口。"""
        with self._lock:
            if not self._events:
                return False
            first_event_id = int(self._events[0][0]["event_id"])
            return event_id < first_event_id - 1


JOB_TERMINAL_TTL_SECONDS = 60 * 60


def prune_expired_jobs(now_epoch: float | None = None) -> None:
    """在请求边界清理已终态且超过保留期的内存任务。"""
    current = time.time() if now_epoch is None else now_epoch
    expired = [
        job_id
        for job_id, state in list(job_status.items())
        if isinstance(state.get("expires_at_epoch"), (int, float))
        and float(state["expires_at_epoch"]) <= current
    ]
    for job_id in expired:
        job_status.pop(job_id, None)


# Global job status tracker - shared across application.py and backend nodes
job_status = defaultdict[str, dict[str, Any]](lambda: {
    "status": "pending",
    "result": None,
    "error": None,
    "debug_info": [],
    "company": None,
    "report": None,
    "last_update": datetime.now().isoformat(),
    "events": JobEventLog(),
})
