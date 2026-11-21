import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import security as sec

FAST_N = 2**14  # lower cost for tests only


def test_password_hash_roundtrip_and_salt():
    h1 = sec.hash_password("correct horse battery", n=FAST_N)
    h2 = sec.hash_password("correct horse battery", n=FAST_N)
    assert h1 != h2, "each hash must use a unique salt"
    assert h1.startswith("scrypt$")
    assert sec.verify_password("correct horse battery", h1)
    assert not sec.verify_password("wrong password!!", h1)


def test_default_cost_hash_verifies():
    h = sec.hash_password("a-strong-pass-123")
    assert h.split("$")[1] == str(2**17)
    assert sec.verify_password("a-strong-pass-123", h)


@pytest.mark.parametrize("stored", ["", "bcrypt$x", "scrypt$abc", "scrypt$1$2$3$!!$!!"])
def test_verify_rejects_malformed_hashes(stored):
    assert sec.verify_password("anything", stored) is False


def test_password_policy():
    with pytest.raises(sec.PasswordPolicyError):
        sec.validate_password("short")
    with pytest.raises(sec.PasswordPolicyError):
        sec.validate_password("password123")
    sec.validate_password("my-family-2026!")


SECRET = "x" * 40


def _claims():
    return sec.TokenClaims(subject=uuid.uuid4(), role="student", scope="student:learn", parent_id=uuid.uuid4())


def test_access_token_roundtrip():
    c = _claims()
    tok = sec.create_access_token(c, secret=SECRET, issuer="se", ttl_seconds=900)
    assert sec.decode_access_token(tok, secret=SECRET, issuer="se") == c


def test_access_token_expired():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    tok = sec.create_access_token(_claims(), secret=SECRET, issuer="se", ttl_seconds=60, now=past)
    with pytest.raises(sec.InvalidTokenError):
        sec.decode_access_token(tok, secret=SECRET, issuer="se")


def test_access_token_wrong_secret_or_issuer():
    tok = sec.create_access_token(_claims(), secret=SECRET, issuer="se", ttl_seconds=60)
    with pytest.raises(sec.InvalidTokenError):
        sec.decode_access_token(tok, secret="y" * 40, issuer="se")
    with pytest.raises(sec.InvalidTokenError):
        sec.decode_access_token(tok, secret=SECRET, issuer="other")


def test_alg_none_token_rejected():
    import jwt
    forged = jwt.encode({"sub": str(uuid.uuid4()), "role": "admin", "scope": "admin", "iss": "se",
                         "iat": 0, "exp": 9999999999}, key=None, algorithm="none")
    with pytest.raises(sec.InvalidTokenError):
        sec.decode_access_token(forged, secret=SECRET, issuer="se")


def test_refresh_token_only_hash_is_stored():
    token, digest = sec.new_refresh_token()
    assert token not in digest and len(digest) == 64
    assert sec.hash_refresh_token(token) == digest
