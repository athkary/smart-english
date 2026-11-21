from app.main import create_app
from tests.support.asgi import Client


def test_health_meta_ready(db, settings):
    with Client(create_app(settings, db=db)) as c:
        assert c.get("/health").json() == {"status": "ok"}
        r = c.get("/ready")
        assert r.status_code == 200 and r.json()["checks"]["postgres"]["ok"]
        assert c.get("/v1/meta").json()["features"]["parent_accounts"] is True
        r = c.get("/nope", headers={"X-Request-ID": "abcdefgh1234"})
        assert r.status_code == 404 and r.json()["error"]["request_id"] == "abcdefgh1234"
