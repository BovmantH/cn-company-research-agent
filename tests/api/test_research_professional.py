from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

import application
from backend.services.company_intelligence.collection import (
    PreparationKind,
    ProfessionalPreparation,
)
from backend.services.company_intelligence.config import (
    DATA_CAPABILITIES,
    ProfessionalDataSettings,
)
from backend.services.company_intelligence.models import (
    CollectionStatus,
    CompanyIdentity,
    EvidenceCollection,
    ProfessionalEvidence,
    SourceMetadata,
)


@dataclass
class RuntimeStub:
    preparation: ProfessionalPreparation
    settings: ProfessionalDataSettings = field(
        default_factory=lambda: ProfessionalDataSettings.from_env({})
    )
    abandoned: list[ProfessionalPreparation] = field(default_factory=list)
    prepare_calls: int = 0

    def prepare_professional_research(self, **_kwargs) -> ProfessionalPreparation:
        self.prepare_calls += 1
        return self.preparation

    def abandon_professional_research(
        self, preparation: ProfessionalPreparation
    ) -> None:
        self.abandoned.append(preparation)


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        provider_subject_id="provider-id",
        original_query="示例科技",
        match_method="exact",
    )


def _capture_scheduled_research(monkeypatch):
    scheduled = []

    def fake_process(job_id, data, **kwargs):
        scheduled.append((job_id, data, kwargs))

        async def noop():
            return None

        return noop()

    def fake_schedule(coroutine, **_kwargs):
        coroutine.close()
        return object()

    monkeypatch.setattr(application, "process_research", fake_process)
    monkeypatch.setattr(application, "_schedule_research", fake_schedule)
    return scheduled


def test_old_research_payload_remains_compatible(monkeypatch) -> None:
    scheduled = _capture_scheduled_research(monkeypatch)

    response = TestClient(application.app).post(
        "/research",
        json={"company": "示例科技"},
    )

    assert response.status_code == 200
    assert "professional_data" not in response.json()
    assert len(scheduled) == 1
    assert scheduled[0][1].professional_data is None
    assert scheduled[0][2]["professional_preparation"] is None


def test_enabled_professional_data_requires_resolution_token() -> None:
    response = TestClient(application.app).post(
        "/research",
        json={
            "company": "示例科技",
            "professional_data": {"enabled": True},
        },
    )

    assert response.status_code == 422


def test_ready_professional_branch_is_scheduled_without_persisting_token(
    monkeypatch,
) -> None:
    scheduled = _capture_scheduled_research(monkeypatch)
    preparation = ProfessionalPreparation(
        kind=PreparationKind.READY,
        job_id="job-new",
        identity=_identity(),
        reservation_id="reservation-1",
    )
    original_runtime = application.app.state.company_intelligence
    application.app.state.company_intelligence = RuntimeStub(preparation)
    try:
        response = TestClient(application.app).post(
            "/research",
            json={
                "company": "前端被篡改的公司",
                "professional_data": {
                    "enabled": True,
                    "resolution_token": "signed-once-token",
                },
            },
        )
    finally:
        application.app.state.company_intelligence = original_runtime

    assert response.status_code == 200
    assert response.json()["professional_data"] == {
        "status": "accepted",
        "reason": None,
    }
    assert len(scheduled) == 1
    assert scheduled[0][1].professional_data is None
    assert scheduled[0][1].company == "示例科技有限公司"
    assert scheduled[0][2]["professional_preparation"] is preparation
    assert "signed-once-token" not in repr(scheduled)


def test_blocked_professional_branch_degrades_to_base_research(
    monkeypatch,
) -> None:
    scheduled = _capture_scheduled_research(monkeypatch)
    preparation = ProfessionalPreparation(
        kind=PreparationKind.BLOCKED,
        reason_code="budget_blocked",
    )
    original_runtime = application.app.state.company_intelligence
    application.app.state.company_intelligence = RuntimeStub(preparation)
    try:
        response = TestClient(application.app).post(
            "/research",
            json={
                "company": "示例科技",
                "professional_data": {
                    "enabled": True,
                    "resolution_token": "signed-once-token",
                },
            },
        )
    finally:
        application.app.state.company_intelligence = original_runtime

    assert response.status_code == 200
    assert response.json()["professional_data"] == {
        "status": "degraded",
        "reason": "budget_blocked",
    }
    assert len(scheduled) == 1
    assert scheduled[0][2]["professional_preparation"] is None
    assert scheduled[0][2]["professional_blocked_reason"] == "budget_blocked"


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [
        (PreparationKind.IN_PROGRESS, "in_progress"),
        (PreparationKind.REPLAYED, "replayed"),
    ],
)
def test_professional_replay_returns_original_job_without_rescheduling(
    monkeypatch,
    kind,
    expected_status,
) -> None:
    scheduled = _capture_scheduled_research(monkeypatch)
    preparation = ProfessionalPreparation(
        kind=kind,
        job_id="job-original",
    )
    original_runtime = application.app.state.company_intelligence
    application.app.state.company_intelligence = RuntimeStub(preparation)
    try:
        response = TestClient(application.app).post(
            "/research",
            json={
                "company": "示例科技",
                "professional_data": {
                    "enabled": True,
                    "resolution_token": "signed-once-token",
                },
            },
        )
    finally:
        application.app.state.company_intelligence = original_runtime

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-original"
    assert response.json()["professional_data"]["status"] == expected_status
    assert scheduled == []


def test_disabled_professional_object_has_no_provider_side_effect(
    monkeypatch,
) -> None:
    scheduled = _capture_scheduled_research(monkeypatch)
    runtime = RuntimeStub(ProfessionalPreparation(kind=PreparationKind.BLOCKED))
    original_runtime = application.app.state.company_intelligence
    application.app.state.company_intelligence = runtime
    try:
        response = TestClient(application.app).post(
            "/research",
            json={
                "company": "示例科技",
                "professional_data": {
                    "enabled": False,
                    "resolution_token": "ignored-token",
                },
            },
        )
    finally:
        application.app.state.company_intelligence = original_runtime

    assert response.status_code == 200
    assert "professional_data" not in response.json()
    assert runtime.prepare_calls == 0
    assert scheduled[0][1].professional_data is None
    assert "ignored-token" not in repr(scheduled)


def test_scheduling_failure_releases_professional_reservation(monkeypatch) -> None:
    preparation = ProfessionalPreparation(
        kind=PreparationKind.READY,
        job_id="job-new",
        identity=_identity(),
        reservation_id="reservation-1",
    )
    runtime = RuntimeStub(preparation)

    def fail_schedule(coroutine, **_kwargs):
        coroutine.close()
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(application, "_schedule_research", fail_schedule)
    original_runtime = application.app.state.company_intelligence
    application.app.state.company_intelligence = runtime
    try:
        response = TestClient(application.app).post(
            "/research",
            json={
                "company": "示例科技",
                "professional_data": {
                    "enabled": True,
                    "resolution_token": "signed-once-token",
                },
            },
        )
    finally:
        application.app.state.company_intelligence = original_runtime

    assert response.status_code == 500
    assert runtime.abandoned == [preparation]


async def _no_sleep(*_args, **_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_professional_failure_does_not_block_base_report(
    monkeypatch,
    caplog,
) -> None:
    class GraphStub:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            assert thread == {}
            yield {"report": "基础 Web 报告"}

    class FailingRuntime:
        settings = ProfessionalDataSettings.from_env({})

        async def collect_professional_research(self, _preparation):
            raise RuntimeError("Authorization: Bearer upstream-secret")

    job_id = "job-professional-degraded"
    original_runtime = application.app.state.company_intelligence
    monkeypatch.setattr(application, "Graph", GraphStub)
    monkeypatch.setattr(application.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(application, "mongodb", None)
    application.app.state.company_intelligence = FailingRuntime()
    application.job_status.pop(job_id, None)
    try:
        await application.process_research(
            job_id,
            application.ResearchRequest(company="示例科技"),
            professional_preparation=ProfessionalPreparation(
                kind=PreparationKind.READY,
                job_id=job_id,
                reservation_id="reservation-1",
            ),
        )
        state = application.job_status[job_id]
    finally:
        application.app.state.company_intelligence = original_runtime
        application.job_status.pop(job_id, None)

    assert state["status"] == "completed"
    assert state["report"].startswith("基础 Web 报告\n\n## 工商与司法专业数据")
    assert "专业数据源暂时不可用" in state["report"]
    professional_events = [
        event
        for event in state["events"]
        if event["type"].startswith("professional_data_")
    ]
    assert [event["type"] for event in professional_events] == [
        "professional_data_started",
        "professional_data_degraded",
    ]
    assert professional_events[1]["reason"] == "provider_unavailable"
    assert "upstream-secret" not in caplog.text


@pytest.mark.asyncio
async def test_professional_evidence_is_appended_before_persist_and_complete(
    monkeypatch,
) -> None:
    class GraphStub:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            assert thread == {}
            yield {"report": "基础 Web 报告"}

    identity = _identity()
    collections = {
        capability: EvidenceCollection(
            capability=capability,
            status=CollectionStatus.SUCCEEDED_EMPTY,
            source=SourceMetadata(
                server=(
                    "qcc-company" if capability.startswith("company.") else "qcc-risk"
                ),
                capability=capability,
                queried_subject=identity.credit_code,
                status=CollectionStatus.SUCCEEDED_EMPTY,
            ),
        )
        for capability in DATA_CAPABILITIES
    }
    evidence = ProfessionalEvidence(identity=identity, collections=collections)

    class SuccessfulRuntime:
        settings = ProfessionalDataSettings.from_env({})

        async def collect_professional_research(self, _preparation):
            return evidence

    class MongoCapture:
        def __init__(self) -> None:
            self.report: str | None = None

        def create_job(self, _job_id, _data) -> None:
            return None

        def update_job(self, **_kwargs) -> None:
            return None

        def store_report(self, *, job_id, report_data) -> None:
            assert job_id == "job-professional-rendered"
            self.report = report_data["report"]

    job_id = "job-professional-rendered"
    mongo = MongoCapture()
    original_runtime = application.app.state.company_intelligence
    monkeypatch.setattr(application, "Graph", GraphStub)
    monkeypatch.setattr(application.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(application, "mongodb", mongo)
    application.app.state.company_intelligence = SuccessfulRuntime()
    application.job_status.pop(job_id, None)
    try:
        await application.process_research(
            job_id,
            application.ResearchRequest(company="示例科技有限公司"),
            professional_preparation=ProfessionalPreparation(
                kind=PreparationKind.READY,
                job_id=job_id,
                identity=identity,
                reservation_id="reservation-1",
            ),
        )
        state = application.job_status[job_id]
    finally:
        application.app.state.company_intelligence = original_runtime
        application.job_status.pop(job_id, None)

    assert state["status"] == "completed"
    assert state["report"].startswith("基础 Web 报告\n\n## 工商与司法专业数据")
    assert "查询成功，未发现记录" in state["report"]
    assert mongo.report == state["report"]
    complete = next(event for event in state["events"] if event["type"] == "complete")
    assert complete["report"] == state["report"]

    monkeypatch.setattr(
        application,
        "FINAL_REPORT_EVENT_MAX_BYTES",
        512,
        raising=False,
    )
    limited_report, appendix_omitted = application._append_professional_evidence(
        "基础 Web 报告",
        evidence.model_dump(mode="json"),
    )
    encoded_complete = application.json.dumps(
        {
            "type": "complete",
            "report": limited_report,
            "version": 1,
            "event_id": 9_999_999_999,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert appendix_omitted is True
    assert "因最终报告大小限制未展开" in limited_report
    assert len(encoded_complete) <= 512

    original_oversized_report = "基础内容" * 1_000
    oversized_report, appendix_omitted = application._append_professional_evidence(
        original_oversized_report,
        evidence.model_dump(mode="json"),
    )
    assert appendix_omitted is True
    assert oversized_report == original_oversized_report


@pytest.mark.asyncio
async def test_budget_blocked_event_still_completes_base_report(
    monkeypatch,
) -> None:
    class GraphStub:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            yield {"report": "基础 Web 报告"}

    job_id = "job-professional-budget-blocked"
    monkeypatch.setattr(application, "Graph", GraphStub)
    monkeypatch.setattr(application.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(application, "mongodb", None)
    application.job_status.pop(job_id, None)
    try:
        await application.process_research(
            job_id,
            application.ResearchRequest(company="示例科技"),
            professional_blocked_reason="budget_blocked",
        )
        state = application.job_status[job_id]
    finally:
        application.job_status.pop(job_id, None)

    assert state["status"] == "completed"
    assert state["report"].startswith("基础 Web 报告\n\n## 工商与司法专业数据")
    assert "专业数据预算已阻止本次采集" in state["report"]
    budget_event = next(
        event
        for event in state["events"]
        if event["type"] == "professional_data_budget_blocked"
    )
    assert budget_event["reason"] == "budget_blocked"
    assert budget_event["version"] == 1
    assert budget_event["event_id"] == 1


@pytest.mark.asyncio
async def test_hanging_professional_branch_times_out_without_blocking_report(
    monkeypatch,
) -> None:
    class GraphStub:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self, thread):
            yield {"report": "基础 Web 报告"}

    class HangingRuntime:
        settings = ProfessionalDataSettings.from_env({})

        def __init__(self) -> None:
            self.cancel_seen = asyncio.Event()
            self.release = asyncio.Event()
            self.finished = asyncio.Event()

        async def collect_professional_research(self, _preparation):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancel_seen.set()
                await self.release.wait()
            finally:
                self.finished.set()

    job_id = "job-professional-timeout"
    runtime = HangingRuntime()
    original_runtime = application.app.state.company_intelligence
    monkeypatch.setattr(application, "Graph", GraphStub)
    monkeypatch.setattr(application.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(application, "mongodb", None)
    monkeypatch.setattr(
        application,
        "_PROFESSIONAL_COLLECTION_TIMEOUT_SECONDS",
        0.01,
    )
    application.app.state.company_intelligence = runtime
    application.job_status.pop(job_id, None)
    try:
        await application.process_research(
            job_id,
            application.ResearchRequest(company="示例科技"),
            professional_preparation=ProfessionalPreparation(
                kind=PreparationKind.READY,
                job_id=job_id,
                identity=_identity(),
                reservation_id="reservation-1",
            ),
        )
        state = application.job_status[job_id]
    finally:
        application.app.state.company_intelligence = original_runtime
        application.job_status.pop(job_id, None)

    assert state["status"] == "completed"
    assert state["report"].startswith("基础 Web 报告\n\n## 工商与司法专业数据")
    assert "专业数据源暂时不可用" in state["report"]
    await asyncio.wait_for(runtime.cancel_seen.wait(), timeout=1)
    assert runtime.cancel_seen.is_set()
    degraded_event = next(
        event
        for event in state["events"]
        if event["type"] == "professional_data_degraded"
    )
    assert degraded_event["reason"] == "provider_unavailable"
    assert "professional_evidence" not in state
    runtime.release.set()
    await asyncio.wait_for(runtime.finished.wait(), timeout=1)


@pytest.mark.asyncio
async def test_mongo_job_creation_failure_releases_unstarted_reservation(
    monkeypatch,
) -> None:
    class MongoFailingStub:
        def create_job(self, _job_id, _data) -> None:
            raise RuntimeError("mongo unavailable")

        def update_job(self, **_kwargs) -> None:
            return None

    preparation = ProfessionalPreparation(
        kind=PreparationKind.READY,
        job_id="job-mongo-failed",
        identity=_identity(),
        reservation_id="reservation-1",
    )
    runtime = RuntimeStub(preparation)
    original_runtime = application.app.state.company_intelligence
    monkeypatch.setattr(application, "mongodb", MongoFailingStub())
    application.app.state.company_intelligence = runtime
    application.job_status.pop("job-mongo-failed", None)
    try:
        await application.process_research(
            "job-mongo-failed",
            application.ResearchRequest(company="示例科技"),
            professional_preparation=preparation,
        )
        state = application.job_status["job-mongo-failed"]
    finally:
        application.app.state.company_intelligence = original_runtime
        application.job_status.pop("job-mongo-failed", None)

    assert state["status"] == "failed"
    assert runtime.abandoned == [preparation]


@pytest.mark.asyncio
async def test_cancel_before_first_task_step_releases_reservation() -> None:
    preparation = ProfessionalPreparation(
        kind=PreparationKind.READY,
        job_id="job-cancel-before-start",
        identity=_identity(),
        reservation_id="reservation-1",
    )
    runtime = RuntimeStub(preparation)

    async def never_started() -> None:
        raise AssertionError("任务不应执行到第一步")

    task = application._schedule_research(
        never_started(),
        runtime=runtime,
        preparation=preparation,
    )
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert runtime.abandoned == [preparation]


@pytest.mark.asyncio
async def test_cancel_professional_child_before_first_step_releases_reservation() -> (
    None
):
    preparation = ProfessionalPreparation(
        kind=PreparationKind.READY,
        job_id="job-child-cancel-before-start",
        identity=_identity(),
        reservation_id="reservation-1",
    )
    runtime = RuntimeStub(preparation)
    original_runtime = application.app.state.company_intelligence
    application.app.state.company_intelligence = runtime
    try:
        task = application._schedule_professional_for_job(
            preparation.job_id or "job-fallback",
            preparation,
            application._ProfessionalTaskControl(),
        )
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        application.app.state.company_intelligence = original_runtime

    assert runtime.abandoned == [preparation]
