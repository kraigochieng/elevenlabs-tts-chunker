"""
Orchestration service — coordinates chunking, per-chunk synthesis, and audio
merging for a single text-to-speech request. This is the seam where
previous_text/next_text context will be threaded through per chunk.
"""

import io
import time

from fastapi import HTTPException

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.schemas import WrapperTTSRequest
from elevenlabs_tts_chunker.services.audio import merge_audio_chunks
from elevenlabs_tts_chunker.services.chunking import resolve_chunks
from elevenlabs_tts_chunker.services.tts import get_elevenlabs_client, synthesize_chunk


async def synthesize_speech(req: WrapperTTSRequest, voice_id: str) -> io.BytesIO:
    """Runs the full chunk -> synthesize -> merge pipeline for one request."""
    request_start = time.perf_counter()
    text = req.text

    if not text.strip():
        logger.warning("Rejected request: text was empty")
        raise HTTPException(status_code=422, detail="text must not be empty")

    chunks = resolve_chunks(text=text, chunk_indexes=req.chunk_indexes)

    voice_settings = (
        req.voice_settings.model_dump(exclude_none=True) if req.voice_settings else {}
    )
    if voice_settings:
        logger.debug("Voice settings: %s", voice_settings)

    client = get_elevenlabs_client()
    audio_chunks: list[bytes] = []
    for i, c in enumerate(chunks):
        segment_text = text[c.start : c.end]
        audio_bytes = await synthesize_chunk(
            client=client,
            text=segment_text,
            voice_id=voice_id,
            model_id=req.model_id,
            voice_settings=voice_settings,
            output_format=req.output_format.value,
            apply_text_normalization=req.apply_text_normalization.value,
            chunk_number=i + 1,
            total_chunks=len(chunks),
        )
        audio_chunks.append(audio_bytes)

    out_buffer = merge_audio_chunks(
        audio_chunks=audio_chunks,
        silence_between_chunks_ms=req.silence_between_chunks_ms,
    )

    total_elapsed = time.perf_counter() - request_start
    logger.info("Total request time=%.2fs", total_elapsed)

    return out_buffer
