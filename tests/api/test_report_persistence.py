from __future__ import annotations

import pytest

import application


class CompletedGraph:
    def __init__(self, **_kwargs) -> None:
        pass

    async def run(self, thread):
        assert thread == {}
        yield {"editor": {"report": "# 示例公司调研报告\n\n已生成的正文"}}


class FailingMongo:
    def __init__(self, failure_stage: str) -> None:
        self.failure_stage = failure_stage
        self.saved_report: str | None = None

    def create_job(self, _job_id, _inputs) -> None:
        pass

    def store_report(self, *, job_id, report_data) -> None:
        if self.failure_stage == "report":
            raise ConnectionError("upstream-storage-private-detail")
        self.saved_report = report_data["report"]

    def update_job(self, *, job_id, status, **_kwargs) -> None:
        if self.failure_stage in {"status", "failed_status"}:
            raise ConnectionError("upstream-storage-private-detail")

    def get_report(self, _job_id):
        raise AssertionError("内存中已有报告时不应依赖故障数据库")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["report", "status"])
async def test_storage_failure_preserves_completed_report_and_sse(
    monkeypatch, caplog, failure_stage
) -> None:
    job_id = f"job-storage-failed-{failure_stage}"
    monkeypatch.setattr(application, "Graph", CompletedGraph)
    monkeypatch.setattr(application, "mongodb", FailingMongo(failure_stage))
    try:
        await application.process_research(
            job_id, application.ResearchRequest(company="示例公司")
        )
        state = application.job_status[job_id]

        assert state["status"] == "completed"
        assert state["report"] == "# 示例公司调研报告\n\n已生成的正文"
        events = list(state["events"])
        assert events[-1]["type"] == "complete"
        assert events[-1]["report"] == state["report"]
        assert any(
            event["type"] == "report_degraded"
            and event["reason"] == "persistence_failed"
            for event in events
        )
        assert not any(event["type"] == "error" for event in events)
        assert await application.get_research_report(job_id) == {
            "report": state["report"]
        }
        assert "upstream-storage-private-detail" not in caplog.text
    finally:
        application.job_status.pop(job_id, None)


@pytest.mark.asyncio
async def test_failure_status_storage_error_does_not_replace_research_error(
    monkeypatch, caplog
) -> None:
    class FailedGraph(CompletedGraph):
        async def run(self, thread):
            raise RuntimeError("upstream-generation-private-detail")
            yield  # 仍模拟真实 Graph 的异步生成器边界。

    job_id = "job-failed-storage-also-failed"
    monkeypatch.setattr(application, "Graph", FailedGraph)
    monkeypatch.setattr(application, "mongodb", FailingMongo("failed_status"))
    try:
        await application.process_research(
            job_id, application.ResearchRequest(company="示例公司")
        )
        state = application.job_status[job_id]
        assert state["status"] == "failed"
        assert state["error"] == "调研任务执行失败"
        assert state["events"][-1]["reason"] == "research_failed"
        assert "upstream-generation-private-detail" not in caplog.text
        assert "upstream-storage-private-detail" not in caplog.text
    finally:
        application.job_status.pop(job_id, None)
