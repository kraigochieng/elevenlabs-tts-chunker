"""
Pydantic schemas for elevenlabs-tts-chunker.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator

# ── ElevenLabs-native shapes (mirrors their documented API) ────────────


class VoiceSettings(BaseModel):
    stability: float | None = Field(None, ge=0.0, le=1.0)
    similarity_boost: float | None = Field(None, ge=0.0, le=1.0)
    style: float | None = Field(None, ge=0.0, le=1.0)
    use_speaker_boost: bool | None = None
    speed: float | None = Field(None, ge=0.25, le=4.0)


class OutputFormat(str, Enum):
    mp3_44100_128 = "mp3_44100_128"
    mp3_44100_192 = "mp3_44100_192"
    mp3_44100_96 = "mp3_44100_96"
    mp3_44100_64 = "mp3_44100_64"
    mp3_44100_32 = "mp3_44100_32"
    mp3_22050_32 = "mp3_22050_32"
    pcm_44100 = "pcm_44100"
    pcm_24000 = "pcm_24000"
    pcm_22050 = "pcm_22050"
    pcm_16000 = "pcm_16000"
    ulaw_8000 = "ulaw_8000"
    # extend with any remaining enum values from the ElevenLabs docs as needed


class TextNormalization(str, Enum):
    auto = "auto"
    on = "on"
    off = "off"


# ── Wrapper-specific shapes ──────────────────────────────────────────────


class ChunkIndex(BaseModel):
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError("end must be greater than start")
        return v


class WrapperTTSRequest(BaseModel):
    """What callers (e.g. an n8n HTTP Request node) send to this service."""

    text: str
    model_id: str = "eleven_multilingual_v2"
    chunk_indexes: list[ChunkIndex] | None = None
    voice_settings: VoiceSettings | None = None
    output_format: OutputFormat = OutputFormat.mp3_44100_128
    apply_text_normalization: TextNormalization = TextNormalization.auto
    silence_between_chunks_ms: int = Field(300, ge=0)

    @field_validator("chunk_indexes")
    @classmethod
    def validate_chunk_indexes(cls, v, info):
        text = info.data.get("text", "")
        if not v:
            return v

        for c in v:
            if c.end > len(text):
                raise ValueError(f"chunk end {c.end} exceeds text length {len(text)}")

        sorted_chunks = sorted(v, key=lambda c: c.start)
        for prev, curr in zip(sorted_chunks, sorted_chunks[1:]):
            if curr.start < prev.end:
                raise ValueError(
                    f"chunk_indexes overlap: [{prev.start}, {prev.end}) and "
                    f"[{curr.start}, {curr.end})"
                )

        return v
