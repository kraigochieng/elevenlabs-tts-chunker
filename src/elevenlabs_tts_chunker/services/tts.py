"""
ElevenLabs TTS synthesis service — SDK client construction and per-chunk
speech generation.
"""

import time
from dataclasses import dataclass

from elevenlabs import VoiceSettings as ElevenLabsVoiceSettings
from elevenlabs.client import AsyncElevenLabs
from fastapi import HTTPException

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.settings import get_settings

# ElevenLabs allows at most 3 previous_request_ids / next_request_ids per
# request stitching call.
MAX_STITCHING_REQUEST_IDS = 3


def get_elevenlabs_client(api_key: str | None = None) -> AsyncElevenLabs:
    """Builds an ElevenLabs client using api_key if given (from a caller's
    xi-api-key header), otherwise falling back to the server's configured
    default. Raises 401 if neither is available."""
    settings = get_settings()
    resolved_key = api_key or settings.elevenlabs_api_key
    if not resolved_key:
        raise HTTPException(
            status_code=401,
            detail="No ElevenLabs API key available: supply one via the "
            "xi-api-key header, or configure ELEVENLABS_API_KEY on the server.",
        )
    return AsyncElevenLabs(
        api_key=resolved_key,
        base_url=settings.elevenlabs_api_base,
    )


@dataclass
class SynthesizedChunk:
    """Audio for one chunk, plus the request_id ElevenLabs assigned to it so
    it can be used as previous_request_ids/next_request_ids on neighboring
    chunks' requests (request stitching). request_id is None if the
    response didn't carry one (e.g. logging/history disabled on the
    account), in which case stitching against this chunk is skipped."""

    audio_bytes: bytes
    request_id: str | None


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
    previous_request_ids: list[str] | None = None,
    next_request_ids: list[str] | None = None,
    pass_label: str = "synthesis",
) -> SynthesizedChunk:
    """Calls the ElevenLabs SDK for a single chunk of text and collects the
    streamed audio bytes plus the request_id ElevenLabs assigned to the
    generation."""
    logger.info(
        "Synthesizing chunk %d/%d (%d chars) via voice_id=%s model_id=%s [%s]",
        chunk_number,
        total_chunks,
        len(text),
        voice_id,
        model_id,
        pass_label,
    )
    logger.debug(
        "Chunk %d/%d context | previous_request_ids=%s next_request_ids=%s",
        chunk_number,
        total_chunks,
        previous_request_ids,
        next_request_ids,
    )
    start_time = time.perf_counter()

    try:
        async with client.text_to_speech.with_raw_response.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            voice_settings=ElevenLabsVoiceSettings(**voice_settings)
            if voice_settings
            else None,
            output_format=output_format,
            apply_text_normalization=apply_text_normalization,
            previous_request_ids=previous_request_ids,
            next_request_ids=next_request_ids,
        ) as response:
            audio_bytes = b"".join([chunk async for chunk in response.data])
            request_id = response.headers.get("request-id")
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
        "Chunk %d/%d synthesized OK in %.2fs (%d bytes returned, request_id=%s)",
        chunk_number,
        total_chunks,
        elapsed,
        len(audio_bytes),
        request_id,
    )
    return SynthesizedChunk(audio_bytes=audio_bytes, request_id=request_id)
