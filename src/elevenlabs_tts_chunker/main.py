"""
elevenlabs-tts-chunker
A FastAPI wrapper around the ElevenLabs Text-to-Speech API that transparently
handles text longer than the 10,000 character per-request limit by chunking,
synthesizing each chunk, and merging the resulting audio into one mp3.

This module is intentionally thin — it wires HTTP request/response handling
to the business logic in services/.
"""

import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.schemas import WrapperTTSRequest
from elevenlabs_tts_chunker.services.audio import merge_audio_chunks
from elevenlabs_tts_chunker.services.chunking import resolve_chunks
from elevenlabs_tts_chunker.services.tts import get_elevenlabs_client, synthesize_chunk
from elevenlabs_tts_chunker.settings import get_settings

app = FastAPI(title="elevenlabs-tts-chunker")


@app.post("/v1/text-to-speech/{voice_id}")
async def text_to_speech(voice_id: str, req: WrapperTTSRequest):
    request_start = time.perf_counter()
    text = req.text

    if not text.strip():
        logger.warning("Rejected request: text was empty")
        raise HTTPException(status_code=422, detail="text must not be empty")

    logger.info(
        "Incoming TTS request | voice_id=%s model_id=%s text_len=%d "
        "output_format=%s custom_chunk_indexes=%s",
        voice_id,
        req.model_id,
        len(text),
        req.output_format.value,
        bool(req.chunk_indexes),
    )

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

    return StreamingResponse(
        content=out_buffer,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{voice_id}_merged.mp3"'
        },
    )


@app.get("/health")
async def health():
    settings = get_settings()
    logger.debug("Health check hit")
    return {"status": "ok", "api_key_loaded": bool(settings.elevenlabs_api_key)}
