"""
elevenlabs-tts-chunker
A FastAPI wrapper around the ElevenLabs Text-to-Speech API that transparently
handles text longer than the 10,000 character per-request limit by chunking,
synthesizing each chunk, and merging the resulting audio into one mp3.

This module is intentionally thin — it wires HTTP request/response handling
to the business logic in services/.
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.schemas import WrapperTTSRequest
from elevenlabs_tts_chunker.services.orchestrator import synthesize_speech
from elevenlabs_tts_chunker.settings import get_settings

app = FastAPI(title="elevenlabs-tts-chunker")


@app.post("/v1/text-to-speech/{voice_id}")
async def text_to_speech(voice_id: str, req: WrapperTTSRequest):
    logger.info(
        "Incoming TTS request | voice_id=%s model_id=%s text_len=%d "
        "output_format=%s custom_chunk_indexes=%s",
        voice_id,
        req.model_id,
        len(req.text),
        req.output_format.value,
        bool(req.chunk_indexes),
    )

    out_buffer = await synthesize_speech(req=req, voice_id=voice_id)

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
