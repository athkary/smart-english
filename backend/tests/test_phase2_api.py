"""Phase 2 behaviour against a real PostgreSQL: accounts, children, ownership, deletion."""
import pathlib
import uuid

import pytest

from app.main import create_app
from app.modules.auth.service import CONSENT_VERSION
from tests.conftest import run
from tests.support.asgi import Client

PW = "family-pass-2026"


@pytest.fixture()
def client(db, settings):
    with Client(create_app(settings, db=db)) as c:
        c.db = db
        yield c


def signup(c, email="mom@example.com", name="أم أحمد"):
    r = c.post("/v1/auth/parents/signup", json={"email": email, "password": PW, "display_name": name,
                                                  "preferred_language": "ar", "consent_version": CONSENT_VERSION})
    assert r.status_code == 201, r.body
    return r.json()


def add_child(c, token, nickname="Ahmed", **kw):
    r = c.post("/v1/students", token=token, json={"nickname": nickname, **kw})
    assert r.status_code == 201, r.body
    return r.json()


# ---------------- signup / login ----------------
def test_signup_creates_parent_with_defaults(client):
    t = signup(client)
    assert t["role"] == "parent" and t["token_type"] == "bearer"
    me = client.get("/v1/parents/me", token=t["access_token"]).json()
    assert me["email"] == "mom@example.com" and me["display_name"] == "أم أحمد"
    assert me["has_pin"] is False and me["student_count"] == 0 and me["plan"] == "free"
    audit = run(client.db.fetch("SELECT action FROM audit_events"))
    assert audit == [{"action": "parent.signup"}]


def test_signup_rejections(client):
    signup(client)
    dup = client.post("/v1/auth/parents/signup", json={"email": "MOM@example.com", "password": PW,
                      "display_name": "x", "consent_version": CONSENT_VERSION})
    assert dup.status_code == 409 and dup.json()["error"]["message_ar"]
    weak = client.post("/v1/auth/parents/signup", json={"email": "a@b.co", "password": "short",
                       "display_name": "x", "consent_version": CONSENT_VERSION})
    assert weak.json()["error"]["code"] == "weak_password"
    no_consent = client.post("/v1/auth/parents/signup", json={"email": "c@b.co", "password": PW,
                             "display_name": "x", "consent_version": "old"})
    assert no_consent.json()["error"]["code"] == "consent_required"
    bad = client.post("/v1/auth/parents/signup", json={"email": "not-an-email", "password": PW})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"


def test_login_and_password_is_hashed(client):
    signup(client)
    assert client.post("/v1/auth/login", json={"email": "Mom@Example.com", "password": PW}).status_code == 200
    wrong = client.post("/v1/auth/login", json={"email": "mom@example.com", "password": "nope-nope-nope"})
    unknown = client.post("/v1/auth/login", json={"email": "who@example.com", "password": PW})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
    stored = run(client.db.fetchrow("SELECT password_hash FROM users WHERE email = 'mom@example.com'"))
    assert stored["password_hash"].startswith("scrypt$") and PW not in stored["password_hash"]


def test_login_rate_limited_per_email(client):
    signup(client)
    codes = [client.post("/v1/auth/login", json={"email": "mom@example.com", "password": "wrong-wrong-1"}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


# ---------------- refresh rotation ----------------
def test_refresh_rotates_and_detects_reuse(client):
    t = signup(client)
    r1 = client.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refresh_token"] != t["refresh_token"]
    # Reusing the old (rotated) token is treated as theft: whole family revoked
    reuse = client.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert reuse.status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401
    # only hashes are stored
    rows = run(client.db.fetch("SELECT token_hash FROM refresh_tokens"))
    assert all(len(r["token_hash"]) == 64 for r in rows)
    assert t["refresh_token"] not in {r["token_hash"] for r in rows}


def test_logout_revokes(client):
    t = signup(client)
    assert client.post("/v1/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


# ---------------- children ----------------
def test_child_crud_and_validation(client):
    tok = signup(client)["access_token"]
    kid = add_child(client, tok, nickname="  Ahmed  ", birth_year=2017, avatar_code="owl", preferred_teacher="daniel")
    assert kid["nickname"] == "Ahmed" and kid["preferred_teacher"] == "daniel" and kid["current_level"] == "A0"
    assert kid["show_arabic"] is True
    upd = client.patch(f"/v1/students/{kid['id']}", token=tok, json={"show_arabic": False, "daily_goal_minutes": 20})
    assert upd.json()["show_arabic"] is False and upd.json()["daily_goal_minutes"] == 20
    assert client.post("/v1/students", token=tok, json={"nickname": "x", "avatar_code": "dragon"}).status_code == 422
    assert client.post("/v1/students", token=tok, json={"nickname": "x", "preferred_teacher": "alex"}).status_code == 422
    assert len(client.get("/v1/students", token=tok).json()["students"]) == 1


def test_child_limit(client, settings):
    tok = signup(client)["access_token"]
    for i in range(settings.max_students_per_parent):
        add_child(client, tok, nickname=f"Kid{i}")
    r = client.post("/v1/students", token=tok, json={"nickname": "OneMore"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "student_limit_reached"


def test_other_family_cannot_see_or_touch_children(client):
    a = signup(client, "a@example.com")["access_token"]
    b = signup(client, "b@example.com")["access_token"]
    kid = add_child(client, a)
    for method, path, body in [("GET", f"/v1/students/{kid['id']}", None),
                               ("PATCH", f"/v1/students/{kid['id']}", {"nickname": "Hacked"}),
                               ("DELETE", f"/v1/students/{kid['id']}", None),
                               ("GET", f"/v1/students/{kid['id']}/settings", None),
                               ("PUT", f"/v1/students/{kid['id']}/settings", {}),
                               ("POST", "/v1/auth/students/session", {"student_id": kid["id"]})]:
        r = client.request(method, path, token=b, json=body)
        assert r.status_code == 404, (method, path, r.status_code)
    assert client.get("/v1/students", token=b).json()["students"] == []
    assert client.get(f"/v1/students/{kid['id']}", token=a).json()["nickname"] == "Ahmed"
    assert client.get("/v1/students/not-a-uuid", token=a).status_code == 404


def test_auth_required_and_roles(client):
    assert client.get("/v1/students").status_code == 401
    assert client.get("/v1/students", token="garbage").status_code == 401
    parent = signup(client)["access_token"]
    kid = add_child(client, parent)
    child = client.post("/v1/auth/students/session", token=parent, json={"student_id": kid["id"]}).json()
    assert child["role"] == "student"
    # child token cannot reach parent routes; parent token cannot act as child
    assert client.get("/v1/students", token=child["access_token"]).status_code == 403
    assert client.get("/v1/parents/me", token=child["access_token"]).status_code == 403
    assert client.get("/v1/me/student", token=parent).status_code == 403


# ---------------- child session ----------------
def test_child_session_view_preferences_and_refresh(client):
    parent = signup(client)["access_token"]
    kid = add_child(client, parent)
    child = client.post("/v1/auth/students/session", token=parent, json={"student_id": kid["id"]}).json()
    me = client.get("/v1/me/student", token=child["access_token"]).json()
    assert me["id"] == kid["id"] and me["minutes_left_today"] is None and me["preferred_teacher"] == "emma"
    client.put(f"/v1/students/{kid['id']}/settings", token=parent, json={"daily_limit_minutes": 30})
    assert client.get("/v1/me/student", token=child["access_token"]).json()["minutes_left_today"] == 30
    p = client.patch("/v1/me/student/preferences", token=child["access_token"],
                     json={"preferred_teacher": "daniel", "show_arabic": False})
    assert p.json()["preferred_teacher"] == "daniel" and p.json()["show_arabic"] is False
    # a refreshed child token is still a child token for the same child
    r = client.post("/v1/auth/refresh", json={"refresh_token": child["refresh_token"]}).json()
    assert r["role"] == "student"
    assert client.get("/v1/me/student", token=r["access_token"]).json()["id"] == kid["id"]


def test_settings_defaults_and_validation(client):
    tok = signup(client)["access_token"]
    kid = add_child(client, tok)
    s = client.get(f"/v1/students/{kid['id']}/settings", token=tok).json()
    assert s["transcript_retention_days"] == 90 and s["free_conversation_enabled"] is True
    s2 = client.put(f"/v1/students/{kid['id']}/settings", token=tok,
                    json={"daily_limit_minutes": 45, "allowed_start_time": "15:00", "allowed_end_time": "19:30",
                          "free_conversation_enabled": False, "transcript_retention_days": 0}).json()
    assert s2["daily_limit_minutes"] == 45 and s2["allowed_start_time"] == "15:00" and s2["allowed_end_time"] == "19:30"
    assert s2["free_conversation_enabled"] is False and s2["transcript_retention_days"] == 0
    # second PUT updates the same row (upsert)
    client.put(f"/v1/students/{kid['id']}/settings", token=tok, json={"daily_limit_minutes": 60})
    assert run(client.db.fetchrow("SELECT count(*) AS n FROM parent_settings WHERE student_id IS NOT NULL"))["n"] == 1
    bad = client.put(f"/v1/students/{kid['id']}/settings", token=tok, json={"allowed_start_time": "15:00"})
    assert bad.status_code == 422


# ---------------- PIN gate ----------------
def test_pin_set_verify_and_lockout(client):
    tok = signup(client)["access_token"]
    assert client.post("/v1/parents/me/pin/verify", token=tok, json={"pin": "1234"}).json()["error"]["code"] == "pin_not_set"
    assert client.put("/v1/parents/me/pin", token=tok, json={"pin": "2468", "password": "wrong-password"}).status_code == 403
    assert client.put("/v1/parents/me/pin", token=tok, json={"pin": "12a4", "password": PW}).status_code == 422
    assert client.put("/v1/parents/me/pin", token=tok, json={"pin": "2468", "password": PW}).status_code == 204
    assert client.get("/v1/parents/me", token=tok).json()["has_pin"] is True
    assert client.post("/v1/parents/me/pin/verify", token=tok, json={"pin": "2468"}).status_code == 204
    codes = [client.post("/v1/parents/me/pin/verify", token=tok, json={"pin": "0000"}).status_code for _ in range(5)]
    assert codes == [403] * 5
    # locked now — even the right PIN is refused
    locked = client.post("/v1/parents/me/pin/verify", token=tok, json={"pin": "2468"})
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "pin_locked"


# ---------------- export & deletion ----------------
def test_export_contains_children(client):
    tok = signup(client)["access_token"]
    add_child(client, tok, nickname="Sara")
    r = client.get("/v1/parents/me/export", token=tok)
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["format"] == "smart-english-export/1" and data["students"][0]["nickname"] == "Sara"


def test_delete_child_removes_identity_and_tokens(client):
    tok = signup(client)["access_token"]
    kid = add_child(client, tok)
    child = client.post("/v1/auth/students/session", token=tok, json={"student_id": kid["id"]}).json()
    assert client.delete(f"/v1/students/{kid['id']}", token=tok).status_code == 204
    assert run(client.db.fetchrow("SELECT count(*) AS n FROM users WHERE role = 'student'"))["n"] == 0
    assert client.post("/v1/auth/refresh", json={"refresh_token": child["refresh_token"]}).status_code == 401
    assert client.get("/v1/me/student", token=child["access_token"]).status_code == 404


def test_delete_account_erases_everything(client):
    tok = signup(client)["access_token"]
    for n in ("Ahmed", "Sara"):
        add_child(client, tok, nickname=n)
    keep = signup(client, "other@example.com")["access_token"]
    add_child(client, keep, nickname="Other")
    assert client.request("DELETE", "/v1/parents/me", token=tok,
                          json={"password": "wrong-password", "confirm": "DELETE"}).status_code == 403
    assert client.request("DELETE", "/v1/parents/me", token=tok, json={"password": PW}).status_code == 422
    assert client.request("DELETE", "/v1/parents/me", token=tok,
                          json={"password": PW, "confirm": "DELETE"}).status_code == 204
    counts = run(client.db.fetchrow(
        "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM students) AS students, "
        "(SELECT count(*) FROM parents) AS parents, (SELECT count(*) FROM refresh_tokens) AS tokens, "
        "(SELECT count(*) FROM parent_settings) AS settings, (SELECT count(*) FROM subscriptions) AS subs"))
    # only the other family remains: 1 parent user + 1 student user
    assert counts == {"users": 2, "students": 1, "parents": 1, "tokens": 1, "settings": 1, "subs": 1}
    assert client.post("/v1/auth/login", json={"email": "mom@example.com", "password": PW}).status_code == 401


# ---------------- transport ----------------
def test_cors_allows_only_configured_origin(client):
    ok = client.request("OPTIONS", "/v1/auth/login", headers={
        "Origin": "http://127.0.0.1:5500", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://127.0.0.1:5500"
    bad = client.request("OPTIONS", "/v1/auth/login", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_large_body_rejected(client):
    r = client.post("/v1/auth/login", json={"email": "a@b.co", "password": "x" * 70000})
    assert r.status_code == 413


def test_schema_smoke_sql(db):
    sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations/sql/tests/schema_smoke.sql").read_text()
    run(db.execute(sql.replace("\\set ON_ERROR_STOP 1", "")))
