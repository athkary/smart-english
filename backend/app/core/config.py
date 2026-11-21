"""Application settings loaded from environment variables.

Deliberately dependency-light (plain pydantic) so it can be unit-tested anywhere.
Provider API keys live ONLY here on the server — never in the iOS app.
"""
from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Mapping

from pydantic import BaseModel, Field, SecretStr, model_validator

_WEAK_SECRETS = {"", "change-me", "changeme", "secret", "dev-secret-change-me"}


class Environment(str, Enum):
    local = "local"
    test = "test"
    staging = "staging"
    production = "production"


class Settings(BaseModel):
    app_name: str = "SMART ENGLISH AI"
    server_version: str = "0.1.0"
    min_ios_app_version: str = "0.1.0"
    environment: Environment = Environment.local
    log_level: str = "INFO"

    database_url: str = "postgresql://smart:smart@localhost:5432/smart_english"
    redis_url: str = ""                      # optional until Phase 4 (realtime sessions)
    auto_migrate: bool = True                # apply SQL migrations on startup

    jwt_secret: SecretStr = SecretStr("dev-secret-change-me")
    jwt_issuer: str = "smart-english-ai"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    scrypt_n: int = Field(default=2**17, ge=2**10, le=2**20)
    max_students_per_parent: int = Field(default=6, ge=1, le=20)

    cors_origins: list[str] = Field(default_factory=list)  # iOS app does not need CORS

    # Provider credentials (server-side only). Empty = provider not configured.
    anthropic_api_key: SecretStr = SecretStr("")
    stt_provider: str = ""
    tts_provider: str = ""
    pronunciation_provider: str = ""

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.environment in (Environment.staging, Environment.production):
            secret = self.jwt_secret.get_secret_value()
            if secret.lower() in _WEAK_SECRETS or len(secret) < 32:
                raise ValueError("JWT_SECRET must be a strong value (>=32 chars) outside local/test")
            if self.scrypt_n < 2**15:
                raise ValueError("SCRYPT_N is too low for staging/production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.production

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        data: dict[str, object] = {}
        for name in cls.model_fields:
            key = name.upper()
            if key in env:
                value: object = env[key]
                if name == "cors_origins":
                    value = [o.strip() for o in str(value).split(",") if o.strip()]
                data[name] = value
        return cls(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
