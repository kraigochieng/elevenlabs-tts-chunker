"""
Orchestration service — coordinates chunking, per-chunk synthesis, and audio
merging for a single text-to-speech request.

Chunk seam continuity is handled via ElevenLabs' request stitching
(previous_request_ids/next_request_ids), which conditions each chunk's
generation on the actual audio produced for its neighbors rather than on
surrounding text. Because a chunk's next_request_ids can only reference a
chunk that has already been generated, this runs in two passes:

  1. Forward pass — generate every chunk in order, each one conditioned on
     up to the 3 chunks already generated before it (previous_request_ids).
  2. Correction pass — regenerate every chunk except the last, now that the
     request_ids of chunks after it are known too, so every interior seam
     is conditioned on real audio in both directions. The last chunk is
     skipped: pass 1 already gave it full previous context, and it has no
     next chunk to add.

Pass 2 always references pass 1's request_ids (not other pass-2 results),
so corrections are computed from one consistent snapshot rather than
cascading.
"""

import io
import time

from fastapi import HTTPException

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
    req: WrapperTTSRequest, voice_id: str, api_key: str | None = None
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

    # Pass 1: forward synthesis, each chunk conditioned on the ones before it.
    pass1_results: list[SynthesizedChunk] = []
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
            previous_request_ids=_request_ids(
                pass1_results[-MAX_STITCHING_REQUEST_IDS:]
            ),
            pass_label="pass 1/forward",
        )
        pass1_results.append(result)

    # Pass 2: regenerate every chunk but the last, now that both neighbors'
    # request_ids are known, so every interior seam has real audio context
    # in both directions.
    final_results = list(pass1_results)
    for i, c in enumerate(chunks[:-1]):
        final_results[i] = await synthesize_chunk(
            client=client,
            text=text[c.start : c.end],
            voice_id=voice_id,
            model_id=req.model_id,
            voice_settings=voice_settings,
            output_format=req.output_format.value,
            apply_text_normalization=req.apply_text_normalization.value,
            chunk_number=i + 1,
            total_chunks=len(chunks),
            previous_request_ids=_request_ids(
                pass1_results[:i][-MAX_STITCHING_REQUEST_IDS:]
            ),
            next_request_ids=_request_ids(
                pass1_results[i + 1 : i + 1 + MAX_STITCHING_REQUEST_IDS]
            ),
            pass_label="pass 2/correction",
        )

    out_buffer = merge_audio_chunks(
        audio_chunks=[r.audio_bytes for r in final_results],
        silence_between_chunks_ms=req.silence_between_chunks_ms,
    )

    total_elapsed = time.perf_counter() - request_start
    logger.info("Total request time=%.2fs", total_elapsed)

    return out_buffer
