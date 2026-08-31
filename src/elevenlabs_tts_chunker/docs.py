"""
Plain-text API documentation served at GET /.

Pulls enum values and field defaults from the actual schema/settings
classes (rather than hardcoding a second copy) so this can't silently
drift out of sync with the real request contract.
"""

from elevenlabs_tts_chunker.schemas import OutputFormat, TextNormalization, WrapperTTSRequest
from elevenlabs_tts_chunker.services.tts import MAX_STITCHING_REQUEST_IDS
from elevenlabs_tts_chunker.settings import Settings

_fields = WrapperTTSRequest.model_fields
_default_max_chunk_chars = Settings.model_fields["default_max_chunk_chars"].default


def render_api_docs() -> str:
    output_formats = ", ".join(f.value for f in OutputFormat)
    normalization_modes = ", ".join(f.value for f in TextNormalization)

    return f"""elevenlabs-tts-chunker
=======================

A FastAPI wrapper around the ElevenLabs Text-to-Speech API that transparently
handles text longer than ElevenLabs' 10,000-character limit per request. Send
it text of any length; it chunks, synthesizes each chunk, and returns one
merged mp3.


ENDPOINT
--------

POST /v1/text-to-speech/{{voice_id}}

  voice_id (path) — the ElevenLabs voice ID to synthesize with.

Request body (JSON):

  text                          string, required
      The text to synthesize. Any length — no manual pre-splitting needed.

  model_id                      string, default "{_fields["model_id"].default}"
      ElevenLabs model ID (GET /v1/models on ElevenLabs' API for the list).

  language_code                 string or null, default null
      ISO 639-1 code to enforce a language. Ignored by multilingual_v2.

  chunk_indexes                 list of {{start, end}} or null, default null
      Caller-supplied chunk boundaries (character offsets into `text`), for
      full control over split points (e.g. per-paragraph). Rules:
        - end must be > start
        - end must not exceed len(text)
        - chunks must not overlap each other
      Omit this to fall back to automatic chunking: text is split under
      ~{_default_max_chunk_chars} characters per chunk (configurable via the
      DEFAULT_MAX_CHUNK_CHARS env var), backing off to the nearest
      whitespace boundary so no word is split mid-token.

  voice_settings                object or null, default null
      Passed through to ElevenLabs unchanged: stability, similarity_boost,
      style, use_speaker_boost, speed. Applied identically to every chunk.

  output_format                 string, default "{_fields["output_format"].default.value}"
      One of: {output_formats}

  apply_text_normalization      string, default "{_fields["apply_text_normalization"].default.value}"
      One of: {normalization_modes}

  silence_between_chunks_ms     integer >= 0, default {_fields["silence_between_chunks_ms"].default}
      Silence inserted at each seam when merging chunk audio together.

Response:

  200 audio/mpeg — the merged mp3, streamed, with
      Content-Disposition: attachment; filename="{{voice_id}}_merged.mp3"
  422 — text was empty, or chunk_indexes failed validation
  502 — the ElevenLabs API call for a chunk failed


CHUNK SEAM CONTINUITY
----------------------

Multi-chunk requests use ElevenLabs' request stitching
(previous_request_ids/next_request_ids) so each chunk is conditioned on the
actual audio generated for its neighbors, not just surrounding text. This
runs as two synthesis passes per request (a forward pass, then a correction
pass covering every chunk but the last) — so a request that resolves to N
chunks costs roughly 2N-1 ElevenLabs API calls, not N. Single-chunk requests
are unaffected (1 call, no second pass).

Requires logging/history enabled on the ElevenLabs account (the default;
disabled only for Zero Retention Mode accounts) and is unavailable on the
eleven_v3 model. Up to {MAX_STITCHING_REQUEST_IDS} request_ids are sent
per direction.


OTHER ENDPOINTS
----------------

GET /health   — {{"status": "ok", "api_key_loaded": bool}}
GET /docs     — interactive Swagger UI (auto-generated from the schema)
GET /         — this page
"""
