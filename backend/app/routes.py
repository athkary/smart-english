"""All HTTP routes (v1). Thin handlers: validate -> service -> JSON."""
from __future__ import annotations

from starlette.requests import Request
from starlette.routing import Route

from app.core.http import RateLimiter, client_ip, no_content, ok, path_uuid, read_json, require_auth
from app.modules.auth.service import AuthService, LoginIn, RefreshIn, SignupIn, StudentSessionIn
from app.modules.health.checks import run_checks
from app.modules.meta.catalog import build_meta
from app.modules.profiles.service import (ParentUpdate, PasswordConfirm, PinSet, PinVerify, ProfileService,
                                          SettingsIn, StudentCreate, StudentPreferences, StudentUpdate)


def _auth(request: Request) -> AuthService:
    return request.app.state.auth_service


def _profiles(request: Request) -> ProfileService:
    return request.app.state.profile_service


def _limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


# ---------- system ----------
async def health(request: Request):
    return ok({"status": "ok"})


async def ready(request: Request):
    is_ready, details = await run_checks(request.app.state.readiness_checks)
    return ok({"status": "ready" if is_ready else "not_ready", "checks": details}, 200 if is_ready else 503)


async def meta(request: Request):
    return ok(build_meta(request.app.state.settings))


# ---------- auth ----------
async def signup(request: Request):
    _limiter(request).check(f"signup:{client_ip(request)}", 5, 600)
    data = await read_json(request, SignupIn)
    tokens, extra = await _auth(request).signup(data)
    return ok({**tokens.as_dict(), **extra}, 201)


async def login(request: Request):
    data = await read_json(request, LoginIn)
    _limiter(request).check(f"login-ip:{client_ip(request)}", 20, 600)
    _limiter(request).check(f"login-email:{data.email}", 5, 300)
    return ok((await _auth(request).login(data)).as_dict())


async def refresh(request: Request):
    _limiter(request).check(f"refresh:{client_ip(request)}", 60, 60)
    data = await read_json(request, RefreshIn)
    return ok((await _auth(request).refresh(data)).as_dict())


async def logout(request: Request):
    data = await read_json(request, RefreshIn)
    await _auth(request).logout(data)
    return no_content()


async def student_session(request: Request):
    me = require_auth(request, role="parent")
    data = await read_json(request, StudentSessionIn)
    return ok((await _auth(request).student_session(me, data)).as_dict(), 201)


# ---------- parent ----------
async def parent_me(request: Request):
    me = require_auth(request, role="parent")
    if request.method == "GET":
        return ok(await _profiles(request).get_parent(me))
    if request.method == "PATCH":
        return ok(await _profiles(request).update_parent(me, await read_json(request, ParentUpdate)))
    await _profiles(request).delete_account(me, await read_json(request, PasswordConfirm))  # DELETE
    return no_content()


async def parent_pin(request: Request):
    me = require_auth(request, role="parent")
    _limiter(request).check(f"pin-set:{me.parent_id}", 10, 600)
    await _profiles(request).set_pin(me, await read_json(request, PinSet))
    return no_content()


async def parent_pin_verify(request: Request):
    me = require_auth(request, role="parent")
    await _profiles(request).verify_pin(me, await read_json(request, PinVerify))
    return no_content()


async def parent_export(request: Request):
    me = require_auth(request, role="parent")
    resp = ok(await _profiles(request).export(me))
    resp.headers["Content-Disposition"] = 'attachment; filename="smart-english-data.json"'
    return resp


# ---------- students (parent-owned) ----------
async def students(request: Request):
    me = require_auth(request, role="parent")
    if request.method == "GET":
        return ok({"students": await _profiles(request).list_students(me)})
    return ok(await _profiles(request).create_student(me, await read_json(request, StudentCreate)), 201)


async def student_detail(request: Request):
    me = require_auth(request, role="parent")
    sid = path_uuid(request, "student_id")
    if request.method == "GET":
        return ok(await _profiles(request).get_student(me, sid))
    if request.method == "PATCH":
        return ok(await _profiles(request).update_student(me, sid, await read_json(request, StudentUpdate)))
    await _profiles(request).delete_student(me, sid)
    return no_content()


async def student_settings(request: Request):
    me = require_auth(request, role="parent")
    sid = path_uuid(request, "student_id")
    if request.method == "GET":
        return ok(await _profiles(request).get_settings(me, sid))
    return ok(await _profiles(request).put_settings(me, sid, await read_json(request, SettingsIn)))


# ---------- the child ----------
async def me_student(request: Request):
    me = require_auth(request, role="student")
    return ok(await _profiles(request).me_student(me))


async def me_student_preferences(request: Request):
    me = require_auth(request, role="student")
    return ok(await _profiles(request).update_my_preferences(me, await read_json(request, StudentPreferences)))


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/ready", ready, methods=["GET"]),
    Route("/v1/meta", meta, methods=["GET"]),
    Route("/v1/auth/parents/signup", signup, methods=["POST"]),
    Route("/v1/auth/login", login, methods=["POST"]),
    Route("/v1/auth/refresh", refresh, methods=["POST"]),
    Route("/v1/auth/logout", logout, methods=["POST"]),
    Route("/v1/auth/students/session", student_session, methods=["POST"]),
    Route("/v1/parents/me", parent_me, methods=["GET", "PATCH", "DELETE"]),
    Route("/v1/parents/me/pin", parent_pin, methods=["PUT"]),
    Route("/v1/parents/me/pin/verify", parent_pin_verify, methods=["POST"]),
    Route("/v1/parents/me/export", parent_export, methods=["GET"]),
    Route("/v1/students", students, methods=["GET", "POST"]),
    Route("/v1/students/{student_id}", student_detail, methods=["GET", "PATCH", "DELETE"]),
    Route("/v1/students/{student_id}/settings", student_settings, methods=["GET", "PUT"]),
    Route("/v1/me/student", me_student, methods=["GET"]),
    Route("/v1/me/student/preferences", me_student_preferences, methods=["PATCH"]),
]
