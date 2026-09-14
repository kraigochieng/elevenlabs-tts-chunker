"""
Orchestration service — coordinates chunking, per-chunk synthesis, and audio
merging for a single text-to-speech request.

Chunk seam continuity is handled via ElevenLabs' request stitching
(previous_request_ids), which conditions each chunk's generation on the
actual audio already produced for the chunks before it rather than on
surrounding text. This is a single forward pass: every chunk is generated
once, in order, each one conditioned on up to the 3 chunks already
generated before it. So a request with N chunks costs exactly N ElevenLabs
calls.

This only stitches backward. A chunk is never regenerated once its
successors exist, so seams aren't conditioned on real audio in both
directions the way a follow-up correction pass would give them. That's a
deliberate trade-off for speed and cost: on a long request, it's the
difference between N ElevenLabs calls and roughly 2N-1.
"""

import io
import time

from fastapi import HTTPException
from pydantic import SecretStr

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.schemas import WrapperTTSRequest
from elevenlabs_tts_chunker.services.audio import merge_audio_chunks
from elevenlabs_tts_chunker.services.chunking import resolve_chunks
from elevenlabs_tts_chunker.services.tts import (
    MAX_STITCHING_REQUEST_IDS,
    SynthesizedChunk,
    get_elevenlabs_client,
    synthesize_chunk,
)


def _request_ids(results: list[SynthesizedChunk]) -> list[str] | None:
    ids = [r.request_id for r in results if r.request_id]
    return ids or None


async def synthesize_speech(
    req: WrapperTTSRequest, voice_id: str, api_key: SecretStr | None = None
) -> io.BytesIO:
    """Runs the full chunk -> synthesize -> merge pipeline for one request.
    api_key, if given, is the caller's own key (from the xi-api-key header)
    and takes precedence over the server's configured default."""
    request_start = time.perf_counter()
    text = req.text

    if not text.strip():
        logger.warning("Rejected request: text was empty")
        raise HTTPException(status_code=422, detail="text must not be empty")

    # Resolve before any chunking work so a missing key fails fast.
    client = get_elevenlabs_client(api_key=api_key)

    chunks = resolve_chunks(text=text, chunk_indexes=req.chunk_indexes)

    voice_settings = (
        req.voice_settings.model_dump(exclude_none=True) if req.voice_settings else {}
    )
    if voice_settings:
        logger.debug("Voice settings: %s", voice_settings)

    # Single forward pass: each chunk conditioned on the ones already
    # generated before it. N chunks -> N ElevenLabs calls.
    results: list[SynthesizedChunk] = []
    for i, c in enumerate(chunks):
        result = await synthesize_chunk(
            client=client,
            text=text[c.start : c.end],
            voice_id=voice_id,
            model_id=req.model_id,
            voice_settings=voice_settings,
            output_format=req.output_format.value,
            apply_text_normalization=req.apply_text_normalization.value,
            chunk_number=i + 1,
            total_chunks=len(chunks),
            previous_request_ids=_request_ids(results[-MAX_STITCHING_REQUEST_IDS:]),
        )
        results.append(result)

    out_buffer = merge_audio_chunks(
        audio_chunks=[r.audio_bytes for r in results],
        silence_between_chunks_ms=req.silence_between_chunks_ms,
    )

    total_elapsed = time.perf_counter() - request_start
    logger.info("Total request time=%.2fs", total_elapsed)

    return out_buffer
