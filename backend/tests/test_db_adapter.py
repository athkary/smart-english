from tests.conftest import run
def test_adapter_types_and_migrations(db):
    rows = run(db.fetch("SELECT code, is_enabled, min_level FROM teachers ORDER BY code"))
    assert [(r["code"], r["is_enabled"]) for r in rows] == [("alex", False), ("daniel", True), ("emma", True)]
    r = run(db.fetchrow("WITH u AS (INSERT INTO users(role,email,password_hash) VALUES ('parent',$1,$2) RETURNING id, created_at) SELECT id, created_at FROM u", "a'b@x.com", "h"))
    import uuid, datetime
    assert isinstance(r["id"], uuid.UUID) and isinstance(r["created_at"], datetime.datetime)
    assert run(db.fetchrow("SELECT email FROM users WHERE id=$1", r["id"]))["email"] == "a'b@x.com"
    from app.db.database import UniqueViolation
    import pytest
    with pytest.raises(UniqueViolation):
        run(db.execute("INSERT INTO users(role,email,password_hash) VALUES ('parent',$1,'h')", "A'B@x.com"))
    assert run(db.fetch("SELECT version FROM schema_migrations ORDER BY 1")) == [{"version":"0001"},{"version":"0002"}]
