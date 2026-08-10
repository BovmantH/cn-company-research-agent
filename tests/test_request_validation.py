import io

import pytest
from fastapi.testclient import TestClient

import application


@pytest.fixture(autouse=True)
def isolate_request_validation_from_external_services(monkeypatch) -> None:
    def fake_process(*_args, **_kwargs):
        async def noop() -> None:
            return None

        return noop()

    def fake_schedule(coroutine, **_kwargs):
        coroutine.close()
        return object()

    monkeypatch.setattr(application, "process_research", fake_process)
    monkeypatch.setattr(application, "_schedule_research", fake_schedule)
    monkeypatch.setattr(
        application.pdf_service,
        "generate_pdf_stream",
        lambda *_args, **_kwargs: (True, (io.BytesIO(b"%PDF-test"), "test.pdf")),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"company": " "},
        {"company": "公" * 201},
        {"company": "示例公司", "company_url": "h" * 2049},
        {"company": "示例公司", "industry": "行" * 201},
        {"company": "示例公司", "hq_location": "地" * 201},
    ],
)
def test_research_rejects_empty_or_oversized_fields(payload) -> None:
    response = TestClient(application.app).post("/research", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"report_content": ""},
        {"report_content": "报" * 2_000_001},
        {"report_content": "报告", "company_name": "公" * 201},
    ],
)
def test_pdf_generation_rejects_empty_or_oversized_fields(payload) -> None:
    response = TestClient(application.app).post("/generate-pdf", json=payload)

    assert response.status_code == 422
