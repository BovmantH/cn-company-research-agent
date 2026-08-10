from __future__ import annotations

from datetime import datetime, timezone

from backend.services.company_intelligence.config import DATA_CAPABILITIES
from backend.services.company_intelligence.models import (
    BankruptcyRecord,
    CollectionStatus,
    CompanyChangeRecord,
    CompanyIdentity,
    DishonestRecord,
    EnforcementRecord,
    EvidenceCollection,
    HighConsumptionRestriction,
    JudicialCaseRecord,
    ProfessionalEvidence,
    RegistrationRecord,
    SeriousViolationRecord,
    ShareholderRecord,
    SourceMetadata,
)
from backend.services.company_intelligence.rendering import (
    MAX_PROFESSIONAL_APPENDIX_BYTES,
    render_professional_coverage_markdown,
    render_professional_evidence_markdown,
)

IDENTITY = CompanyIdentity(
    canonical_name="示例科技有限公司",
    credit_code="91320594MA1N00000X",
    registration_status="存续",
    region="江苏省",
    provider_subject_id="internal-provider-id",
    original_query="用户原始查询",
)
QUERIED_AT = datetime(2026, 8, 10, 1, 2, 3, tzinfo=timezone.utc)


def _source(capability: str, status: CollectionStatus) -> SourceMetadata:
    return SourceMetadata(
        server="qcc-company" if capability.startswith("company.") else "qcc-risk",
        capability=capability,
        queried_subject=IDENTITY.credit_code,
        queried_at=QUERIED_AT,
        cache_hit=True,
        status=status,
    )


def _evidence(
    overrides: dict[str, EvidenceCollection] | None = None,
) -> ProfessionalEvidence:
    collections = {
        capability: EvidenceCollection(
            capability=capability,
            status=CollectionStatus.NOT_REQUESTED,
            reason_code="not_requested",
        )
        for capability in DATA_CAPABILITIES
    }
    collections.update(overrides or {})
    return ProfessionalEvidence(
        identity=IDENTITY,
        collections=collections,
        generated_at=datetime(2026, 8, 10, 2, 3, 4, tzinfo=timezone.utc),
    )


def test_renderer_uses_fixed_capability_order_and_distinct_statuses() -> None:
    evidence = _evidence(
        {
            "company.registration": EvidenceCollection(
                capability="company.registration",
                status=CollectionStatus.SUCCEEDED_WITH_RECORDS,
                records=[
                    RegistrationRecord(
                        legal_representative="张三",
                        source=_source(
                            "company.registration",
                            CollectionStatus.SUCCEEDED_WITH_RECORDS,
                        ),
                    )
                ],
                source=_source(
                    "company.registration",
                    CollectionStatus.SUCCEEDED_WITH_RECORDS,
                ),
            ),
            "company.shareholders": EvidenceCollection(
                capability="company.shareholders",
                status=CollectionStatus.SUCCEEDED_EMPTY,
                source=_source(
                    "company.shareholders", CollectionStatus.SUCCEEDED_EMPTY
                ),
            ),
            "company.changes": EvidenceCollection(
                capability="company.changes",
                status=CollectionStatus.PARTIAL,
                records=[
                    CompanyChangeRecord(
                        item="住所变更",
                        before="旧地址",
                        after="新地址",
                        changed_on="2026-01-01",
                        source=_source("company.changes", CollectionStatus.PARTIAL),
                    )
                ],
                source=_source("company.changes", CollectionStatus.PARTIAL),
                reason_code="provider_partial",
            ),
            "risk.case_filings": EvidenceCollection(
                capability="risk.case_filings",
                status=CollectionStatus.FAILED,
                source=_source("risk.case_filings", CollectionStatus.FAILED),
                reason_code="provider_call_failed",
            ),
            "risk.enforcement": EvidenceCollection(
                capability="risk.enforcement",
                status=CollectionStatus.UNAVAILABLE,
                reason_code="provider_unavailable",
            ),
            "risk.dishonest": EvidenceCollection(
                capability="risk.dishonest",
                status=CollectionStatus.BUDGET_BLOCKED,
                reason_code="budget_blocked",
            ),
            "risk.high_consumption": EvidenceCollection(
                capability="risk.high_consumption",
                status=CollectionStatus.IDENTITY_UNCONFIRMED,
                reason_code="identity_unconfirmed",
            ),
        }
    )

    rendered = render_professional_evidence_markdown(evidence)

    assert rendered == render_professional_evidence_markdown(evidence)
    headings = [
        "### 工商登记",
        "### 股东信息",
        "### 工商变更",
        "### 立案信息",
        "### 裁判文书",
        "### 被执行信息",
        "### 失信信息",
        "### 限制高消费",
        "### 破产信息",
        "### 严重违法",
    ]
    assert [rendered.index(heading) for heading in headings] == sorted(
        rendered.index(heading) for heading in headings
    )
    for status_text in (
        "查询成功（1 条）",
        "查询成功，未发现记录",
        "部分成功（1 条已验证）",
        "查询失败",
        "未请求",
        "当前不可用",
        "预算已阻止",
        "主体未确认",
    ):
        assert status_text in rendered
    assert "不构成法律、征信、投资或信贷意见" in rendered
    assert "https://zxgk.court.gov.cn/" in rendered


def test_coverage_renderer_never_echoes_unknown_reason() -> None:
    rendered = render_professional_coverage_markdown(
        "Authorization: Bearer upstream-secret"
    )

    assert "本次专业数据未完成采集" in rendered
    assert "upstream-secret" not in rendered


def test_renderer_outputs_every_record_type_without_llm_rewriting() -> None:
    succeeded = CollectionStatus.SUCCEEDED_WITH_RECORDS
    records = {
        "company.registration": RegistrationRecord(
            legal_representative="张三",
            registered_capital="1000万元人民币",
            established_on="2020-01-02",
            registration_status="存续",
            registered_address="南京市示例路1号",
            business_scope="软件开发",
            source=_source("company.registration", succeeded),
        ),
        "company.shareholders": ShareholderRecord(
            shareholder_name="李四",
            shareholder_type="自然人股东",
            ownership_ratio="60%",
            subscribed_amount="600万元人民币",
            subscribed_on="2020-01-02",
            source=_source("company.shareholders", succeeded),
        ),
        "company.changes": CompanyChangeRecord(
            item="法定代表人",
            before="王五",
            after="张三",
            changed_on="2021-02-03",
            source=_source("company.changes", succeeded),
        ),
        "risk.case_filings": JudicialCaseRecord(
            case_number="（2026）苏01民初1号",
            cause="合同纠纷",
            court="南京市中级人民法院",
            filed_on="2026-03-04",
            plaintiffs=["原告甲"],
            defendants=["被告乙"],
            third_parties=["第三人丙"],
            amount="88万元",
            summary="一审立案",
            source=_source("risk.case_filings", succeeded),
        ),
        "risk.judicial_documents": JudicialCaseRecord(
            case_number="（2026）苏01民终2号",
            cause="买卖合同纠纷",
            court="江苏省高级人民法院",
            filed_on="2026-04-05",
            plaintiffs=["上诉人甲"],
            defendants=["被上诉人乙"],
            amount="99万元",
            summary="二审判决",
            source=_source("risk.judicial_documents", succeeded),
        ),
        "risk.enforcement": EnforcementRecord(
            case_number="（2026）苏01执3号",
            court="南京市中级人民法院",
            filed_on="2026-05-06",
            amount="12万元",
            status_text="执行中",
            source=_source("risk.enforcement", succeeded),
        ),
        "risk.dishonest": DishonestRecord(
            case_number="（2026）苏01执4号",
            court="南京市中级人民法院",
            conduct="有履行能力而拒不履行",
            performance_status="全部未履行",
            published_on="2026-06-07",
            source=_source("risk.dishonest", succeeded),
        ),
        "risk.high_consumption": HighConsumptionRestriction(
            case_number="（2026）苏01执5号",
            applicant="申请人甲",
            restricted_subject="示例科技有限公司",
            related_legal_representative="张三",
            filed_on="2026-07-08",
            source=_source("risk.high_consumption", succeeded),
        ),
        "risk.bankruptcy": BankruptcyRecord(
            case_number="（2026）苏01破6号",
            applicant="债权人甲",
            respondent="示例科技有限公司",
            court="南京市中级人民法院",
            published_on="2026-08-09",
            source=_source("risk.bankruptcy", succeeded),
        ),
        "risk.serious_violation": SeriousViolationRecord(
            reason="提交虚假材料",
            listed_on="2026-08-10",
            authority="南京市市场监督管理局",
            status_text="列入",
            source=_source("risk.serious_violation", succeeded),
        ),
    }
    evidence = _evidence(
        {
            capability: EvidenceCollection(
                capability=capability,
                status=succeeded,
                records=[record],
                source=_source(capability, succeeded),
            )
            for capability, record in records.items()
        }
    )

    rendered = render_professional_evidence_markdown(evidence)

    for fact in (
        "张三",
        "1000万元人民币",
        "李四",
        "60%",
        "法定代表人",
        "（2026）苏01民初1号",
        "南京市中级人民法院",
        "原告甲",
        "被告乙",
        "第三人丙",
        "88万元",
        "（2026）苏01执3号",
        "有履行能力而拒不履行",
        "申请人甲",
        "债权人甲",
        "提交虚假材料",
    ):
        assert fact in rendered
    assert "internal-provider-id" not in rendered
    assert "用户原始查询" not in rendered


def test_renderer_escapes_html_and_markdown_from_provider_fields() -> None:
    malicious_name = "<script>alert(1)</script> [点我](javascript:alert(1)) | *粗体* \\"
    status = CollectionStatus.SUCCEEDED_WITH_RECORDS
    evidence = _evidence(
        {
            "company.shareholders": EvidenceCollection(
                capability="company.shareholders",
                status=status,
                records=[
                    ShareholderRecord(
                        shareholder_name=malicious_name,
                        source=_source("company.shareholders", status),
                    )
                ],
                source=_source("company.shareholders", status),
            )
        }
    )

    rendered = render_professional_evidence_markdown(evidence)

    assert "<script>" not in rendered
    assert r"&lt;script&gt;alert\(1\)&lt;/script&gt;" in rendered
    assert "[点我](javascript:" not in rendered
    assert "\\|" in rendered
    assert "\\*粗体\\*" in rendered


def test_renderer_truncates_large_fields_and_record_sets_within_byte_budget() -> None:
    status = CollectionStatus.SUCCEEDED_WITH_RECORDS
    source = _source("risk.case_filings", status)
    record_source = source.model_copy(update={"record_id": "private-record-id"})
    records = [
        JudicialCaseRecord(
            case_number=(
                "AAAA-窗口外记录" if number == 59 else f"（2026）苏01民初{number}号"
            ),
            summary="摘要" * 10_000,
            source=record_source,
        )
        for number in range(60)
    ]
    evidence = _evidence(
        {
            "risk.case_filings": EvidenceCollection(
                capability="risk.case_filings",
                status=status,
                records=records,
                source=source,
            )
        }
    )

    rendered = render_professional_evidence_markdown(evidence)

    assert len(rendered.encode("utf-8")) <= MAX_PROFESSIONAL_APPENDIX_BYTES
    assert "内容已截断" in rendered
    assert "共 60 条；超出部分未写入报告" in rendered
    assert "AAAA-窗口外记录" not in rendered
    assert "private-record-id" not in rendered
