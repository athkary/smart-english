"""Password hashing, JWT access tokens and opaque refresh tokens.

Uses only the standard library (hashlib.scrypt, secrets, hmac) plus PyJWT.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

# scrypt parameters (OWASP-recommended baseline: N=2^17, r=8, p=1 ≈ 128 MiB)
_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 256 * 1024 * 1024
_SCHEME = "scrypt"

MIN_PASSWORD_LENGTH = 10


class PasswordPolicyError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.lower() in {"password123", "1234567890", "qwertyuiop", "0123456789"}:
        raise PasswordPolicyError("Password is too common")


def hash_password(password: str, *, n: int = _SCRYPT_N) -> str:
    """Return a self-describing hash: scrypt$N$r$p$salt$hash."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=_SCRYPT_R, p=_SCRYPT_P,
                            dklen=_SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM)
    return f"{_SCHEME}${n}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != _SCHEME:
            return False
        digest = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(_unb64(expected)), maxmem=_SCRYPT_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, _unb64(expected))


# ---------------- Tokens ----------------
ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenClaims:
    subject: uuid.UUID
    role: str            # 'parent' | 'student' | 'admin'
    scope: str           # e.g. 'parent' or 'student:learn'
    parent_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None


class InvalidTokenError(Exception):
    pass


def create_access_token(claims: TokenClaims, *, secret: str, issuer: str, ttl_seconds: int,
                        now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(claims.subject),
        "role": claims.role,
        "scope": claims.scope,
        "iss": issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if claims.parent_id:
        payload["pid"] = str(claims.parent_id)
    if claims.student_id:
        payload["sid"] = str(claims.student_id)
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str, issuer: str) -> TokenClaims:
    try:
        data = jwt.decode(token, secret, algorithms=[ALGORITHM], issuer=issuer,
                          options={"require": ["sub", "exp", "iat", "iss", "role", "scope"]})
        return TokenClaims(
            subject=uuid.UUID(data["sub"]),
            role=data["role"],
            scope=data["scope"],
            parent_id=uuid.UUID(data["pid"]) if data.get("pid") else None,
            student_id=uuid.UUID(data["sid"]) if data.get("sid") else None,
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def new_refresh_token() -> tuple[str, str]:
    """Return (token_for_client, sha256_hash_for_db). Only the hash is stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
