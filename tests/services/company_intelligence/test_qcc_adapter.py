from __future__ import annotations

import pytest

from backend.services.company_intelligence.models import ResolveKind
from backend.services.company_intelligence.qcc_adapter import (
    normalize_identity_response,
)


def _identity(index: int = 0) -> dict[str, str]:
    return {
        "Name": f"示例科技{index}有限公司",
        "CreditCode": f"91320594MA1N0000{index}X",
        "Status": "存续",
        "Province": "江苏省",
        "KeyNo": f"provider-{index}",
    }


def test_normalizes_exact_identity_from_qcc_result_envelope() -> None:
    result = normalize_identity_response(
        "示例科技",
        {"Status": "200", "Message": "查询成功", "Result": _identity()},
    )

    assert result.kind == ResolveKind.EXACT
    assert result.reason_code is None
    assert result.identities[0].model_dump(exclude={"resolved_at"}, mode="json") == {
        "canonical_name": "示例科技0有限公司",
        "credit_code": "91320594MA1N00000X",
        "registration_status": "存续",
        "region": "江苏省",
        "provider_subject_id": "provider-0",
        "match_method": "exact",
        "original_query": "示例科技",
        "provider": "qcc_mcp",
    }


def test_normalizes_two_to_five_candidates() -> None:
    result = normalize_identity_response(
        "示例",
        {"Result": [_identity(1), _identity(2), _identity(3)]},
    )

    assert result.kind == ResolveKind.CANDIDATES
    assert [item.credit_code for item in result.identities] == [
        "91320594MA1N00001X",
        "91320594MA1N00002X",
        "91320594MA1N00003X",
    ]


def test_explicit_empty_list_is_not_found() -> None:
    result = normalize_identity_response("不存在的企业", {"Result": []})

    assert result.kind == ResolveKind.NOT_FOUND
    assert result.identities == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"Result": None},
        {"Result": {}},
        {"Status": "500", "Message": "Authorization: Bearer secret", "Result": []},
        {"Result": [{"Name": "缺少信用代码"}]},
        {"Result": [_identity(index) for index in range(6)]},
        {"Result": [_identity(), _identity()]},
        {"Result": [_identity() | {"Name": "异常\n企业"}]},
        {"Code": 500, **_identity()},
        {"Success": False, **_identity()},
        {**_identity(), "data": [_identity(1)]},
        {"Result": [], "data": [_identity()]},
        {"Result": _identity() | {"Records": [_identity(1)]}},
        {"Result": [_identity() | {"CompanyName": "冲突名称有限公司"}]},
        {"Result": [_identity() | {"RegStatus": "注销", "Status": "存续"}]},
        {"Result": [_identity() | {"UnifiedSocialCreditCode": "91110000MA0000000A"}]},
        {"Result": "not-json-records"},
        {"Result": ["not-an-object"]},
    ],
)
def test_ambiguous_or_invalid_response_fails_closed(
    payload: dict[str, object],
) -> None:
    result = normalize_identity_response("示例科技", payload)

    assert result.kind == ResolveKind.BLOCKED
    assert result.identities == []
    assert result.reason_code == "provider_schema_invalid"
    assert "secret" not in result.reason_code


def test_direct_identity_object_is_supported_without_treating_company_status_as_error() -> (
    None
):
    result = normalize_identity_response("示例科技", _identity())

    assert result.kind == ResolveKind.EXACT
    assert result.identities[0].registration_status == "存续"
