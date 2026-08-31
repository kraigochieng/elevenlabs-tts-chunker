"""
ElevenLabs TTS synthesis service — SDK client construction and per-chunk
speech generation.
"""

import time

from elevenlabs import VoiceSettings as ElevenLabsVoiceSettings
from elevenlabs.client import AsyncElevenLabs
from fastapi import HTTPException

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.settings import get_settings


def get_elevenlabs_client() -> AsyncElevenLabs:
    settings = get_settings()
    return AsyncElevenLabs(
        api_key=settings.elevenlabs_api_key,
        base_url=settings.elevenlabs_api_base,
    )


async def synthesize_chunk(
    client: AsyncElevenLabs,
    text: str,
    voice_id: str,
    model_id: str,
    voice_settings: dict,
    output_format: str,
    apply_text_normalization: str,
    chunk_number: int,
    total_chunks: int,
    previous_text: str | None = None,
    next_text: str | None = None,
) -> bytes:
    """Calls the ElevenLabs SDK for a single chunk of text and collects the
    streamed audio bytes into one buffer."""
    logger.info(
        "Synthesizing chunk %d/%d (%d chars) via voice_id=%s model_id=%s",
        chunk_number,
        total_chunks,
        len(text),
        voice_id,
        model_id,
    )
    logger.debug(
        "Chunk %d/%d context | previous_text=%d chars next_text=%d chars",
        chunk_number,
        total_chunks,
        len(previous_text or ""),
        len(next_text or ""),
    )
    start_time = time.perf_counter()

    try:
        audio_stream = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            voice_settings=ElevenLabsVoiceSettings(**voice_settings)
            if voice_settings
            else None,
            output_format=output_format,
            apply_text_normalization=apply_text_normalization,
            previous_text=previous_text,
            next_text=next_text,
        )
        audio_bytes = b"".join([chunk async for chunk in audio_stream])
    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        logger.error(
            "Chunk %d/%d failed after %.2fs: %s",
            chunk_number,
            total_chunks,
            elapsed,
            exc,
        )
        raise HTTPException(status_code=502, detail=f"ElevenLabs error: {exc}") from exc

    elapsed = time.perf_counter() - start_time
    logger.info(
        "Chunk %d/%d synthesized OK in %.2fs (%d bytes returned)",
        chunk_number,
        total_chunks,
        elapsed,
        len(audio_bytes),
    )
    return audio_bytes
