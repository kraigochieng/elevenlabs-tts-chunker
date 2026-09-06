"""
Chunking logic for splitting long text into ElevenLabs-safe segments.
"""

from elevenlabs_tts_chunker.logging_config import logger
from elevenlabs_tts_chunker.schemas import ChunkIndex
from elevenlabs_tts_chunker.settings import get_settings


def default_chunk_indexes(text: str, max_chars: int | None = None) -> list[ChunkIndex]:
    """
    Greedily splits text into chunks under max_chars, backing off to the
    nearest whitespace boundary so no word is split mid-token.
    Falls back to Settings.default_max_chunk_chars when max_chars is omitted.
    """
    if max_chars is None:
        max_chars = get_settings().default_max_chunk_chars

    logger.debug(
        "Computing default chunks (max_chars=%d, text_len=%d)",
        max_chars,
        len(text),
    )

    chunks: list[ChunkIndex] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            probe = end
            while probe > start and not text[probe].isspace():
                probe -= 1
            if probe > start:
                end = probe
        chunks.append(ChunkIndex(start=start, end=end))
        start = end

    return chunks


def log_chunk_plan(chunks: list[ChunkIndex], text: str, source: str) -> None:
    """Logs a readable summary of the chunk plan to the terminal."""
    logger.info("Chunk plan (%s): %d chunk(s)", source, len(chunks))
    for i, c in enumerate(chunks):
        preview = text[c.start : c.end][:60].replace("\n", " ")
        ellipsis = "…" if (c.end - c.start) > 60 else ""
        logger.info(
            "  chunk %d/%d | chars %d–%d (%d chars) | %r%s",
            i + 1,
            len(chunks),
            c.start,
            c.end,
            c.end - c.start,
            preview,
            ellipsis,
        )


def resolve_chunks(
    text: str, chunk_indexes: list[ChunkIndex] | None
) -> list[ChunkIndex]:
    """Returns caller-supplied chunk_indexes if given, otherwise computes and
    logs the default chunk plan.

    If the full text already fits under the automatic-chunking threshold,
    splitting isn't needed at all — caller-supplied chunk_indexes are
    ignored in that case (logged at info level) and the text is treated as
    a single chunk instead.
    """
    max_chars = get_settings().default_max_chunk_chars

    if chunk_indexes:
        if len(text) <= max_chars:
            logger.info(
                "Ignoring %d caller-supplied chunk_indexes: text is %d chars, "
                "at or under the %d-char auto-chunking threshold, so no "
                "splitting is needed",
                len(chunk_indexes),
                len(text),
                max_chars,
            )
        else:
            log_chunk_plan(chunks=chunk_indexes, text=text, source="caller-supplied")
            return chunk_indexes

    chunks = default_chunk_indexes(text=text, max_chars=max_chars)
    log_chunk_plan(chunks=chunks, text=text, source="auto-computed")
    return chunks
