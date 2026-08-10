from __future__ import annotations

import pytest
from fastapi import HTTPException

import application


class FailingPdfService:
    def generate_pdf_stream(self, _report_content, _company_name):
        return False, "Authorization: Bearer upstream-secret"


@pytest.mark.asyncio
async def test_pdf_failure_does_not_expose_internal_error(monkeypatch, caplog) -> None:
    monkeypatch.setattr(application, "pdf_service", FailingPdfService())

    with pytest.raises(HTTPException) as captured:
        await application.generate_pdf(
            application.PDFGenerationRequest(
                report_content="# 示例报告",
                company_name="示例科技",
            )
        )

    assert captured.value.detail == "PDF 生成失败"
    assert "upstream-secret" not in caplog.text
