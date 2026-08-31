"""
Orchestration service — coordinates chunking, per-chunk synthesis, and audio
merging for a single text-to-speech request.
"""

import io
import time

from fastapi import HTTPException

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.schemas import ChunkIndex, WrapperTTSRequest
from elevenlabs_tts_chunker.services.audio import merge_audio_chunks
from elevenlabs_tts_chunker.services.chunking import resolve_chunks
from elevenlabs_tts_chunker.services.tts import get_elevenlabs_client, synthesize_chunk
from elevenlabs_tts_chunker.settings import get_settings


def _surrounding_context(
    text: str, chunk: ChunkIndex, context_chars: int
) -> tuple[str | None, str | None]:
    """Returns (previous_text, next_text): up to context_chars of the source
    text immediately before/after this chunk, for seam continuity. Uses the
    raw source text rather than neighboring chunks, so it works whether
    chunks are contiguous (default auto-chunking) or caller-supplied with
    gaps between them."""
    previous_text = text[max(0, chunk.start - context_chars) : chunk.start]
    next_text = text[chunk.end : chunk.end + context_chars]
    return previous_text or None, next_text or None


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

    context_chars = get_settings().tts_context_chars

    client = get_elevenlabs_client()
    audio_chunks: list[bytes] = []
    for i, c in enumerate(chunks):
        segment_text = text[c.start : c.end]
        previous_text, next_text = _surrounding_context(
            text=text, chunk=c, context_chars=context_chars
        )
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
            previous_text=previous_text,
            next_text=next_text,
        )
        audio_chunks.append(audio_bytes)

    out_buffer = merge_audio_chunks(
        audio_chunks=audio_chunks,
        silence_between_chunks_ms=req.silence_between_chunks_ms,
    )

    total_elapsed = time.perf_counter() - request_start
    logger.info("Total request time=%.2fs", total_elapsed)

    return out_buffer
