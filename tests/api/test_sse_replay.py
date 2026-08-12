from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import application
from backend.classes.state import JobEventLog, job_status, prune_expired_jobs


def _sse_payloads(response_text: str) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


def test_event_log_assigns_versioned_monotonic_ids_without_mutating_input() -> None:
    events = JobEventLog()
    original = {
        "type": "professional_data_started",
        "event_id": 999,
        "meta": {"safe": True},
    }

    events.append(original)
    original["meta"]["safe"] = False
    events.append({"type": "professional_data_completed", "version": 999})

    assert events[0]["meta"] == {"safe": True}
    assert [event["event_id"] for event in events] == [1, 2]
    assert [event["version"] for event in events] == [1, 1]
    assert [event["event_id"] for event in events.after(1)] == [2]


def test_sse_reconnect_replays_only_events_after_client_cursor() -> None:
    job_id = "job-sse-replay"
    events = JobEventLog()
    events.append({"type": "professional_data_started"})
    events.append({"type": "professional_data_completed"})
    job_status[job_id] = {
        "status": "completed",
        "report": "报告",
        "events": events,
    }
    try:
        response = TestClient(application.app).get(
            f"/research/{job_id}/stream",
            headers={"Last-Event-ID": "1"},
        )
    finally:
        job_status.pop(job_id, None)

    assert response.status_code == 200
    assert "id: 1" not in response.text
    assert "id: 2" in response.text
    assert _sse_payloads(response.text) == [
        {
            "type": "professional_data_completed",
            "version": 1,
            "event_id": 2,
        }
    ]


def test_two_sse_clients_do_not_consume_each_others_events() -> None:
    job_id = "job-sse-two-clients"
    events = JobEventLog()
    events.append({"type": "professional_data_started"})
    job_status[job_id] = {"status": "completed", "events": events}
    try:
        first = TestClient(application.app).get(f"/research/{job_id}/stream")
        second = TestClient(application.app).get(f"/research/{job_id}/stream")
    finally:
        job_status.pop(job_id, None)

    assert _sse_payloads(first.text) == _sse_payloads(second.text)
    assert len(events) == 1


def test_invalid_last_event_id_is_rejected() -> None:
    response = TestClient(application.app).get(
        "/research/unknown/stream",
        headers={"Last-Event-ID": "not-a-number"},
    )

    assert response.status_code == 400


def test_event_log_is_bounded_read_only_and_reports_expired_cursor() -> None:
    events = JobEventLog(max_events=2, max_bytes=1024 * 1024)
    events.extend(
        [
            {"type": "progress", "step": "one"},
            {"type": "progress", "step": "two"},
            {"type": "progress", "step": "three"},
        ]
    )

    assert [event["event_id"] for event in events] == [2, 3]
    assert events.history_expired(0) is True
    assert not hasattr(events, "pop")
    assert not hasattr(events, "clear")

    with pytest.raises(ValueError, match="超过字节限制"):
        JobEventLog(max_events=2, max_bytes=32).append(
            {"type": "progress", "step": "x" * 100}
        )


def test_concurrent_event_append_keeps_unique_monotonic_ids() -> None:
    events = JobEventLog(max_events=200, max_bytes=1024 * 1024)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda number: events.append({"type": "progress", "step": str(number)}),
                range(100),
            )
        )

    assert [event["event_id"] for event in events] == list(range(1, 101))


def test_expired_sse_cursor_returns_observable_reset_event() -> None:
    job_id = "job-sse-expired"
    events = JobEventLog(max_events=2, max_bytes=1024 * 1024)
    events.extend(
        [
            {"type": "progress", "step": "one"},
            {"type": "progress", "step": "two"},
            {"type": "progress", "step": "three"},
        ]
    )
    job_status[job_id] = {"status": "processing", "events": events}
    try:
        response = TestClient(application.app).get(
            f"/research/{job_id}/stream",
            headers={"Last-Event-ID": "0"},
        )
    finally:
        job_status.pop(job_id, None)

    assert response.status_code == 200
    assert _sse_payloads(response.text) == [
        {
            "type": "stream_reset_required",
            "reason": "event_history_expired",
            "version": 1,
        }
    ]


def test_non_terminal_degradation_does_not_hide_later_completion() -> None:
    job_id = "job-sse-degraded-complete"
    events = JobEventLog()
    events.append({"type": "report_degraded", "reason": "formatting_failed"})
    events.append({"type": "complete", "report": "基础报告"})
    job_status[job_id] = {
        "status": "completed",
        "report": "基础报告",
        "events": events,
    }
    try:
        response = TestClient(application.app).get(f"/research/{job_id}/stream")
    finally:
        job_status.pop(job_id, None)

    assert [event["type"] for event in _sse_payloads(response.text)] == [
        "report_degraded",
        "complete",
    ]


@pytest.mark.asyncio
async def test_research_failure_event_and_log_do_not_leak_exception_text(
    monkeypatch,
    caplog,
) -> None:
    class FailingGraph:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            if False:
                yield {}
            raise RuntimeError("Authorization: Bearer upstream-secret")

    async def no_sleep(*_args, **_kwargs) -> None:
        return None

    job_id = "job-safe-research-error"
    monkeypatch.setattr(application, "Graph", FailingGraph)
    monkeypatch.setattr(application.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(application, "mongodb", None)
    job_status.pop(job_id, None)
    try:
        await application.process_research(
            job_id,
            application.ResearchRequest(company="示例科技"),
        )
        state = job_status[job_id]
    finally:
        job_status.pop(job_id, None)

    serialized = json.dumps(state, ensure_ascii=False, default=list)
    assert state["status"] == "failed"
    assert state["events"][-1]["reason"] == "research_failed"
    assert "upstream-secret" not in serialized
    assert "upstream-secret" not in caplog.text


@pytest.mark.parametrize(
    ("status_code", "expected_reason", "expected_message"),
    [
        (
            400,
            "provider_request_invalid",
            "所选厂商不接受当前模型或请求参数，请重新加载模型列表后重试",
        ),
        (
            401,
            "provider_authentication_failed",
            "所选厂商拒绝了 API Key，请检查 Key 是否正确或已失效",
        ),
        (
            402,
            "provider_balance_insufficient",
            "所选厂商账户余额不足，请充值或改用免费模型后重试",
        ),
        (
            403,
            "provider_permission_denied",
            "当前 API Key 无权使用所选模型或联网搜索，请检查厂商账户权限",
        ),
        (
            404,
            "provider_model_unavailable",
            "所选模型不存在或已下线，请重新加载模型列表后选择其他模型",
        ),
        (408, "provider_timeout", "所选厂商响应超时，请稍后重试"),
        (
            429,
            "provider_rate_limited",
            "所选厂商请求过于频繁或免费额度已用完，请稍后重试或更换模型",
        ),
        (503, "provider_unavailable", "所选厂商服务暂时不可用，请稍后重试"),
    ],
)
@pytest.mark.asyncio
async def test_provider_status_failure_returns_safe_actionable_message(
    monkeypatch,
    caplog,
    status_code: int,
    expected_reason: str,
    expected_message: str,
) -> None:
    class ProviderStatusError(RuntimeError):
        def __init__(self, message: str) -> None:
            super().__init__(message)
            self.status_code = status_code

    class FailingGraph:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            if False:
                yield {}
            try:
                raise ProviderStatusError(
                    "Authorization: Bearer upstream-secret; account=-0.27"
                )
            except ProviderStatusError:
                raise RuntimeError("严重 API 错误：查询词生成失败") from None

    async def no_sleep(*_args, **_kwargs) -> None:
        return None

    job_id = f"job-provider-{status_code}-error"
    monkeypatch.setattr(application, "Graph", FailingGraph)
    monkeypatch.setattr(application.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(application, "mongodb", None)
    job_status.pop(job_id, None)
    try:
        await application.process_research(
            job_id,
            application.ResearchRequest(company="示例科技"),
        )
        state = job_status[job_id]
    finally:
        job_status.pop(job_id, None)

    event = state["events"][-1]
    serialized = json.dumps(state, ensure_ascii=False, default=list)
    assert event["reason"] == expected_reason
    assert event["error"] == expected_message
    assert "upstream-secret" not in serialized
    assert "upstream-secret" not in caplog.text


def test_terminal_job_ttl_pruning_removes_only_expired_state() -> None:
    expired_id = "job-expired"
    active_id = "job-active"
    job_status[expired_id] = {"status": "completed", "expires_at_epoch": 10}
    job_status[active_id] = {"status": "completed", "expires_at_epoch": 30}
    try:
        prune_expired_jobs(now_epoch=20)
        assert expired_id not in job_status
        assert active_id in job_status
    finally:
        job_status.pop(expired_id, None)
        job_status.pop(active_id, None)
