# elevenlabs-tts-chunker

A FastAPI wrapper around the [ElevenLabs Text-to-Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert) that transparently handles text longer than ElevenLabs' 10,000-character limit per request.

It accepts a single block of text (of any length), splits it into safe chunks, synthesizes each chunk via ElevenLabs, and merges the resulting audio into one continuous mp3 — so callers don't need to think about the character limit at all.

This project is designed to be **forked and self-deployed**: clone it, plug in your own ElevenLabs API key (or let your callers bring their own), and run it as your own service. See [Fork & Deploy](#fork--deploy) below.

> Not affiliated with or endorsed by ElevenLabs. You'll need your own ElevenLabs account and API key, and your use of it is subject to [ElevenLabs' own Terms of Service](https://elevenlabs.io/terms-of-use).

## Why

ElevenLabs' `/v1/text-to-speech/{voice_id}` endpoint rejects requests where `text` exceeds 10,000 characters. For long-form content (briefs, articles, multi-section scripts), this means splitting text into multiple requests and stitching the resulting audio back together — including handling split points cleanly, keeping voice settings consistent across calls, and avoiding artifacts at the seams.

This service handles all of that in one place, exposing an API shaped closely after ElevenLabs' own, so it can act as a near drop-in replacement in existing pipelines (e.g. n8n workflows) with minimal changes.

## Features

- Accepts text of any length — no manual pre-splitting required by the caller
- Optional **caller-supplied chunk boundaries** (`chunk_indexes`) for full control over where splits happen, with overlap/bounds validation
- **Automatic chunking fallback** when no boundaries are supplied
- Consistent `voice_id` / `voice_settings` applied across all chunks
- **Seam continuity via ElevenLabs request stitching** — each chunk is conditioned on the actual audio generated for its neighbors, not just surrounding text
- Audio merging via `pydub` (backed by `ffmpeg`) for clean, artifact-free concatenation
- Optional silence padding between merged chunks
- Returns a single finished mp3, regardless of how many chunks were needed internally
- **Bring-your-own-key support** — callers can supply their own ElevenLabs API key per request via the `xi-api-key` header, so this can run as a multi-tenant proxy with no server-wide key at all
- Self-documenting: `GET /` returns plain-text API docs generated live from the actual request schema

## How it works

### 1. Chunking strategy

**Caller-supplied boundaries.** The request body accepts an optional `chunk_indexes` field — a list of `{start, end}` objects (character offsets into `text`). This is useful when the caller already knows the semantically meaningful split points in their text (e.g. per-story, per-section, per-paragraph boundaries) and wants a guarantee that no chunk cuts mid-sentence or mid-tag (such as an ElevenLabs `<break time="Xs" />` tag). Chunks must not overlap.

**Default (automatic) chunking.** If `chunk_indexes` is omitted, the service falls back to its own splitting logic:

1. Walk the text, accumulating characters up to a safe threshold below the 10,000-character limit (default ~9,500, leaving headroom).
2. Rather than cutting at an arbitrary offset, back off to the nearest whitespace boundary so no word is split mid-token.
3. Repeat until the entire input is covered by a sequence of ordered `{start, end}` pairs.

Either way, the result is the same internal representation: an ordered list of chunk boundaries over `text`.

### 2. Synthesis

Each chunk is sent to ElevenLabs as a separate call to `/v1/text-to-speech/{voice_id}`, using the same `voice_id` and `voice_settings` for every chunk to keep the voice consistent across the merged output.

For multi-chunk requests, chunk seams also use ElevenLabs' **request stitching** (`previous_request_ids`/`next_request_ids`), which conditions each chunk's generation on the actual audio generated for its neighbors. This runs as two synthesis passes — a forward pass, then a correction pass covering every chunk but the last — so an N-chunk request costs roughly `2N-1` ElevenLabs API calls, not `N`. This requires logging/history enabled on the ElevenLabs account (the default) and isn't available on the `eleven_v3` model.

### 3. Merging

The mp3 bytes returned per chunk are stitched together using [`pydub`](https://github.com/jiaaro/pydub), which relies on `ffmpeg` for decoding/encoding and clean concatenation — avoiding the artifacts that can occur with naive byte-level concatenation of mp3 files. An optional short silence gap (`silence_between_chunks_ms`) can be inserted at each seam to smooth the transition between chunks.

The final output is returned as a single continuous mp3 file. From the caller's perspective, the 10,000-character limit is effectively transparent.

## Fork & Deploy

The intended way to use this project is to fork it on GitHub and deploy your own copy — you don't need to ask permission or share a hosted instance with anyone else.

### 1. Fork and configure

1. Fork [kraigochieng/elevenlabs-tts-chunker](https://github.com/kraigochieng/elevenlabs-tts-chunker) on GitHub.
2. Copy [`.env.example`](.env.example) to `.env` and fill in what you need. Everything in it is optional:
   - `ELEVENLABS_API_KEY` — a server-wide fallback key. Leave it unset if you'd rather have every caller supply their own via the `xi-api-key` header (see [Configuration](#configuration) below).
   - `DEFAULT_MAX_CHUNK_CHARS`, `LOG_LEVEL` — tuning knobs with sane defaults; see the comments in `.env.example`.

### 2. Deploy

Pick whichever fits your platform:

**Docker (recommended for most platforms).** The repo includes a multi-stage [`Dockerfile`](Dockerfile) that installs `ffmpeg` and runs as a non-root user:

```bash
docker build -t elevenlabs-tts-chunker .
docker run -p 8000:8000 -e ELEVENLABS_API_KEY=your_api_key_here elevenlabs-tts-chunker
```

This works as-is on any platform that runs a Docker image (Railway, Render, Fly.io, a plain VM, etc.) — just set your environment variables through that platform's usual mechanism.

**Vercel.** The repo includes [`Dockerfile.vercel`](Dockerfile.vercel) — a symlink to the same [`Dockerfile`](Dockerfile) used above. Vercel builds any `Dockerfile.vercel` it finds at the repo root into a container-backed Function instead of using its native Python runtime, which means `ffmpeg` is available exactly as it is in the plain Docker image, with no separate file to keep in sync.

1. Import the forked repo at [vercel.com/new](https://vercel.com/new) (or run `vercel` from the repo root).
2. Set `ELEVENLABS_API_KEY` (and any other overrides you want) under Project Settings → Environment Variables.
3. Deploy.

The container must listen on the port Vercel provides via the `PORT` env var — the `Dockerfile`/`Dockerfile.vercel` CMD already handles this, falling back to `8000` when `PORT` isn't set (e.g. plain `docker run`).

If you'd rather use Vercel's native Python runtime instead of the Docker path (e.g. `pyproject.toml`'s `[tool.vercel]` entrypoint targets that), delete or rename `Dockerfile.vercel` — but note that runtime is a serverless/managed environment rather than a full container, so it may not include `ffmpeg` out of the box, which multi-chunk requests need for audio merging.

**Anywhere else.** Any platform that can run a Python web process works, as long as `ffmpeg` is available on `PATH`. See [Requirements](#requirements) below for running it directly without Docker.

## Requirements

For running directly (without Docker):

- Python 3.11+ (the repo is pinned to 3.12 via `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- `ffmpeg` installed and available on `PATH` (required by `pydub`)
- An ElevenLabs API key — either configured on the server, or supplied by each caller via the `xi-api-key` header (see Configuration)

## Installation (local development)

```bash
git clone https://github.com/kraigochieng/elevenlabs-tts-chunker.git
cd elevenlabs-tts-chunker
uv sync
```

Install `ffmpeg`:
```bash
# macOS
brew install ffmpeg

# Debian/Ubuntu
apt install ffmpeg
```

## Configuration

`ELEVENLABS_API_KEY` is optional and acts as a fallback default. Set it as an environment variable:

```bash
export ELEVENLABS_API_KEY=your_api_key_here
```

Or via a `.env` file (see [`.env.example`](.env.example) for the full list of options):
```
ELEVENLABS_API_KEY=your_api_key_here
```

Any request can instead (or additionally) supply its own key via the `xi-api-key` header, same as ElevenLabs' own API — it takes precedence over the server default when present. If a request has neither, it gets a `401`. This lets the service run as a multi-tenant proxy with no server-wide key configured at all, if every caller brings their own.

## Running locally

```bash
uv run uvicorn elevenlabs_tts_chunker.main:app --reload --port 8000
```

The service will be available at `http://localhost:8000` — `GET /` there returns plain-text API docs generated live from the code, `GET /health` is a basic health check.

## API Reference

### `POST /v1/text-to-speech/{voice_id}`

Mimics the shape of ElevenLabs' own endpoint, with additional chunking-related fields.

#### Path parameters

| Name | Type | Description |
|---|---|---|
| `voice_id` | string | ElevenLabs voice ID to use for synthesis |

#### Headers

| Header | Required | Description |
|---|---|---|
| `xi-api-key` | No | Your own ElevenLabs API key, same as ElevenLabs' own API. Overrides the server's default key when present. Required if the server has no `ELEVENLABS_API_KEY` configured. |

#### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | Yes | Full text to synthesize, of any length |
| `model_id` | string | No | ElevenLabs model ID. Defaults to `eleven_multilingual_v2` |
| `language_code` | string | No | ISO 639-1 code to enforce a language. Ignored by `multilingual_v2` |
| `chunk_indexes` | array of `{start, end}` | No | Caller-supplied, non-overlapping chunk boundaries. If omitted, chunks are computed automatically |
| `voice_settings` | object | No | Passed through to ElevenLabs on every chunk (`stability`, `similarity_boost`, `style`, `use_speaker_boost`, `speed`) |
| `output_format` | string | No | ElevenLabs output format, e.g. `mp3_44100_128`. Defaults to `mp3_44100_128` |
| `apply_text_normalization` | string | No | `auto` \| `on` \| `off`. Defaults to `auto` |
| `silence_between_chunks_ms` | integer | No | Milliseconds of silence inserted at each chunk seam. Defaults to `300` |

#### Example request

```json
{
  "text": "Hi, I'm Robin with your top events for today's brief...\n\nStory 1: ...\n\nStory 2: ...",
  "voice_id": "wyWA56cQNU2KqUW4eCsI",
  "voice_settings": {
    "speed": 1.0
  }
}
```

With caller-supplied boundaries:

```json
{
  "text": "...",
  "voice_id": "wyWA56cQNU2KqUW4eCsI",
  "chunk_indexes": [
    { "start": 0, "end": 9200 },
    { "start": 9200, "end": 18100 }
  ]
}
```

#### Response

Returns the merged audio as a binary mp3 stream (`Content-Type: audio/mpeg`), with a `Content-Disposition` header suggesting a timestamped filename.

#### Errors

| Status | Meaning |
|---|---|
| `401` | No ElevenLabs API key available (no `xi-api-key` header, and no server-side `ELEVENLABS_API_KEY`) |
| `422` | Request validation error — empty `text`, or `chunk_indexes` out of bounds/overlapping |
| `502` | Upstream ElevenLabs API error on one of the chunk requests |

### Other endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Plain-text API docs, generated live from the request schema |
| `GET /docs` | Interactive Swagger UI, auto-generated by FastAPI |
| `GET /health` | `{"status": "ok", "api_key_loaded": bool}` — `api_key_loaded` reflects the server's default key only |

## Usage in n8n

1. Build your full `text` (and optionally your own `chunk_indexes`) in a Code node.
2. Point an HTTP Request node at your deployed instance's `/v1/text-to-speech/{voice_id}` endpoint instead of ElevenLabs' directly.
3. Set the HTTP Request node's response format to **File / Binary**.
4. The returned mp3 is already fully merged — no further concatenation step needed in your workflow.

## License

[MIT](LICENSE) — do whatever you like with this, including running it as your own commercial or private service. Attribution (keeping the copyright notice) is the only real obligation.
