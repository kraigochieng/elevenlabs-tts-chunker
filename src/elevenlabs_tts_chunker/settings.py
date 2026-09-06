"""
Application settings for elevenlabs-tts-chunker.
Loads configuration from environment variables / a .env file via pydantic-settings.
"""

from functools import lru_cache

from dotenv import find_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ElevenLabs' hard per-request character limit. default_max_chunk_chars must
# stay below this — see the validator on Settings below.
ELEVENLABS_HARD_CHAR_LIMIT = 10_000


class Settings(BaseSettings):
    # Fallback ElevenLabs API key, used when a request doesn't supply its
    # own via the xi-api-key header. Optional: if unset, every request must
    # bring its own key, or it's rejected with a 401.
    elevenlabs_api_key: str | None = None

    # Base host for the ElevenLabs API — overridable via .env, e.g. for
    # pointing at a proxy, mock server, or a regional/enterprise endpoint.
    elevenlabs_api_base: str = "https://api.elevenlabs.io"

    # Kept separate from elevenlabs_api_base so the versioned resource path
    # could be changed independently (e.g. if ElevenLabs ships a /v2 endpoint)
    # without needing to touch the host. Not currently consumed directly —
    # the official SDK builds its own request paths from elevenlabs_api_base —
    # but kept here for reference/back-compat with a raw-HTTP client.
    elevenlabs_tts_path: str = "/v1/text-to-speech"

    # Headroom below ElevenLabs' hard 10,000 character limit per request.
    # Overridable via .env if you want tighter margins. Must stay strictly
    # below ELEVENLABS_HARD_CHAR_LIMIT — see validator below.
    default_max_chunk_chars: int = Field(9500, gt=0)

    # Standard library logging level name (DEBUG, INFO, WARNING, ERROR).
    # Overridable via .env — set to DEBUG to see per-chunk text previews.
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=find_dotenv() or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("default_max_chunk_chars")
    @classmethod
    def enforce_elevenlabs_char_limit(cls, v: int) -> int:
        if v >= ELEVENLABS_HARD_CHAR_LIMIT:
            raise ValueError(
                f"default_max_chunk_chars ({v}) must be strictly less than "
                f"ElevenLabs' hard per-request limit of {ELEVENLABS_HARD_CHAR_LIMIT} "
                "characters — chunks at or above this size will be rejected "
                "by the ElevenLabs API. Lower DEFAULT_MAX_CHUNK_CHARS in your .env."
            )
        return v

    @property
    def elevenlabs_tts_url(self) -> str:
        return f"{self.elevenlabs_api_base.rstrip('/')}{self.elevenlabs_tts_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
