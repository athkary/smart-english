"""Parent profile, children (students), parent settings, PIN gate, export & deletion.

Every query on a student filters by the caller's parent_id (no IDOR): another family's
student is reported as 404, never 403, so its existence is not revealed.
"""
from __future__ import annotations

import uuid
from datetime import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import Settings
from app.core.http import AppError, not_found
from app.core.security import TokenClaims, hash_password, verify_password
from app.db.database import Database

TeacherCode = Literal["emma", "daniel"]  # Alex unlocks with A2 content
Level = Literal["A0", "A1", "A2"]
AVATARS = ("lion", "cat", "owl", "fox", "panda", "rabbit", "turtle", "penguin")
PIN_MAX_ATTEMPTS = 5
PIN_LOCK_MINUTES = 5


def _clean_name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("empty")
    return v


class StudentCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)
    birth_year: int | None = Field(default=None, ge=2005, le=2026)
    avatar_code: str = "lion"
    preferred_teacher: TeacherCode = "emma"

    @field_validator("nickname")
    @classmethod
    def _n(cls, v: str) -> str:
        return _clean_name(v)

    @field_validator("avatar_code")
    @classmethod
    def _avatar(cls, v: str) -> str:
        if v not in AVATARS:
            raise ValueError("unknown avatar")
        return v


class StudentUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=40)
    birth_year: int | None = Field(default=None, ge=2005, le=2026)
    avatar_code: str | None = None
    preferred_teacher: TeacherCode | None = None
    show_arabic: bool | None = None
    daily_goal_minutes: int | None = Field(default=None, ge=5, le=120)
    current_level: Level | None = None

    @field_validator("nickname")
    @classmethod
    def _n(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)

    @field_validator("avatar_code")
    @classmethod
    def _avatar(cls, v: str | None) -> str | None:
        if v is not None and v not in AVATARS:
            raise ValueError("unknown avatar")
        return v


class StudentPreferences(BaseModel):
    preferred_teacher: TeacherCode | None = None
    show_arabic: bool | None = None


class SettingsIn(BaseModel):
    daily_limit_minutes: int | None = Field(default=None, ge=5, le=240)
    allowed_start_time: time | None = None
    allowed_end_time: time | None = None
    free_conversation_enabled: bool = True
    role_play_enabled: bool = True
    store_transcripts: bool = True
    transcript_retention_days: int = Field(default=90, ge=0, le=365)
    weekly_report_email: bool = True

    @model_validator(mode="after")
    def _window(self) -> "SettingsIn":
        if (self.allowed_start_time is None) != (self.allowed_end_time is None):
            raise ValueError("start and end time must be set together")
        return self


class ParentUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    preferred_language: Literal["ar", "en"] | None = None


class PinSet(BaseModel):
    pin: str = Field(pattern=r"^\d{4,6}$")
    password: str = Field(min_length=1, max_length=200)


class PinVerify(BaseModel):
    pin: str = Field(pattern=r"^\d{4,6}$")


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm: Literal["DELETE"]


_STUDENT_COLS = """s.id, s.nickname, s.birth_year, s.avatar_code, s.current_level::text AS current_level,
    t.code AS preferred_teacher, s.show_arabic, s.daily_goal_minutes, s.total_points, s.streak_days,
    s.last_active_on, s.created_at"""


class ProfileService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db, self.s = db, settings

    # ---------- parent ----------
    async def get_parent(self, me: TokenClaims) -> dict:
        row = await self.db.fetchrow(
            """SELECT p.id, u.email::text AS email, p.display_name, p.preferred_language::text AS preferred_language,
                      (p.parent_pin_hash IS NOT NULL) AS has_pin, p.consent_version, p.created_at,
                      (SELECT count(*) FROM students s WHERE s.parent_id = p.id) AS student_count,
                      (SELECT plan::text FROM subscriptions WHERE parent_id = p.id ORDER BY created_at LIMIT 1) AS plan
               FROM parents p JOIN users u ON u.id = p.user_id WHERE p.id = $1""", me.parent_id)
        if row is None:
            raise not_found()
        row["max_students"] = self.s.max_students_per_parent
        return row

    async def update_parent(self, me: TokenClaims, data: ParentUpdate) -> dict:
        await self.db.execute(
            "UPDATE parents SET display_name = COALESCE($2, display_name), "
            "preferred_language = COALESCE($3::ui_language, preferred_language) WHERE id = $1",
            me.parent_id, data.display_name.strip() if data.display_name else None, data.preferred_language)
        return await self.get_parent(me)

    async def _check_password(self, me: TokenClaims, password: str) -> None:
        row = await self.db.fetchrow("SELECT password_hash FROM users WHERE id = $1", me.subject)
        if row is None or not verify_password(password, row["password_hash"]):
            raise AppError("invalid_password", "Password is incorrect", "كلمة المرور غير صحيحة", 403)

    async def set_pin(self, me: TokenClaims, data: PinSet) -> None:
        await self._check_password(me, data.password)
        await self.db.execute(
            "UPDATE parents SET parent_pin_hash = $2, pin_failed_attempts = 0, pin_locked_until = NULL WHERE id = $1",
            me.parent_id, hash_password(data.pin, n=self.s.scrypt_n))

    async def verify_pin(self, me: TokenClaims, data: PinVerify) -> None:
        row = await self.db.fetchrow(
            "SELECT parent_pin_hash, (pin_locked_until IS NOT NULL AND pin_locked_until > now()) AS locked "
            "FROM parents WHERE id = $1", me.parent_id)
        if row is None:
            raise not_found()
        if row["parent_pin_hash"] is None:
            raise AppError("pin_not_set", "Parent PIN is not set", "لم يتم تعيين رمز ولي الأمر", 409)
        if row["locked"]:
            raise AppError("pin_locked", "Too many wrong attempts. Try again in a few minutes.",
                           "محاولات خاطئة كثيرة. حاول بعد بضع دقائق.", 429)
        if verify_password(data.pin, row["parent_pin_hash"]):
            await self.db.execute("UPDATE parents SET pin_failed_attempts = 0, pin_locked_until = NULL WHERE id = $1",
                                  me.parent_id)
            return
        await self.db.execute(
            """UPDATE parents SET
                 pin_failed_attempts = CASE WHEN pin_failed_attempts + 1 >= $2 THEN 0 ELSE pin_failed_attempts + 1 END,
                 pin_locked_until = CASE WHEN pin_failed_attempts + 1 >= $2
                                         THEN now() + make_interval(mins => $3) ELSE pin_locked_until END
               WHERE id = $1""", me.parent_id, PIN_MAX_ATTEMPTS, PIN_LOCK_MINUTES)
        raise AppError("invalid_pin", "Wrong PIN", "الرمز غير صحيح", 403)

    async def export(self, me: TokenClaims) -> dict:
        parent = await self.get_parent(me)
        students = await self.list_students(me)
        settings = await self.db.fetch(
            "SELECT student_id, daily_limit_minutes, free_conversation_enabled, role_play_enabled, "
            "store_transcripts, transcript_retention_days, weekly_report_email FROM parent_settings WHERE parent_id = $1",
            me.parent_id)
        lessons = await self.db.fetch(
            "SELECT ls.student_id, l.code AS lesson, ls.status::text AS status, ls.score, ls.stars, ls.started_at, "
            "ls.completed_at FROM lesson_sessions ls JOIN students s ON s.id = ls.student_id "
            "JOIN lessons l ON l.id = ls.lesson_id WHERE s.parent_id = $1 ORDER BY ls.started_at", me.parent_id)
        return {"format": "smart-english-export/1", "parent": parent, "students": students,
                "settings": settings, "lesson_sessions": lessons}

    async def delete_account(self, me: TokenClaims, data: PasswordConfirm) -> None:
        await self._check_password(me, data.password)
        # users -> parents -> students (trigger removes student identities) -> all child data (CASCADE)
        await self.db.execute(
            "WITH a AS (INSERT INTO audit_events(actor_user_id, action, target_type, target_id) "
            "VALUES (NULL, 'parent.deleted', 'parent', $2)) DELETE FROM users WHERE id = $1 AND role = 'parent'",
            me.subject, me.parent_id)

    # ---------- students ----------
    async def list_students(self, me: TokenClaims) -> list[dict]:
        return await self.db.fetch(
            f"SELECT {_STUDENT_COLS} FROM students s LEFT JOIN teachers t ON t.id = s.preferred_teacher_id "
            "WHERE s.parent_id = $1 ORDER BY s.created_at", me.parent_id)

    async def get_student(self, me: TokenClaims, student_id: uuid.UUID) -> dict:
        row = await self.db.fetchrow(
            f"SELECT {_STUDENT_COLS} FROM students s LEFT JOIN teachers t ON t.id = s.preferred_teacher_id "
            "WHERE s.id = $1 AND s.parent_id = $2", student_id, me.parent_id)
        if row is None:
            raise not_found()
        return row

    async def create_student(self, me: TokenClaims, data: StudentCreate) -> dict:
        row = await self.db.fetchrow(
            """
            WITH cnt AS (SELECT count(*) AS c FROM students WHERE parent_id = $1),
            u AS (INSERT INTO users(role) SELECT 'student' FROM cnt WHERE c < $6 RETURNING id),
            s AS (INSERT INTO students(user_id, parent_id, nickname, birth_year, avatar_code, preferred_teacher_id)
                  SELECT u.id, $1, $2, $3, $4, (SELECT id FROM teachers WHERE code = $5 AND is_enabled) FROM u
                  RETURNING id),
            a AS (INSERT INTO audit_events(actor_user_id, action, target_type, target_id)
                  SELECT $7, 'student.created', 'student', id FROM s)
            SELECT id FROM s
            """, me.parent_id, data.nickname, data.birth_year, data.avatar_code, data.preferred_teacher,
            self.s.max_students_per_parent, me.subject)
        if row is None:
            raise AppError("student_limit_reached",
                           f"You can add up to {self.s.max_students_per_parent} children",
                           f"يمكنك إضافة {self.s.max_students_per_parent} أطفال كحد أقصى", 409)
        return await self.get_student(me, row["id"])

    async def update_student(self, me: TokenClaims, student_id: uuid.UUID, data: StudentUpdate) -> dict:
        row = await self.db.fetchrow(
            """UPDATE students SET
                 nickname = COALESCE($3, nickname),
                 birth_year = COALESCE($4, birth_year),
                 avatar_code = COALESCE($5, avatar_code),
                 preferred_teacher_id = COALESCE((SELECT id FROM teachers WHERE code = $6 AND is_enabled),
                                                 preferred_teacher_id),
                 show_arabic = COALESCE($7, show_arabic),
                 daily_goal_minutes = COALESCE($8, daily_goal_minutes),
                 current_level = COALESCE($9::cefr_level, current_level)
               WHERE id = $1 AND parent_id = $2 RETURNING id""",
            student_id, me.parent_id, data.nickname, data.birth_year, data.avatar_code, data.preferred_teacher,
            data.show_arabic, data.daily_goal_minutes, data.current_level)
        if row is None:
            raise not_found()
        return await self.get_student(me, student_id)

    async def delete_student(self, me: TokenClaims, student_id: uuid.UUID) -> None:
        row = await self.db.fetchrow(
            "WITH d AS (DELETE FROM students WHERE id = $1 AND parent_id = $2 RETURNING id), "
            "a AS (INSERT INTO audit_events(actor_user_id, action, target_type, target_id) "
            "      SELECT $3, 'student.deleted', 'student', id FROM d) SELECT id FROM d",
            student_id, me.parent_id, me.subject)
        if row is None:
            raise not_found()

    # ---------- per-child settings ----------
    async def get_settings(self, me: TokenClaims, student_id: uuid.UUID) -> dict:
        await self.get_student(me, student_id)  # ownership
        row = await self.db.fetchrow(
            """SELECT daily_limit_minutes, allowed_start_time, allowed_end_time, free_conversation_enabled,
                      role_play_enabled, store_transcripts, transcript_retention_days, weekly_report_email
               FROM parent_settings WHERE parent_id = $1 AND (student_id = $2 OR student_id IS NULL)
               ORDER BY student_id NULLS LAST LIMIT 1""", me.parent_id, student_id)
        return _fmt_settings(row or SettingsIn().model_dump())

    async def put_settings(self, me: TokenClaims, student_id: uuid.UUID, data: SettingsIn) -> dict:
        await self.get_student(me, student_id)
        await self.db.execute(
            """INSERT INTO parent_settings(parent_id, student_id, daily_limit_minutes, allowed_start_time,
                   allowed_end_time, free_conversation_enabled, role_play_enabled, store_transcripts,
                   transcript_retention_days, weekly_report_email)
               VALUES ($1, $2, $3, $4::time, $5::time, $6, $7, $8, $9, $10)
               ON CONFLICT (parent_id, student_id) WHERE student_id IS NOT NULL DO UPDATE SET
                   daily_limit_minutes = EXCLUDED.daily_limit_minutes,
                   allowed_start_time = EXCLUDED.allowed_start_time, allowed_end_time = EXCLUDED.allowed_end_time,
                   free_conversation_enabled = EXCLUDED.free_conversation_enabled,
                   role_play_enabled = EXCLUDED.role_play_enabled, store_transcripts = EXCLUDED.store_transcripts,
                   transcript_retention_days = EXCLUDED.transcript_retention_days,
                   weekly_report_email = EXCLUDED.weekly_report_email""",
            me.parent_id, student_id, data.daily_limit_minutes,
            data.allowed_start_time, data.allowed_end_time,
            data.free_conversation_enabled, data.role_play_enabled, data.store_transcripts,
            data.transcript_retention_days, data.weekly_report_email)
        return await self.get_settings(me, student_id)

    # ---------- the child's own view ----------
    async def me_student(self, me: TokenClaims) -> dict:
        row = await self.db.fetchrow(
            f"""SELECT {_STUDENT_COLS},
                   COALESCE((SELECT learning_seconds FROM daily_activity
                             WHERE student_id = s.id AND activity_date = current_date), 0) AS seconds_today,
                   (SELECT daily_limit_minutes FROM parent_settings ps
                     WHERE ps.parent_id = s.parent_id AND (ps.student_id = s.id OR ps.student_id IS NULL)
                     ORDER BY ps.student_id NULLS LAST LIMIT 1) AS daily_limit_minutes
                FROM students s LEFT JOIN teachers t ON t.id = s.preferred_teacher_id
                WHERE s.id = $1 AND s.parent_id = $2""", me.student_id, me.parent_id)
        if row is None:
            raise not_found()
        limit = row.pop("daily_limit_minutes")
        row["minutes_left_today"] = None if limit is None else max(0, limit - row["seconds_today"] // 60)
        return row

    async def update_my_preferences(self, me: TokenClaims, data: StudentPreferences) -> dict:
        await self.db.execute(
            """UPDATE students SET
                 preferred_teacher_id = COALESCE((SELECT id FROM teachers WHERE code = $3 AND is_enabled),
                                                 preferred_teacher_id),
                 show_arabic = COALESCE($4, show_arabic)
               WHERE id = $1 AND parent_id = $2""",
            me.student_id, me.parent_id, data.preferred_teacher, data.show_arabic)
        return await self.me_student(me)


def _fmt_settings(row: dict) -> dict:
    out = dict(row)
    for k in ("allowed_start_time", "allowed_end_time"):
        v = out.get(k)
        out[k] = None if v is None else (v.isoformat(timespec="minutes") if isinstance(v, time) else str(v)[:5])
    return out
