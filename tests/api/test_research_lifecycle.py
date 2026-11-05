from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import application


@pytest.fixture
def waiting_graph(monkeypatch):
    entered = asyncio.Event()

    class WaitingGraph:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            entered.set()
            await asyncio.Event().wait()
            yield {"editor": {"report": "不应完成的报告"}}

    monkeypatch.setattr(application, "Graph", WaitingGraph)
    monkeypatch.setattr(application, "mongodb", None)
    return entered


@pytest.mark.asyncio
async def test_running_cancellation_has_terminal_event_and_expiry(
    waiting_graph,
) -> None:
    job_id = "job-running-cancel"
    task = asyncio.create_task(
        application.process_research(
            job_id, application.ResearchRequest(company="示例公司")
        )
    )
    try:
        await asyncio.wait_for(waiting_graph.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        state = application.job_status[job_id]
        assert state["status"] == "failed"
        assert state["error"] == "调研任务已取消"
        assert state["expires_at_epoch"] > time.time()
        assert state["events"][-1]["reason"] == "research_cancelled"
        response = TestClient(application.app).get(f"/research/{job_id}/stream")
        assert '"reason": "research_cancelled"' in response.text
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        application.job_status.pop(job_id, None)


@pytest.mark.asyncio
async def test_shutdown_wait_is_bounded_for_uncooperative_task(
    monkeypatch, caplog
) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def stubborn_work() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    monkeypatch.setattr(application, "_RESEARCH_SHUTDOWN_TIMEOUT_SECONDS", 0.01)
    task = None
    try:
        async with application._application_lifespan(application.app):
            task = asyncio.create_task(stubborn_work())
            application._register_background_task(task)
            await entered.wait()

        assert cancelled.is_set()
        assert not task.done()
        assert "停机等待超时" in caplog.text
    finally:
        release.set()
        if task is not None:
            await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_shutdown_cancels_and_drains_running_research(waiting_graph) -> None:
    job_id = "job-shutdown-cancel"
    task = None
    try:
        async with application._application_lifespan(application.app):
            task = application._schedule_research(
                application.process_research(
                    job_id, application.ResearchRequest(company="示例公司")
                ),
                runtime=application.app.state.company_intelligence,
                preparation=None,
            )
            await asyncio.wait_for(waiting_graph.wait(), timeout=2)

        assert task.cancelled()
        assert task not in application.app.state.research_tasks
        state = application.job_status[job_id]
        assert state["status"] == "failed"
        assert state["events"][-1]["reason"] == "research_cancelled"
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        application.job_status.pop(job_id, None)
