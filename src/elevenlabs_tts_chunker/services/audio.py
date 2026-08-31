"""
Audio merging service — combines per-chunk mp3 bytes into one continuous
file using pydub (backed by ffmpeg).
"""

import io
import time

from pydub import AudioSegment

from elevenlabs_tts_chunker.logging_config import logger


def merge_audio_chunks(
    audio_chunks: list[bytes], silence_between_chunks_ms: int
) -> io.BytesIO:
    """Merges a list of mp3 byte buffers into one mp3, inserting silence at
    each seam. Returns a seeked-to-start BytesIO ready to stream."""
    combined = AudioSegment.empty()
    silence = (
        AudioSegment.silent(duration=silence_between_chunks_ms)
        if silence_between_chunks_ms > 0
        else None
    )
    if silence is not None:
        logger.debug(
            "Will insert %dms of silence between chunk seams",
            silence_between_chunks_ms,
        )

    for i, audio_bytes in enumerate(audio_chunks):
        segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        combined += segment
        if silence is not None and i < len(audio_chunks) - 1:
            combined += silence

    logger.info(
        "All %d chunk(s) synthesized — merging into final audio (total duration %.2fs)",
        len(audio_chunks),
        len(combined) / 1000.0,
    )

    merge_start = time.perf_counter()
    out_buffer = io.BytesIO()
    combined.export(out_buffer, format="mp3")
    out_buffer.seek(0)
    merge_elapsed = time.perf_counter() - merge_start

    output_size = out_buffer.getbuffer().nbytes
    logger.info(
        "Merge complete in %.2fs | final file size=%d bytes",
        merge_elapsed,
        output_size,
    )

    return out_buffer
