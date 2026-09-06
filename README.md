# elevenlabs-tts-chunker

A FastAPI wrapper around the [ElevenLabs Text-to-Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert) that transparently handles text longer than ElevenLabs' 10,000-character limit per request.

It accepts a single block of text (of any length), splits it into safe chunks, synthesizes each chunk via ElevenLabs, and merges the resulting audio into one continuous mp3 — so callers don't need to think about the character limit at all.

## Why

ElevenLabs' `/v1/text-to-speech/{voice_id}` endpoint rejects requests where `text` exceeds 10,000 characters. For long-form content (briefs, articles, multi-section scripts), this means splitting text into multiple requests and stitching the resulting audio back together — including handling split points cleanly, keeping voice settings consistent across calls, and avoiding artifacts at the seams.

This service handles all of that in one place, exposing an API shaped closely after ElevenLabs' own, so it can act as a near drop-in replacement in existing pipelines (e.g. n8n workflows) with minimal changes.

## Features

- Accepts text of any length — no manual pre-splitting required by the caller
- Optional **caller-supplied chunk boundaries** (`chunk_indexes`) for full control over where splits happen
- **Automatic chunking fallback** when no boundaries are supplied
- Consistent `voice_id` / `voice_settings` applied across all chunks
- Audio merging via `pydub` (backed by `ffmpeg`) for clean, artifact-free concatenation
- Optional silence padding between merged chunks
- Returns a single finished mp3, regardless of how many chunks were needed internally

## How it works

### 1. Chunking strategy

**Caller-supplied boundaries.** The request body accepts an optional `chunk_indexes` field — a list of `{start, end}` objects (character offsets into `tts_text`). This is useful when the caller already knows the semantically meaningful split points in their text (e.g. per-story, per-section, per-paragraph boundaries) and wants a guarantee that no chunk cuts mid-sentence or mid-tag (such as an ElevenLabs `<break time="Xs" />` tag).

**Default (automatic) chunking.** If `chunk_indexes` is omitted, the service falls back to its own splitting logic:

1. Walk the text, accumulating characters up to a safe threshold below the 10,000-character limit (default ~9,500, leaving headroom).
2. Rather than cutting at an arbitrary offset, back off to the nearest whitespace boundary so no word is split mid-token.
3. Repeat until the entire input is covered by a sequence of ordered `{start, end}` pairs.

Either way, the result is the same internal representation: an ordered list of chunk boundaries over `tts_text`.

### 2. Synthesis

Each chunk is sent to ElevenLabs as a separate call to `/v1/text-to-speech/{voice_id}`, in sequence, using the same `voice_id` and `voice_settings` for every chunk to keep the voice consistent across the merged output.

### 3. Merging

The mp3 bytes returned per chunk are stitched together using [`pydub`](https://github.com/jiaaro/pydub), which relies on `ffmpeg` for decoding/encoding and clean concatenation — avoiding the artifacts that can occur with naive byte-level concatenation of mp3 files. An optional short silence gap (`silence_between_chunks_ms`) can be inserted at each seam to smooth the transition between chunks.

The final output is returned as a single continuous mp3 file. From the caller's perspective, the 10,000-character limit is effectively transparent.

## Requirements

- Python 3.10+
- `ffmpeg` installed and available on `PATH` (required by `pydub`)
- An ElevenLabs API key — either configured on the server, or supplied by
  each caller via the `xi-api-key` header (see Configuration)

## Installation

```bash
git clone https://github.com/<your-org>/elevenlabs-tts-chunker.git
cd elevenlabs-tts-chunker
pip install -r requirements.txt
```

`requirements.txt`:
```
fastapi
uvicorn
httpx
pydub
python-dotenv
```

Install `ffmpeg`:
```bash
# macOS
brew install ffmpeg

# Debian/Ubuntu
apt install ffmpeg
```

## Configuration

`ELEVENLABS_API_KEY` is optional and acts as a fallback default. Set it as
an environment variable:

```bash
export ELEVENLABS_API_KEY=your_api_key_here
```

Or via a `.env` file:
```
ELEVENLABS_API_KEY=your_api_key_here
```

Any request can instead (or additionally) supply its own key via the
`xi-api-key` header, same as ElevenLabs' own API — it takes precedence over
the server default when present. If a request has neither, it gets a 401.
This lets the service run as a multi-tenant proxy with no server-wide key
configured at all, if every caller brings their own.

## Running locally

```bash
uvicorn main:app --reload --port 8000
```

The service will be available at `http://localhost:8000`.

## API Reference

### `POST /v1/text-to-speech/{voice_id}`

Mimics the shape of ElevenLabs' own endpoint, with additional chunking-related fields.

#### Path parameters

| Name | Type | Description |
|---|---|---|
| `voice_id` | string | ElevenLabs voice ID to use for synthesis |

#### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `tts_text` | string | Yes | Full text to synthesize, of any length |
| `model_id` | string | No | ElevenLabs model ID. Defaults to `eleven_multilingual_v2` |
| `chunk_indexes` | array of `{start, end}` | No | Caller-supplied chunk boundaries. If omitted, chunks are computed automatically |
| `voice_settings` | object | No | Passed through to ElevenLabs on every chunk (`stability`, `similarity_boost`, `style`, `use_speaker_boost`, `speed`) |
| `output_format` | string | No | ElevenLabs output format, e.g. `mp3_44100_128`. Defaults to `mp3_44100_128` |
| `silence_between_chunks_ms` | integer | No | Milliseconds of silence inserted at each chunk seam. Defaults to `300` |

#### Example request

```json
{
  "tts_text": "Hi, I'm Robin with your top events for today's brief...\n\nStory 1: ...\n\nStory 2: ...",
  "voice_id": "wyWA56cQNU2KqUW4eCsI",
  "voice_settings": {
    "speed": 1.0
  }
}
```

With caller-supplied boundaries:

```json
{
  "tts_text": "...",
  "voice_id": "wyWA56cQNU2KqUW4eCsI",
  "chunk_indexes": [
    { "start": 0, "end": 9200 },
    { "start": 9200, "end": 18100 }
  ]
}
```

#### Response

Returns the merged audio as a binary mp3 stream (`Content-Type: audio/mpeg`).

#### Errors

| Status | Meaning |
|---|---|
| `400` | `chunk_indexes` out of bounds relative to `tts_text` |
| `422` | Request validation error (matches ElevenLabs' own error code for malformed input) |
| `502` | Upstream ElevenLabs API error on one of the chunk requests |

## Usage in n8n

1. Build your full `tts_text` (and optionally your own `chunk_indexes`) in a Code node.
2. Point an HTTP Request node at this service's `/v1/text-to-speech/{voice_id}` endpoint instead of ElevenLabs' directly.
3. Set the HTTP Request node's response format to **File / Binary**.
4. The returned mp3 is already fully merged — no further concatenation step needed in your workflow.

## Deployment

This service can be deployed to any platform that supports a Python web process (Railway, Render, Fly.io, etc.). Ensure the deployment environment has `ffmpeg` available — most platforms require either a buildpack/Dockerfile step to install it.

Minimal `Dockerfile`:

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## License

MIT
