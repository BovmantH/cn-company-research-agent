"""专业企业数据的公开 HTTP 契约。"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services.company_intelligence.requester import resolve_client_ip
from backend.services.company_intelligence.resolution import (
    IdempotencyConflict,
    PublicResolution,
    ResolutionInProgress,
)
from backend.services.company_intelligence.runtime import CompanyIntelligenceRuntime

router = APIRouter(tags=["company-intelligence"])


class ResolveCompanyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=200)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """用 NFKC 统一全半角并拒绝控制字符，稳定后续幂等摘要。"""
        normalized = unicodedata.normalize("NFKC", value)
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("公司查询词不得包含控制字符")
        normalized = " ".join(normalized.split())
        if not normalized:
            raise ValueError("公司查询词不能为空")
        return normalized


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _runtime(request: Request) -> CompanyIntelligenceRuntime:
    return request.app.state.company_intelligence


@router.get("/capabilities")
async def get_capabilities(request: Request):
    """返回可安全公开的部署能力，不泄露密钥、余额或上游错误。"""
    return {"professional_company_data": _runtime(request).capability_state().as_dict()}


@router.post("/companies/resolve", response_model=PublicResolution)
async def resolve_company(
    data: ResolveCompanyRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
):
    """在可信代理边界解析请求方，并映射幂等冲突和处理中重放。"""
    runtime = _runtime(request)
    peer_ip = request.client.host if request.client else "unknown"
    client_ip = resolve_client_ip(
        peer_ip=peer_ip,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxy_cidrs=runtime.settings.trusted_proxy_cidrs,
    )
    try:
        return await runtime.resolve_company(
            query=data.query,
            idempotency_key=idempotency_key,
            client_ip=client_ip,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="idempotency_conflict") from exc
    except ResolutionInProgress:
        response = PublicResolution(kind="blocked", reason="resolution_in_progress")
        return JSONResponse(status_code=202, content=response.model_dump(mode="json"))
