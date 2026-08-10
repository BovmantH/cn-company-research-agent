"""专业企业数据的稳定领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import DATA_CAPABILITIES


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def reject_control_characters_in_text(self) -> "StrictModel":
        """拒绝可能破坏日志、SSE 或确定性报告结构的控制字符。"""
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            values = value if isinstance(value, list) else [value]
            if any(
                isinstance(item, str)
                and any(ord(char) < 32 or ord(char) == 127 for char in item)
                for item in values
            ):
                raise ValueError(f"{field_name} 不得包含控制字符")
        return self


class CollectionStatus(StrEnum):
    SUCCEEDED_WITH_RECORDS = "succeeded_with_records"
    SUCCEEDED_EMPTY = "succeeded_empty"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_REQUESTED = "not_requested"
    UNAVAILABLE = "unavailable"
    BUDGET_BLOCKED = "budget_blocked"
    IDENTITY_UNCONFIRMED = "identity_unconfirmed"


class ResolveKind(StrEnum):
    EXACT = "exact"
    CANDIDATES = "candidates"
    NOT_FOUND = "not_found"
    BLOCKED = "blocked"


class CompanyIdentity(StrictModel):
    canonical_name: str = Field(min_length=1, max_length=200)
    credit_code: str = Field(min_length=2, max_length=32)
    registration_status: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=120)
    provider_subject_id: str | None = Field(default=None, max_length=128)
    match_method: Literal["exact", "user_selected"] = "exact"
    original_query: str = Field(min_length=1, max_length=200)
    resolved_at: datetime = Field(default_factory=utc_now)
    provider: Literal["qcc_mcp"] = "qcc_mcp"

    @field_validator("canonical_name", "original_query", "provider_subject_id")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(
            ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise ValueError("主体字段不得包含控制字符")
        return value

    @field_validator("credit_code")
    @classmethod
    def validate_credit_code(cls, value: str) -> str:
        normalized = value.upper()
        allowed = frozenset("0123456789ABCDEFGHJKLMNPQRTUWXY")
        if len(normalized) != 18 or any(char not in allowed for char in normalized):
            raise ValueError("统一社会信用代码格式不合法")
        return normalized

    @field_validator("resolved_at")
    @classmethod
    def require_aware_resolved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("resolved_at 必须包含时区")
        return value


class SourceMetadata(StrictModel):
    provider: Literal["qcc_mcp"] = "qcc_mcp"
    server: Literal["qcc-company", "qcc-risk"]
    capability: str = Field(min_length=1, max_length=80)
    queried_subject: str = Field(min_length=1, max_length=200)
    queried_at: datetime = Field(default_factory=utc_now)
    record_id: str | None = Field(default=None, max_length=256)
    data_updated_at: datetime | None = None
    cache_hit: bool = False
    status: CollectionStatus

    @field_validator("queried_at", "data_updated_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("来源时间必须包含时区")
        return value


class RegistrationRecord(StrictModel):
    record_type: Literal["company_registration"] = "company_registration"
    legal_representative: str | None = Field(default=None, max_length=300)
    registered_capital: str | None = Field(default=None, max_length=100)
    established_on: str | None = Field(default=None, max_length=50)
    registration_status: str | None = Field(default=None, max_length=100)
    registered_address: str | None = Field(default=None, max_length=1_000)
    business_scope: str | None = Field(default=None, max_length=20_000)
    source: SourceMetadata


class ShareholderRecord(StrictModel):
    record_type: Literal["shareholder"] = "shareholder"
    shareholder_name: str = Field(min_length=1, max_length=300)
    shareholder_type: str | None = Field(default=None, max_length=100)
    ownership_ratio: str | None = Field(default=None, max_length=100)
    subscribed_amount: str | None = Field(default=None, max_length=100)
    subscribed_on: str | None = Field(default=None, max_length=50)
    source: SourceMetadata


class CompanyChangeRecord(StrictModel):
    record_type: Literal["company_change"] = "company_change"
    item: str = Field(min_length=1, max_length=300)
    before: str | None = Field(default=None, max_length=20_000)
    after: str | None = Field(default=None, max_length=20_000)
    changed_on: str | None = Field(default=None, max_length=50)
    source: SourceMetadata


class JudicialCaseRecord(StrictModel):
    record_type: Literal["judicial_case"] = "judicial_case"
    case_number: str | None = Field(default=None, max_length=200)
    cause: str | None = Field(default=None, max_length=300)
    court: str | None = Field(default=None, max_length=300)
    filed_on: str | None = Field(default=None, max_length=50)
    plaintiffs: list[Annotated[str, Field(max_length=300)]] = Field(
        default_factory=list, max_length=200
    )
    defendants: list[Annotated[str, Field(max_length=300)]] = Field(
        default_factory=list, max_length=200
    )
    third_parties: list[Annotated[str, Field(max_length=300)]] = Field(
        default_factory=list, max_length=200
    )
    amount: str | None = Field(default=None, max_length=100)
    summary: str | None = Field(default=None, max_length=20_000)
    source: SourceMetadata


class EnforcementRecord(StrictModel):
    record_type: Literal["enforcement"] = "enforcement"
    case_number: str | None = Field(default=None, max_length=200)
    court: str | None = Field(default=None, max_length=300)
    filed_on: str | None = Field(default=None, max_length=50)
    amount: str | None = Field(default=None, max_length=100)
    status_text: str | None = Field(default=None, max_length=300)
    source: SourceMetadata


class DishonestRecord(StrictModel):
    record_type: Literal["dishonest"] = "dishonest"
    case_number: str | None = Field(default=None, max_length=200)
    court: str | None = Field(default=None, max_length=300)
    conduct: str | None = Field(default=None, max_length=20_000)
    performance_status: str | None = Field(default=None, max_length=300)
    published_on: str | None = Field(default=None, max_length=50)
    source: SourceMetadata


class HighConsumptionRestriction(StrictModel):
    record_type: Literal["high_consumption"] = "high_consumption"
    case_number: str | None = Field(default=None, max_length=200)
    applicant: str | None = Field(default=None, max_length=300)
    restricted_subject: str | None = Field(default=None, max_length=300)
    related_legal_representative: str | None = Field(default=None, max_length=300)
    filed_on: str | None = Field(default=None, max_length=50)
    source: SourceMetadata


class BankruptcyRecord(StrictModel):
    record_type: Literal["bankruptcy"] = "bankruptcy"
    case_number: str | None = Field(default=None, max_length=200)
    applicant: str | None = Field(default=None, max_length=300)
    respondent: str | None = Field(default=None, max_length=300)
    court: str | None = Field(default=None, max_length=300)
    published_on: str | None = Field(default=None, max_length=50)
    source: SourceMetadata


class SeriousViolationRecord(StrictModel):
    record_type: Literal["serious_violation"] = "serious_violation"
    reason: str | None = Field(default=None, max_length=20_000)
    listed_on: str | None = Field(default=None, max_length=50)
    authority: str | None = Field(default=None, max_length=300)
    status_text: str | None = Field(default=None, max_length=300)
    source: SourceMetadata


EvidenceRecord = Annotated[
    RegistrationRecord
    | ShareholderRecord
    | CompanyChangeRecord
    | JudicialCaseRecord
    | EnforcementRecord
    | DishonestRecord
    | HighConsumptionRestriction
    | BankruptcyRecord
    | SeriousViolationRecord,
    Field(discriminator="record_type"),
]


CAPABILITY_CONTRACTS: dict[str, tuple[str, frozenset[str]]] = {
    "company.registration": ("qcc-company", frozenset({"company_registration"})),
    "company.shareholders": ("qcc-company", frozenset({"shareholder"})),
    "company.changes": ("qcc-company", frozenset({"company_change"})),
    "risk.case_filings": ("qcc-risk", frozenset({"judicial_case"})),
    "risk.judicial_documents": ("qcc-risk", frozenset({"judicial_case"})),
    "risk.enforcement": ("qcc-risk", frozenset({"enforcement"})),
    "risk.dishonest": ("qcc-risk", frozenset({"dishonest"})),
    "risk.high_consumption": ("qcc-risk", frozenset({"high_consumption"})),
    "risk.bankruptcy": ("qcc-risk", frozenset({"bankruptcy"})),
    "risk.serious_violation": ("qcc-risk", frozenset({"serious_violation"})),
}


class EvidenceCollection(StrictModel):
    capability: str = Field(min_length=1, max_length=80)
    status: CollectionStatus
    records: list[EvidenceRecord] = Field(default_factory=list, max_length=1_000)
    source: SourceMetadata | None = None
    reason_code: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]{0,79}$",
    )

    @model_validator(mode="after")
    def enforce_status_semantics(self) -> "EvidenceCollection":
        """保证状态、记录类型和来源元数据符合该逻辑能力的固定契约。"""
        contract = CAPABILITY_CONTRACTS.get(self.capability)
        if contract is None:
            raise ValueError(f"未知逻辑能力: {self.capability}")
        if self.status == CollectionStatus.SUCCEEDED_WITH_RECORDS and not self.records:
            raise ValueError("succeeded_with_records 必须包含至少一条记录")
        if self.status == CollectionStatus.SUCCEEDED_EMPTY and self.records:
            raise ValueError("succeeded_empty 不得包含记录")
        if self.status == CollectionStatus.PARTIAL and not self.records:
            raise ValueError("partial 必须包含至少一条已验证记录")
        if (
            self.status
            in {
                CollectionStatus.FAILED,
                CollectionStatus.NOT_REQUESTED,
                CollectionStatus.UNAVAILABLE,
                CollectionStatus.BUDGET_BLOCKED,
                CollectionStatus.IDENTITY_UNCONFIRMED,
            }
            and self.records
        ):
            raise ValueError(f"{self.status} 状态不得携带事实记录")
        expected_server, allowed_record_types = contract
        provider_statuses = {
            CollectionStatus.SUCCEEDED_WITH_RECORDS,
            CollectionStatus.SUCCEEDED_EMPTY,
            CollectionStatus.PARTIAL,
            CollectionStatus.FAILED,
        }
        if self.status in provider_statuses and self.source is None:
            raise ValueError("数据提供方调用结果必须包含集合级来源元数据")
        non_success_statuses = set(CollectionStatus) - {
            CollectionStatus.SUCCEEDED_WITH_RECORDS,
            CollectionStatus.SUCCEEDED_EMPTY,
        }
        if self.status in non_success_statuses and not self.reason_code:
            raise ValueError(f"{self.status} 必须包含稳定原因码")
        if self.status not in non_success_statuses and self.reason_code is not None:
            raise ValueError("成功状态不得包含失败原因码")
        if self.status not in provider_statuses and self.source is not None:
            raise ValueError("未调用 Provider 的状态不得包含来源元数据")
        if self.source is not None:
            if self.source.capability != self.capability:
                raise ValueError("集合来源 capability 与集合不一致")
            if self.source.server != expected_server:
                raise ValueError("集合来源 server 与逻辑能力不一致")
            if self.source.status != self.status:
                raise ValueError("集合来源 status 与集合不一致")
            if self.source.record_id is not None:
                raise ValueError("集合级来源不得包含记录 ID")
        for record in self.records:
            if record.record_type not in allowed_record_types:
                raise ValueError(
                    f"{self.capability} 不允许记录类型 {record.record_type}"
                )
            if record.source.capability != self.capability:
                raise ValueError("记录来源 capability 与集合不一致")
            if record.source.server != expected_server:
                raise ValueError("记录来源 server 与逻辑能力不一致")
            if record.source.status != self.status:
                raise ValueError("记录来源 status 与集合不一致")
            if self.source is not None and (
                record.source.queried_subject != self.source.queried_subject
                or record.source.queried_at != self.source.queried_at
                or record.source.cache_hit != self.source.cache_hit
            ):
                raise ValueError("记录来源与集合级来源元数据不一致")
        return self


class ProfessionalEvidence(StrictModel):
    identity: CompanyIdentity
    collections: dict[str, EvidenceCollection] = Field(default_factory=dict)
    provider: Literal["qcc_mcp"] = "qcc_mcp"
    generated_at: datetime = Field(default_factory=utc_now)
    schema_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def require_complete_coverage(self) -> "ProfessionalEvidence":
        """要求每个必需能力都有明确结果，包括失败、空结果和未请求状态。"""
        expected = set(DATA_CAPABILITIES)
        if set(self.collections) != expected:
            missing = sorted(expected - set(self.collections))
            extra = sorted(set(self.collections) - expected)
            raise ValueError(f"专业数据覆盖不完整: missing={missing}, extra={extra}")
        for key, collection in self.collections.items():
            if key != collection.capability:
                raise ValueError("collections key 必须与 collection.capability 一致")
            if (
                collection.source is not None
                and collection.source.queried_subject != self.identity.credit_code
            ):
                raise ValueError("集合查询主体必须是已确认企业的统一社会信用代码")
        return self


class ResolveResult(StrictModel):
    kind: ResolveKind
    identities: list[CompanyIdentity] = Field(default_factory=list, max_length=5)
    reason_code: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def enforce_resolve_shape(self) -> "ResolveResult":
        """限制不同解析结果可携带的主体数量，并拒绝重复候选。"""
        if self.kind == ResolveKind.EXACT and len(self.identities) != 1:
            raise ValueError("exact 必须且只能返回一个主体")
        if self.kind == ResolveKind.CANDIDATES and not 1 < len(self.identities) <= 5:
            raise ValueError("candidates 必须返回 2 至 5 个主体")
        if (
            self.kind in {ResolveKind.NOT_FOUND, ResolveKind.BLOCKED}
            and self.identities
        ):
            raise ValueError(f"{self.kind} 不得返回主体")
        codes = [identity.credit_code for identity in self.identities]
        if len(codes) != len(set(codes)):
            raise ValueError("候选主体的统一社会信用代码不得重复")
        return self
