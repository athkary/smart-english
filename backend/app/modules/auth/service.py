"""Parent accounts, login, token rotation, child device sessions."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

import re

from pydantic import AfterValidator, BaseModel, Field, field_validator
from typing import Annotated

from app.core.config import Settings
from app.core.http import AppError
from app.core.security import (PasswordPolicyError, TokenClaims, create_access_token, hash_password,
                               hash_refresh_token, new_refresh_token, validate_password, verify_password)
from app.db.database import Database, UniqueViolation

CONSENT_VERSION = "2026-11"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("invalid email")
    return v


Email = Annotated[str, AfterValidator(_email)]


# ---------- request models ----------
class SignupIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    preferred_language: Literal["ar", "en"] = "ar"
    consent_version: str = Field(min_length=1, max_length=20)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty")
        return v


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class StudentSessionIn(BaseModel):
    student_id: uuid.UUID


# ---------- results ----------
@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int
    role: str

    def as_dict(self) -> dict:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token,
                "token_type": "bearer", "expires_in": self.expires_in, "role": self.role}


def _invalid_credentials() -> AppError:
    return AppError("invalid_credentials", "Email or password is incorrect",
                    "البريد الإلكتروني أو كلمة المرور غير صحيحة", 401)


def _invalid_refresh() -> AppError:
    return AppError("invalid_refresh_token", "Session expired, please sign in again",
                    "انتهت الجلسة، سجّل الدخول من جديد", 401)


class AuthService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db, self.s = db, settings
        # Constant-time-ish behaviour for unknown emails: verify against a real hash.
        self._dummy_hash = hash_password(uuid.uuid4().hex, n=settings.scrypt_n)

    # ----- token issuing -----
    async def _issue(self, claims: TokenClaims, user_id: uuid.UUID, device_label: str,
                     family_id: uuid.UUID | None = None) -> Tokens:
        refresh, digest = new_refresh_token()
        await self.db.execute(
            "INSERT INTO refresh_tokens(user_id, token_hash, family_id, device_label, expires_at) "
            "VALUES ($1, $2, COALESCE($3::uuid, gen_random_uuid()), $4, now() + make_interval(days => $5))",
            user_id, digest, family_id, device_label, self.s.refresh_token_ttl_days)
        return Tokens(self._access(claims), refresh, self.s.access_token_ttl_seconds, claims.role)

    def _access(self, claims: TokenClaims) -> str:
        return create_access_token(claims, secret=self.s.jwt_secret.get_secret_value(),
                                   issuer=self.s.jwt_issuer, ttl_seconds=self.s.access_token_ttl_seconds)

    # ----- parent signup / login -----
    async def signup(self, data: SignupIn) -> tuple[Tokens, dict]:
        if data.consent_version != CONSENT_VERSION:
            raise AppError("consent_required", "Please accept the current privacy terms",
                           "يرجى الموافقة على شروط الخصوصية الحالية", 422)
        try:
            validate_password(data.password)
        except PasswordPolicyError:
            raise AppError("weak_password", "Password must be at least 10 characters and not common",
                           "كلمة المرور يجب أن تكون 10 أحرف على الأقل وغير شائعة", 422) from None
        pw_hash = hash_password(data.password, n=self.s.scrypt_n)
        try:
            row = await self.db.fetchrow(
                """
                WITH u AS (INSERT INTO users(role, email, password_hash) VALUES ('parent', $1::text::citext, $2) RETURNING id),
                p AS (INSERT INTO parents(user_id, display_name, preferred_language, consent_accepted_at, consent_version)
                      SELECT id, $3, $4::ui_language, now(), $5 FROM u RETURNING id, user_id),
                st AS (INSERT INTO parent_settings(parent_id) SELECT id FROM p),
                sub AS (INSERT INTO subscriptions(parent_id, plan, state) SELECT id, 'free', 'active' FROM p),
                a AS (INSERT INTO audit_events(actor_user_id, action, target_type, target_id)
                      SELECT user_id, 'parent.signup', 'parent', id FROM p)
                SELECT p.id AS parent_id, p.user_id FROM p
                """,
                data.email, pw_hash, data.display_name, data.preferred_language, data.consent_version)
        except UniqueViolation:
            raise AppError("email_taken", "An account with this email already exists",
                           "يوجد حساب مسجّل بهذا البريد الإلكتروني", 409) from None
        assert row is not None
        claims = TokenClaims(subject=row["user_id"], role="parent", scope="parent", parent_id=row["parent_id"])
        tokens = await self._issue(claims, row["user_id"], "parent")
        return tokens, {"parent_id": row["parent_id"]}

    async def login(self, data: LoginIn) -> Tokens:
        row = await self.db.fetchrow(
            "SELECT u.id, u.password_hash, u.is_active, p.id AS parent_id FROM users u "
            "JOIN parents p ON p.user_id = u.id WHERE u.email = $1::text::citext AND u.role = 'parent'",
            data.email)
        if row is None:
            verify_password(data.password, self._dummy_hash)
            raise _invalid_credentials()
        if not verify_password(data.password, row["password_hash"]) or not row["is_active"]:
            raise _invalid_credentials()
        await self.db.execute("UPDATE users SET last_login_at = now() WHERE id = $1", row["id"])
        claims = TokenClaims(subject=row["id"], role="parent", scope="parent", parent_id=row["parent_id"])
        return await self._issue(claims, row["id"], "parent")

    # ----- refresh rotation with reuse detection -----
    async def refresh(self, data: RefreshIn) -> Tokens:
        digest = hash_refresh_token(data.refresh_token)
        new_token, new_digest = new_refresh_token()
        row = await self.db.fetchrow(
            """
            WITH old AS (
                UPDATE refresh_tokens SET revoked_at = now()
                WHERE token_hash = $1 AND revoked_at IS NULL AND expires_at > now()
                RETURNING user_id, family_id, device_label),
            ins AS (
                INSERT INTO refresh_tokens(user_id, token_hash, family_id, device_label, expires_at)
                SELECT user_id, $2, family_id, device_label, now() + make_interval(days => $3) FROM old
                RETURNING user_id)
            SELECT u.id AS user_id, u.role::text AS role, u.is_active,
                   p.id AS parent_id, s.id AS student_id, s.parent_id AS student_parent_id
            FROM ins JOIN users u ON u.id = ins.user_id
            LEFT JOIN parents p ON p.user_id = u.id
            LEFT JOIN students s ON s.user_id = u.id
            """,
            digest, new_digest, self.s.refresh_token_ttl_days)
        if row is None:
            # Reuse of an already-rotated token => revoke the whole family (likely theft).
            await self.db.execute(
                "UPDATE refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL AND family_id IN "
                "(SELECT family_id FROM refresh_tokens WHERE token_hash = $1 AND revoked_at IS NOT NULL)",
                digest)
            raise _invalid_refresh()
        if not row["is_active"]:
            raise _invalid_refresh()
        if row["role"] == "parent":
            claims = TokenClaims(subject=row["user_id"], role="parent", scope="parent", parent_id=row["parent_id"])
        else:
            claims = TokenClaims(subject=row["user_id"], role="student", scope="student:learn",
                                 parent_id=row["student_parent_id"], student_id=row["student_id"])
        return Tokens(self._access(claims), new_token, self.s.access_token_ttl_seconds, claims.role)

    async def logout(self, data: RefreshIn) -> None:
        await self.db.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL AND family_id IN "
            "(SELECT family_id FROM refresh_tokens WHERE token_hash = $1)", hash_refresh_token(data.refresh_token))

    # ----- child session on this device (issued by the parent) -----
    async def student_session(self, parent: TokenClaims, data: StudentSessionIn) -> Tokens:
        row = await self.db.fetchrow(
            "SELECT s.id, s.user_id FROM students s WHERE s.id = $1 AND s.parent_id = $2",
            data.student_id, parent.parent_id)
        if row is None:
            raise AppError("not_found", "Not found", "غير موجود", 404)
        claims = TokenClaims(subject=row["user_id"], role="student", scope="student:learn",
                             parent_id=parent.parent_id, student_id=row["id"])
        return await self._issue(claims, row["user_id"], f"student:{row['id']}")
