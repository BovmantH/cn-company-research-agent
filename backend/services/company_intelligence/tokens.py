"""主体解析 Token 与请求方匿名标识。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .ledger import UsageLedger
from .models import CompanyIdentity


class ResolutionTokenError(ValueError):
    pass


class ResolutionClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jti: str
    requester_id: str
    canonical_name: str
    credit_code: str
    provider_subject_id: str | None = None
    original_query: str
    iat: int
    exp: int


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def requester_fingerprint(client_ip: str, secret: str) -> str:
    """用部署密钥匿名化请求方，避免账本保存原始客户端 IP。"""
    normalized = client_ip.strip().lower()
    return hmac.new(
        secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class ResolutionTokenService:
    def __init__(self, secret: str, ledger: UsageLedger, *, ttl_seconds: int = 600) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("APP_SIGNING_SECRET 至少需要 32 字节")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._secret = secret.encode("utf-8")
        self._ledger = ledger
        self._ttl_seconds = ttl_seconds

    def issue(
        self,
        identity: CompanyIdentity,
        requester_id: str,
        *,
        now: datetime | None = None,
    ) -> str:
        """签发与请求方绑定的短期主体凭证，避免前端伪造权威主体字段。"""
        issued_at = int((now or datetime.now(timezone.utc)).timestamp())
        claims = ResolutionClaims(
            jti=uuid.uuid4().hex,
            requester_id=requester_id,
            canonical_name=identity.canonical_name,
            credit_code=identity.credit_code,
            provider_subject_id=identity.provider_subject_id,
            original_query=identity.original_query,
            iat=issued_at,
            exp=issued_at + self._ttl_seconds,
        )
        payload = json.dumps(
            claims.model_dump(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        encoded = _b64encode(payload)
        signature = _b64encode(hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(
        self,
        token: str,
        requester_id: str,
        *,
        now: datetime | None = None,
    ) -> ResolutionClaims:
        """只读校验长度、签名、时效和请求方，不改变 Token 使用状态。"""
        if not token or len(token) > 4096:
            raise ResolutionTokenError("invalid_token")
        try:
            encoded, signature = token.split(".", 1)
        except ValueError as exc:
            raise ResolutionTokenError("invalid_token") from exc

        expected = _b64encode(
            hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ResolutionTokenError("invalid_signature")

        try:
            claims = ResolutionClaims.model_validate_json(_b64decode(encoded))
        except (ValueError, ValidationError) as exc:
            raise ResolutionTokenError("invalid_payload") from exc

        current = int((now or datetime.now(timezone.utc)).timestamp())
        if claims.exp <= current:
            raise ResolutionTokenError("expired_token")
        if claims.iat > current + 30:
            raise ResolutionTokenError("invalid_issued_at")
        if not hmac.compare_digest(claims.requester_id, requester_id):
            raise ResolutionTokenError("requester_mismatch")
        return claims

    def consume(
        self,
        token: str,
        requester_id: str,
        *,
        now: datetime | None = None,
    ) -> ResolutionClaims:
        """校验 Token 后在账本中原子标记一次性消费。"""
        claims = self.verify(token, requester_id, now=now)
        if not self._ledger.consume_token(claims.jti, claims.exp):
            raise ResolutionTokenError("token_already_used")
        return claims
