"""把已校验的专业证据确定性渲染为安全 Markdown。"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .config import DATA_CAPABILITIES
from .models import (
    BankruptcyRecord,
    CollectionStatus,
    CompanyChangeRecord,
    DishonestRecord,
    EnforcementRecord,
    EvidenceCollection,
    EvidenceRecord,
    HighConsumptionRestriction,
    JudicialCaseRecord,
    ProfessionalEvidence,
    RegistrationRecord,
    SeriousViolationRecord,
    ShareholderRecord,
)

_CAPABILITY_TITLES = {
    "company.registration": "工商登记",
    "company.shareholders": "股东信息",
    "company.changes": "工商变更",
    "risk.case_filings": "立案信息",
    "risk.judicial_documents": "裁判文书",
    "risk.enforcement": "被执行信息",
    "risk.dishonest": "失信信息",
    "risk.high_consumption": "限制高消费",
    "risk.bankruptcy": "破产信息",
    "risk.serious_violation": "严重违法",
}

_STATUS_TEXT = {
    CollectionStatus.SUCCEEDED_EMPTY: "查询成功，未发现记录",
    CollectionStatus.FAILED: "查询失败",
    CollectionStatus.NOT_REQUESTED: "未请求",
    CollectionStatus.UNAVAILABLE: "当前不可用",
    CollectionStatus.BUDGET_BLOCKED: "预算已阻止",
    CollectionStatus.IDENTITY_UNCONFIRMED: "主体未确认",
}

_REASON_TEXT = {
    "provider_partial": "上游仅返回部分可验证结果",
    "provider_call_failed": "上游调用失败",
    "provider_unavailable": "专业数据服务当前不可用",
    "budget_blocked": "本次请求未通过预算准入",
    "identity_unconfirmed": "企业主体尚未完成确认",
    "not_requested": "本次未请求该项数据",
}

MAX_PROFESSIONAL_APPENDIX_BYTES = 2 * 1024 * 1024
_MAX_COLLECTION_BYTES = 128 * 1024
_MAX_RECORDS_PER_CAPABILITY = 50
_MAX_RAW_FIELD_BYTES = 2 * 1024
_TRUNCATION_MARKER = "…（内容已截断）"

_RECORD_FIELDS: dict[type, tuple[tuple[str, str], ...]] = {
    RegistrationRecord: (
        ("法定代表人", "legal_representative"),
        ("注册资本", "registered_capital"),
        ("成立日期", "established_on"),
        ("登记状态", "registration_status"),
        ("注册地址", "registered_address"),
        ("经营范围", "business_scope"),
    ),
    ShareholderRecord: (
        ("股东名称", "shareholder_name"),
        ("股东类型", "shareholder_type"),
        ("持股比例", "ownership_ratio"),
        ("认缴出资额", "subscribed_amount"),
        ("认缴日期", "subscribed_on"),
    ),
    CompanyChangeRecord: (
        ("变更事项", "item"),
        ("变更前", "before"),
        ("变更后", "after"),
        ("变更日期", "changed_on"),
    ),
    JudicialCaseRecord: (
        ("案号", "case_number"),
        ("案由", "cause"),
        ("法院", "court"),
        ("立案日期", "filed_on"),
        ("原告", "plaintiffs"),
        ("被告", "defendants"),
        ("第三人", "third_parties"),
        ("涉案金额", "amount"),
        ("摘要", "summary"),
    ),
    EnforcementRecord: (
        ("案号", "case_number"),
        ("法院", "court"),
        ("立案日期", "filed_on"),
        ("执行金额", "amount"),
        ("执行状态", "status_text"),
    ),
    DishonestRecord: (
        ("案号", "case_number"),
        ("法院", "court"),
        ("失信行为", "conduct"),
        ("履行状态", "performance_status"),
        ("发布日期", "published_on"),
    ),
    HighConsumptionRestriction: (
        ("案号", "case_number"),
        ("申请人", "applicant"),
        ("被限制主体", "restricted_subject"),
        ("关联法定代表人", "related_legal_representative"),
        ("立案日期", "filed_on"),
    ),
    BankruptcyRecord: (
        ("案号", "case_number"),
        ("申请人", "applicant"),
        ("被申请人", "respondent"),
        ("法院", "court"),
        ("发布日期", "published_on"),
    ),
    SeriousViolationRecord: (
        ("列入原因", "reason"),
        ("列入日期", "listed_on"),
        ("决定机关", "authority"),
        ("状态", "status_text"),
    ),
}


def _escape_text(value: str) -> str:
    """同时阻断原始 HTML 与 Markdown 链接、格式和表格注入。"""
    escaped = html.escape(value, quote=False)
    for character in (
        "\\",
        "`",
        "*",
        "_",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        "#",
        "|",
        ">",
    ):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _truncate_raw_text(value: str) -> str:
    """按 UTF-8 字节截断字段，并为用户保留明确的完整性提示。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= _MAX_RAW_FIELD_BYTES:
        return value
    marker_size = len(_TRUNCATION_MARKER.encode("utf-8"))
    prefix = encoded[: _MAX_RAW_FIELD_BYTES - marker_size].decode(
        "utf-8", errors="ignore"
    )
    return f"{prefix}{_TRUNCATION_MARKER}"


def _format_value(value: object) -> str:
    if value is None or value == "" or value == []:
        return "未披露"
    if isinstance(value, list):
        raw_value = "、".join(str(item) for item in sorted(value))
    else:
        raw_value = str(value)
    return _escape_text(_truncate_raw_text(raw_value))


def _format_time(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.strftime("%Y-%m-%d %H:%M:%S UTC")


def _record_sort_key(record: EvidenceRecord) -> str:
    """只用展示字段的有界前缀排序，避免大字段再次放大内存。"""
    facts: list[str] = []
    for _label, field_name in _RECORD_FIELDS[type(record)]:
        value = getattr(record, field_name)
        if isinstance(value, list):
            raw_value = "、".join(str(item) for item in sorted(value))
        else:
            raw_value = "" if value is None else str(value)
        facts.append(_truncate_raw_text(raw_value))
    return json.dumps(facts, ensure_ascii=False, separators=(",", ":"))


def _render_record(record: EvidenceRecord, number: int) -> list[str]:
    lines = [f"#### 记录 {number}"]
    for label, field_name in _RECORD_FIELDS[type(record)]:
        lines.append(f"- **{label}：** {_format_value(getattr(record, field_name))}")
    if record.source.data_updated_at:
        lines.append(
            f"- **数据更新时间：** {_format_time(record.source.data_updated_at)}"
        )
    return lines


def _encoded_lines_size(lines: list[str]) -> int:
    return len("\n".join(lines).encode("utf-8"))


def _collection_status_text(collection: EvidenceCollection) -> str:
    count = len(collection.records)
    if collection.status == CollectionStatus.SUCCEEDED_WITH_RECORDS:
        return f"查询成功（{count} 条）"
    if collection.status == CollectionStatus.PARTIAL:
        return f"部分成功（{count} 条已验证）"
    return _STATUS_TEXT[collection.status]


def _render_collection(collection: EvidenceCollection) -> list[str]:
    lines = [
        f"### {_CAPABILITY_TITLES[collection.capability]}",
        f"- **状态：** {_collection_status_text(collection)}",
    ]
    if collection.reason_code:
        lines.append(
            f"- **说明：** {_REASON_TEXT.get(collection.reason_code, '未提供更多信息')}"
        )
    if collection.source:
        service_name = (
            "工商数据服务"
            if collection.source.server == "qcc-company"
            else "风险数据服务"
        )
        lines.extend(
            (
                f"- **来源：** 企查查官方 MCP（{service_name}）",
                f"- **查询时间：** {_format_time(collection.source.queried_at)}",
                f"- **缓存命中：** {'是' if collection.source.cache_hit else '否'}",
            )
        )
    # Provider 最多可返回 1000 条大记录。先固定展示窗口，再对窗口内的
    # 有界字段排序，防止为最终不会展示的数据消耗同步 CPU 和内存。
    records = sorted(
        collection.records[:_MAX_RECORDS_PER_CAPABILITY],
        key=_record_sort_key,
    )
    total_records = len(collection.records)
    rendered_count = 0
    for record in records:
        next_count = rendered_count + 1
        candidate = [*lines, "", *_render_record(record, next_count)]
        if next_count < total_records:
            candidate.append(
                "- **展示范围：** "
                f"仅展示前 {next_count} 条，共 {total_records} 条；超出部分未写入报告。"
            )
        if _encoded_lines_size(candidate) > _MAX_COLLECTION_BYTES:
            break
        lines = candidate[:-1] if next_count < total_records else candidate
        rendered_count = next_count
    if rendered_count < total_records:
        lines.append(
            "- **展示范围：** "
            f"仅展示前 {rendered_count} 条，共 {total_records} 条；超出部分未写入报告。"
        )
    return lines


def render_professional_evidence_markdown(
    evidence: ProfessionalEvidence,
) -> str:
    """按固定能力和字段顺序生成不经 LLM 改写的专业数据附录。"""
    identity = evidence.identity
    lines = [
        "## 工商与司法专业数据",
        "",
        (
            "> 本章节由已校验的结构化数据确定性生成，未经过大语言模型改写；"
            "内容仅供调研参考，不构成法律、征信、投资或信贷意见；"
            "司法执行状态请以[中国执行信息公开网](https://zxgk.court.gov.cn/)"
            "的人工核验结果为准。"
        ),
        "",
        f"- **规范主体：** {_format_value(identity.canonical_name)}",
        f"- **统一社会信用代码：** {_format_value(identity.credit_code)}",
        f"- **主体登记状态：** {_format_value(identity.registration_status)}",
        f"- **主体地区：** {_format_value(identity.region)}",
        f"- **生成时间：** {_format_time(evidence.generated_at)}",
    ]
    for capability in DATA_CAPABILITIES:
        lines.extend(("", *_render_collection(evidence.collections[capability])))
    rendered = "\n".join(lines).strip()
    if len(rendered.encode("utf-8")) > MAX_PROFESSIONAL_APPENDIX_BYTES:
        raise ValueError("专业数据附录超过固定字节预算")
    return rendered
