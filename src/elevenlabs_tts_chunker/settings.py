"""
Application settings for elevenlabs-tts-chunker.
Loads configuration from environment variables / a .env file via pydantic-settings.
"""

from functools import lru_cache

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    elevenlabs_api_key: str

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
    # Overridable via .env if that limit ever changes or you want tighter
    # margins.
    default_max_chunk_chars: int = 9500

    # Standard library logging level: DEBUG, INFO, WARNING, or ERROR.
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=find_dotenv() or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def elevenlabs_tts_url(self) -> str:
        return f"{self.elevenlabs_api_base.rstrip('/')}{self.elevenlabs_tts_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
