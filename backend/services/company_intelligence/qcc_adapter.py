"""把 QCC MCP 原始结果归一化为稳定的企业情报领域对象。"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import CompanyIdentity, ResolveKind, ResolveResult


_MISSING = object()
_SUCCESS_STATUSES = frozenset({"200", "ok", "success", "succeeded"})


class QccResponseInvalid(ValueError):
    """上游响应无法在不猜测业务含义的前提下安全归一化。"""


def _first_value(record: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    values = [record[alias] for alias in aliases if alias in record]
    if not values:
        return _MISSING
    if any(value != values[0] for value in values[1:]):
        raise QccResponseInvalid("同一字段的多个别名互相冲突")
    return values[0]


def _string_field(
    record: dict[str, Any],
    aliases: tuple[str, ...],
    *,
    required: bool,
) -> str | None:
    value = _first_value(record, aliases)
    if value is _MISSING or value is None:
        if required:
            raise QccResponseInvalid("缺少必需主体字段")
        return None
    if not isinstance(value, str):
        raise QccResponseInvalid("主体字段类型不兼容")
    normalized = value.strip()
    if not normalized:
        if required:
            raise QccResponseInvalid("必需主体字段为空")
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise QccResponseInvalid("主体字段包含控制字符")
    return normalized


def _is_success_status(value: Any) -> bool:
    if value is True or value == 200:
        return True
    return isinstance(value, str) and value.strip().lower() in _SUCCESS_STATUSES


def _reject_conflicting_aliases(
    record: dict[str, Any], canonical: str, aliases: tuple[str, ...]
) -> None:
    """拒绝已知但未采用的别名与规范字段表达不同事实。"""
    if canonical not in record:
        if any(alias in record for alias in aliases):
            raise QccResponseInvalid("响应只包含未确认的兼容别名")
        return
    canonical_value = record[canonical]
    if any(alias in record and record[alias] != canonical_value for alias in aliases):
        raise QccResponseInvalid("规范字段与兼容别名互相冲突")


def _extract_identity_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """只解析已知结果信封；显式空值表示无结果，未知形状表示失败。"""
    result: Any = payload.get("Result", _MISSING)
    _reject_conflicting_aliases(
        payload, "Result", ("Results", "result", "results", "Data", "data")
    )
    success_flag = _first_value(payload, ("Success", "success"))
    if success_flag is not _MISSING and success_flag is not True:
        raise QccResponseInvalid("上游返回失败状态")

    if result is _MISSING:
        response_code = _first_value(payload, ("Code", "code"))
        if response_code is not _MISSING and not _is_success_status(response_code):
            raise QccResponseInvalid("上游返回失败状态")
        if _first_value(
            payload,
            ("CompanyName", "Name"),
        ) is not _MISSING:
            return [payload]
        raise QccResponseInvalid("缺少明确的结果字段")

    envelope_status = _first_value(payload, ("Status", "status", "Code", "code"))
    if envelope_status is not _MISSING and not _is_success_status(envelope_status):
        raise QccResponseInvalid("上游返回失败状态")

    if result == []:
        return []
    if result is None or result == {}:
        raise QccResponseInvalid("结果为空但未返回明确空列表")
    if isinstance(result, list):
        records = result
    elif isinstance(result, dict):
        _reject_conflicting_aliases(
            result, "Items", ("List", "Records", "items", "list", "records")
        )
        nested: Any = result.get("Items", _MISSING)
        if nested == []:
            records = []
        elif nested is _MISSING:
            records = [result]
        elif nested is None:
            raise QccResponseInvalid("结果列表为空但未返回明确空列表")
        elif isinstance(nested, list):
            records = nested
        else:
            raise QccResponseInvalid("结果列表类型不兼容")
    else:
        raise QccResponseInvalid("结果类型不兼容")

    if not all(isinstance(record, dict) for record in records):
        raise QccResponseInvalid("主体记录必须是对象")
    return records


def _normalize_identity(query: str, record: dict[str, Any]) -> CompanyIdentity:
    _reject_conflicting_aliases(
        record,
        "CreditCode",
        (
            "UnifiedSocialCreditCode",
            "SocialCreditCode",
            "creditCode",
            "credit_code",
        ),
    )
    return CompanyIdentity(
        canonical_name=_string_field(
            record,
            ("CompanyName", "Name"),
            required=True,
        ),
        credit_code=_string_field(
            record,
            ("CreditCode",),
            required=True,
        ),
        registration_status=_string_field(
            record,
            ("RegStatus", "Status"),
            required=False,
        ),
        region=_string_field(
            record,
            ("Province", "Region"),
            required=False,
        ),
        provider_subject_id=_string_field(
            record,
            ("KeyNo", "CompanyId"),
            required=False,
        ),
        original_query=query,
    )


def normalize_identity_response(
    query: str, payload: dict[str, Any]
) -> ResolveResult:
    """将实体识别响应映射为 exact/candidates/not_found/blocked。"""
    try:
        records = _extract_identity_records(payload)
        if not records:
            return ResolveResult(kind=ResolveKind.NOT_FOUND)
        if len(records) > 5:
            raise QccResponseInvalid("主体候选超过上游契约上限")
        identities = [_normalize_identity(query, record) for record in records]
        kind = ResolveKind.EXACT if len(identities) == 1 else ResolveKind.CANDIDATES
        # 候选在此阶段尚未由用户选定；CompanyResolutionService 只会在签发
        # 候选 Token 时把最终身份语义改为 user_selected。
        return ResolveResult(kind=kind, identities=identities)
    except (QccResponseInvalid, ValidationError, ValueError):
        # 仅返回稳定原因码，不把上游 Message、账户信息或原始响应带入业务层。
        return ResolveResult(
            kind=ResolveKind.BLOCKED,
            reason_code="provider_schema_invalid",
        )
