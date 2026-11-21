"""Static public metadata served by GET /v1/meta.

`features` must only report True for capabilities that are implemented AND tested.
The iOS app hides any UI whose feature flag is False (no dead buttons).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.core.config import Settings


class TeacherInfo(BaseModel):
    code: str
    display_name: str
    description_en: str
    description_ar: str
    min_level: str
    available: bool


class FeatureFlags(BaseModel):
    parent_accounts: bool = True           # Phase 2 ✓
    ai_teacher: bool = False               # Phase 3
    voice_classroom: bool = False          # Phase 4
    curriculum: bool = False               # Phase 5
    pronunciation_assessment: bool = False  # Phase 6
    games: bool = False                    # Phase 7
    parent_dashboard: bool = False         # Phase 8
    subscriptions: bool = False            # after MVP testing


class MetaResponse(BaseModel):
    app: str
    tagline_en: str
    tagline_ar: str
    api_version: str
    server_version: str
    min_ios_app_version: str
    supported_languages: list[str]
    levels: list[str]
    teachers: list[TeacherInfo]
    features: FeatureFlags


TEACHERS: tuple[TeacherInfo, ...] = (
    TeacherInfo(code="emma", display_name="Emma", description_en="Friendly teacher for beginners",
                description_ar="معلمة ودودة للمبتدئين", min_level="A0", available=True),
    TeacherInfo(code="daniel", display_name="Daniel", description_en="Friendly teacher for conversation practice",
                description_ar="معلم ودود لممارسة المحادثة", min_level="A1", available=True),
    TeacherInfo(code="alex", display_name="Alex", description_en="Advanced teacher for future intermediate levels",
                description_ar="معلم متقدم للمستويات المتوسطة القادمة", min_level="A2", available=False),
)


def build_meta(settings: Settings) -> MetaResponse:
    return MetaResponse(
        app=settings.app_name,
        tagline_en="Learn English. Speak with Confidence.",
        tagline_ar="تعلّم الإنجليزية. تحدّث بثقة.",
        api_version="1",
        server_version=settings.server_version,
        min_ios_app_version=settings.min_ios_app_version,
        supported_languages=["ar", "en"],
        levels=["A0", "A1", "A2"],
        teachers=list(TEACHERS),
        features=FeatureFlags(),
    )
