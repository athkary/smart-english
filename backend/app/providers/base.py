"""Provider interfaces — swap AI/audio vendors independently (spec §13).

Phase 1 defines the contracts and the registry only. Concrete adapters
(Anthropic, STT, TTS, pronunciation) are added and tested in Phases 3, 4 and 6.
No fake/mock adapter is registered in production code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol, runtime_checkable


# ---------- Shared data types ----------
@dataclass(frozen=True)
class AudioFormat:
    encoding: Literal["pcm16", "opus"] = "pcm16"
    sample_rate: int = 16_000
    channels: int = 1


@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    is_final: bool
    confidence: float | None = None
    end_of_turn: bool = False


@dataclass(frozen=True)
class Correction:
    original: str
    corrected: str
    explanation_ar: str


@dataclass(frozen=True)
class TeacherTurn:
    """Structured teacher output (bilingual)."""
    text_en: str
    text_ar: str
    correction: Correction | None = None
    repeat_after_me: str | None = None
    new_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["teacher", "student"]
    text: str


@dataclass(frozen=True)
class TeacherContext:
    teacher_code: str
    mode: Literal["beginner", "guided", "free", "role_play"]
    student_level: str
    show_arabic: bool = True
    scenario_code: str | None = None
    lesson_vocabulary: tuple[str, ...] = ()
    learner_summary: str = ""
    history: tuple[ChatMessage, ...] = ()


@dataclass(frozen=True)
class PhonemeError:
    phoneme: str
    expected: str
    score: float | None = None


@dataclass(frozen=True)
class WordAssessment:
    word: str
    error_type: Literal["none", "mispronunciation", "omission", "insertion"] = "none"
    accuracy: float | None = None
    phonemes: tuple[PhonemeError, ...] = ()


@dataclass(frozen=True)
class PronunciationReport:
    method: Literal["phoneme_assessment", "transcript_match"]
    recognized_text: str
    words: tuple[WordAssessment, ...] = ()
    missing_words: tuple[str, ...] = ()
    accuracy: float | None = None      # must be None for transcript_match
    fluency: float | None = None
    completeness: float | None = None

    def __post_init__(self) -> None:
        if self.method == "transcript_match" and self.accuracy is not None:
            raise ValueError("Accuracy scores require phoneme-level assessment")


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool
    flags: tuple[str, ...] = field(default_factory=tuple)
    redacted_text: str | None = None


# ---------- Interfaces ----------
@runtime_checkable
class SpeechToTextStream(Protocol):
    async def send_audio(self, chunk: bytes) -> None: ...
    async def finish(self) -> None: ...
    def events(self) -> AsyncIterator[TranscriptEvent]: ...
    async def close(self) -> None: ...


@runtime_checkable
class SpeechToText(Protocol):
    name: str
    async def open_stream(self, fmt: AudioFormat, *, language: str = "en-US",
                          phrase_hints: tuple[str, ...] = ()) -> SpeechToTextStream: ...


@runtime_checkable
class TextToSpeech(Protocol):
    name: str
    def synthesize_stream(self, text: str, *, voice_id: str, fmt: AudioFormat) -> AsyncIterator[bytes]: ...


@runtime_checkable
class TeacherLLM(Protocol):
    name: str
    def respond(self, context: TeacherContext, student_text: str) -> AsyncIterator[TeacherTurn]: ...


@runtime_checkable
class PronunciationAssessor(Protocol):
    name: str
    async def assess(self, audio: bytes, fmt: AudioFormat, target_text: str) -> PronunciationReport: ...


@runtime_checkable
class ContentSafety(Protocol):
    name: str
    async def check_input(self, text: str) -> SafetyVerdict: ...
    async def check_output(self, text: str) -> SafetyVerdict: ...


ProviderKind = Literal["stt", "tts", "llm", "pronunciation", "safety"]

_INTERFACES: dict[str, type] = {
    "stt": SpeechToText,
    "tts": TextToSpeech,
    "llm": TeacherLLM,
    "pronunciation": PronunciationAssessor,
    "safety": ContentSafety,
}


class ProviderNotConfigured(RuntimeError):
    """Raised when a feature needs a provider that has not been configured yet."""


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}

    def register(self, kind: ProviderKind, provider: object) -> None:
        iface = _INTERFACES[kind]
        if not isinstance(provider, iface):
            raise TypeError(f"{type(provider).__name__} does not implement {iface.__name__}")
        self._providers[kind] = provider

    def get(self, kind: ProviderKind) -> object:
        try:
            return self._providers[kind]
        except KeyError:
            raise ProviderNotConfigured(f"No '{kind}' provider configured") from None

    def configured(self) -> dict[str, str | None]:
        return {k: getattr(self._providers.get(k), "name", None) for k in _INTERFACES}
