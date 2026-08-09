from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.company_intelligence.ledger import InMemoryUsageLedger
from backend.services.company_intelligence.models import CompanyIdentity
from backend.services.company_intelligence.tokens import (
    ResolutionTokenError,
    ResolutionTokenService,
    requester_fingerprint,
)


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        canonical_name="示例科技有限公司",
        credit_code="91320594MA1N00000X",
        original_query="示例科技",
    )


def test_token_is_bound_to_requester_and_single_use() -> None:
    ledger = InMemoryUsageLedger()
    service = ResolutionTokenService("s" * 32, ledger)
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    token = service.issue(_identity(), requester)

    claims = service.consume(token, requester)
    assert claims.credit_code == "91320594MA1N00000X"
    with pytest.raises(ResolutionTokenError, match="token_already_used"):
        service.consume(token, requester)


def test_verify_is_read_only_and_does_not_consume_token() -> None:
    ledger = InMemoryUsageLedger()
    service = ResolutionTokenService("s" * 32, ledger)
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    token = service.issue(_identity(), requester)

    first = service.verify(token, requester)
    second = service.verify(token, requester)

    assert first == second
    assert service.consume(token, requester) == first
    with pytest.raises(ResolutionTokenError, match="token_already_used"):
        service.consume(token, requester)


def test_signed_claims_preserve_identity_match_method() -> None:
    service = ResolutionTokenService("s" * 32, InMemoryUsageLedger())
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    identity = _identity().model_copy(update={"match_method": "user_selected"})

    claims = service.verify(service.issue(identity, requester), requester)

    assert claims.match_method == "user_selected"


def test_tampering_is_rejected() -> None:
    service = ResolutionTokenService("s" * 32, InMemoryUsageLedger())
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    token = service.issue(_identity(), requester)
    payload, signature = token.split(".")
    tampered = ("A" if payload[0] != "A" else "B") + payload[1:] + "." + signature
    with pytest.raises(ResolutionTokenError, match="invalid_signature"):
        service.consume(tampered, requester)


def test_expired_token_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    service = ResolutionTokenService("s" * 32, InMemoryUsageLedger(), ttl_seconds=5)
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    token = service.issue(_identity(), requester, now=now)
    with pytest.raises(ResolutionTokenError, match="expired_token"):
        service.consume(token, requester, now=now + timedelta(seconds=6))


def test_requester_mismatch_is_rejected_without_consuming_token() -> None:
    service = ResolutionTokenService("s" * 32, InMemoryUsageLedger())
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    other = requester_fingerprint("127.0.0.2", "s" * 32)
    token = service.issue(_identity(), requester)
    with pytest.raises(ResolutionTokenError, match="requester_mismatch"):
        service.consume(token, other)
    assert service.consume(token, requester).credit_code == _identity().credit_code


def test_concurrent_token_consumption_allows_exactly_one_winner() -> None:
    service = ResolutionTokenService("s" * 32, InMemoryUsageLedger())
    requester = requester_fingerprint("127.0.0.1", "s" * 32)
    token = service.issue(_identity(), requester)

    def consume() -> bool:
        try:
            service.consume(token, requester)
        except ResolutionTokenError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: consume(), range(8)))
    assert sum(outcomes) == 1
