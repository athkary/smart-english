import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings
from app.modules.meta.catalog import build_meta
from app.providers import base as p


# ---------- config ----------
def test_settings_from_env():
    s = Settings.from_env({"ENVIRONMENT": "test", "CORS_ORIGINS": "https://a.com, https://b.com",
                           "ACCESS_TOKEN_TTL_SECONDS": "600"})
    assert s.environment is Environment.test
    assert s.cors_origins == ["https://a.com", "https://b.com"]
    assert s.access_token_ttl_seconds == 600


@pytest.mark.parametrize("env", ["staging", "production"])
def test_weak_jwt_secret_rejected_outside_local(env):
    with pytest.raises(ValidationError):
        Settings.from_env({"ENVIRONMENT": env})
    with pytest.raises(ValidationError):
        Settings.from_env({"ENVIRONMENT": env, "JWT_SECRET": "short"})
    assert Settings.from_env({"ENVIRONMENT": env, "JWT_SECRET": "k" * 48}).environment.value == env


def test_secrets_not_leaked_in_repr():
    s = Settings.from_env({"ANTHROPIC_API_KEY": "sk-ant-should-not-print"})
    assert "sk-ant-should-not-print" not in repr(s)
    assert "sk-ant-should-not-print" not in s.model_dump_json()


# ---------- meta ----------
def test_meta_is_bilingual_and_honest():
    m = build_meta(Settings())
    assert m.supported_languages == ["ar", "en"]
    codes = [t.code for t in m.teachers]
    assert codes == ["emma", "daniel", "alex"]
    assert all(t.description_ar and t.description_en for t in m.teachers)
    # Only what is built and tested may be advertised as working
    flags = m.features.model_dump()
    assert flags.pop("parent_accounts") is True
    assert not any(flags.values())


# ---------- providers ----------
class _GoodTTS:
    name = "test-tts"

    def synthesize_stream(self, text, *, voice_id, fmt):  # pragma: no cover - shape only
        raise NotImplementedError


class _BadTTS:
    name = "bad"


def test_registry_enforces_interfaces():
    reg = p.ProviderRegistry()
    with pytest.raises(p.ProviderNotConfigured):
        reg.get("tts")
    with pytest.raises(TypeError):
        reg.register("tts", _BadTTS())
    reg.register("tts", _GoodTTS())
    assert reg.configured()["tts"] == "test-tts"
    assert reg.configured()["llm"] is None


def test_transcript_match_cannot_claim_accuracy():
    with pytest.raises(ValueError):
        p.PronunciationReport(method="transcript_match", recognized_text="I like apple", accuracy=80)
    ok = p.PronunciationReport(method="phoneme_assessment", recognized_text="apple", accuracy=91.5)
    assert ok.accuracy == 91.5
