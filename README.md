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
- Optional **caller-supplied chunk boundaries** (`chunk_indexes`) for full control over where splits happen, with overlap/bounds validation — see [Chunking Modes](#chunking-modes)
- **Automatic chunking fallback** when no boundaries are supplied
- Consistent `voice_id` / `voice_settings` applied across all chunks
- **Seam continuity via ElevenLabs request stitching** — each chunk is conditioned on the actual audio generated for its neighbors, not just surrounding text
- Audio merging via `pydub` (backed by `ffmpeg`) for clean, artifact-free concatenation
- Optional silence padding between merged chunks
- Returns a single finished mp3, regardless of how many chunks were needed internally
- **Bring-your-own-key support** — callers can supply their own ElevenLabs API key per request via the `xi-api-key` header, so this can run as a multi-tenant proxy with no server-wide key at all
- Self-documenting: `GET /` returns plain-text API docs generated live from the actual request schema

## Chunking Modes

There are two ways a request's chunk boundaries get decided — pick whichever fits what you're sending.

### Mode 1: Automatic chunking (default)

Send just `text` and omit `chunk_indexes`, and the service computes the boundaries for you:

1. Walk the text, accumulating characters up to a safe threshold below the 10,000-character limit (default ~9,500, configurable via `DEFAULT_MAX_CHUNK_CHARS`, leaving headroom).
2. Rather than cutting at an arbitrary offset, back off to the nearest whitespace boundary so no word is split mid-token.
3. Repeat until the entire input is covered by a sequence of ordered `{start, end}` pairs.

Text is only ever split when it's actually longer than that threshold. If your whole `text` already fits under it, it's sent as a single chunk — nothing is divided at all.

This is the easiest path — send your whole `text` and nothing else. Good default for a single continuous passage with no internal structure that matters.

### Mode 2: Manual chunking (`chunk_indexes`)

Supply your own list of `{start, end}` character offsets into `text` instead, and the service uses exactly those boundaries rather than computing its own. Chunks must not overlap, but gaps between them are fine (see the worked example below).

This only takes effect when it's actually needed: if your full `text` is already at or under the automatic-chunking threshold above, any `chunk_indexes` you supply are ignored — the request is treated as a single chunk instead (same as Mode 1), and this is logged explaining why. There's no point paying for extra ElevenLabs requests (and the request-stitching overhead that comes with multiple chunks) to split text that already fits in one call.

**Why you'd want this.** Automatic chunking is safe but has no idea about your content's structure — it just walks characters and backs off to the nearest whitespace. That's fine for one continuous passage, but it can go wrong for anything with real internal structure:

- It might split in the middle of a paragraph or section just because that's where the character threshold happened to land, even though a much more natural break point existed a sentence or two earlier.
- It has no concept of "these two paragraphs are unrelated." If your text is several distinct stories or sections concatenated together, automatic chunking may lump parts of two of them into one chunk — which can hurt prosody at the seam, since this service's chunk-seam continuity (ElevenLabs request stitching) keys off *your* boundaries. A boundary that doesn't correspond to a natural pause gives the stitching worse context to work with.
- It can't respect markup like an ElevenLabs `<break time="1s" />` tag — a whitespace boundary can still land inside one.
- It always maximizes chunk size (up to ~9,500 characters). If you want smaller, more predictable chunks — e.g. one per paragraph or per script section — you need to say so explicitly.

**A guide to chunking by paragraph.** The simplest reliable manual strategy is one chunk per paragraph (or per section, if your content is organized that way). Each chunk stays small, self-contained, and easy to read back and debug:

1. Decide your split points in the *original* text — usually the blank lines between paragraphs (`\n\n`), or your own section markers.
2. For each paragraph, find its `start` and `end` as character offsets **into the full `text` string you're sending**, not offsets relative to that paragraph alone.
3. Skip the separator characters (the blank line) between chunks — validation only requires that chunks don't overlap, not that they cover every character, so gaps are fine.
4. Keep your chunks in reading order (sorted by `start`) — synthesis happens in the order you supply them.

Here's that logic as a short helper (JavaScript, e.g. for an n8n Code node — see [Usage in n8n](#usage-in-n8n)):

```js
function paragraphsToChunkIndexes(text) {
  const chunks = [];
  let pos = 0;
  for (const paragraph of text.split("\n\n")) {
    const start = text.indexOf(paragraph, pos);
    const end = start + paragraph.length;
    chunks.push({ start, end });
    pos = end;
  }
  return chunks;
}
```

**Worked example.** This short passage is kept small purely so it's easy to read and hand-verify below — a real request this size (well under the ~9,500-character threshold) would actually have its `chunk_indexes` ignored per the note above. The offset mechanism itself works exactly the same at any length: it's just character positions into `text`.

Given this `text` — three short paragraphs:

```
Welcome to the daily brief. Here are today's top stories.

Story one: Local elections wrapped up last night with record turnout.

Story two: A new park opened downtown, drawing large crowds this weekend.
```

Splitting on the blank lines between paragraphs gives three chunks:

| Chunk | `start` | `end` | Text |
|---|---|---|---|
| 1 | 0 | 57 | "Welcome to the daily brief. Here are today's top stories." |
| 2 | 59 | 128 | "Story one: Local elections wrapped up last night with record turnout." |
| 3 | 130 | 203 | "Story two: A new park opened downtown, drawing large crowds this weekend." |

(Offsets `57`–`59` and `128`–`130` are the two-character `\n\n` separators between paragraphs — they're simply skipped, not assigned to any chunk.)

The corresponding request:

```json
{
  "text": "Welcome to the daily brief. Here are today's top stories.\n\nStory one: Local elections wrapped up last night with record turnout.\n\nStory two: A new park opened downtown, drawing large crowds this weekend.",
  "voice_id": "wyWA56cQNU2KqUW4eCsI",
  "chunk_indexes": [
    { "start": 0, "end": 57 },
    { "start": 59, "end": 128 },
    { "start": 130, "end": 203 }
  ]
}
```

Each row of the table above maps directly to one entry in `chunk_indexes` — that's the whole mechanism. At a length that actually needs splitting, each chunk gets synthesized separately and merged back into one mp3, same as in automatic mode.

## How it works

### 1. Synthesis

Each chunk (from whichever chunking mode was used) is sent to ElevenLabs as a separate call to `/v1/text-to-speech/{voice_id}`, using the same `voice_id` and `voice_settings` for every chunk to keep the voice consistent across the merged output.

For multi-chunk requests, chunk seams also use ElevenLabs' **request stitching** (`previous_request_ids`/`next_request_ids`), which conditions each chunk's generation on the actual audio generated for its neighbors. This runs as two synthesis passes — a forward pass, then a correction pass covering every chunk but the last — so an N-chunk request costs roughly `2N-1` ElevenLabs API calls, not `N`. This requires logging/history enabled on the ElevenLabs account (the default) and isn't available on the `eleven_v3` model.

### 2. Merging

The mp3 bytes returned per chunk are stitched together using [`pydub`](https://github.com/jiaaro/pydub), which relies on `ffmpeg` for decoding/encoding and clean concatenation — avoiding the artifacts that can occur with naive byte-level concatenation of mp3 files. An optional short silence gap (`silence_between_chunks_ms`) can be inserted at each seam to smooth the transition between chunks.

The final output is returned as a single continuous mp3 file. From the caller's perspective, the 10,000-character limit is effectively transparent.

## Fork & Deploy

The intended way to use this project is to fork it on GitHub and deploy your own copy — you don't need to ask permission or share a hosted instance with anyone else.

### 1. Fork and configure

1. Fork [kraigochieng/elevenlabs-tts-chunker](https://github.com/kraigochieng/elevenlabs-tts-chunker) on GitHub.
2. Copy [`.env.example`](.env.example) to `.env` and fill in what you need. Everything in it is optional:
   - `ELEVENLABS_API_KEY` — a server-wide fallback key. Any request can instead (or additionally) supply its own key via the `xi-api-key` header, same as ElevenLabs' own API — it takes precedence over this default when present. If a request has neither, it gets a `401`. Leave `ELEVENLABS_API_KEY` unset entirely to require every caller to bring their own key, running this as a multi-tenant proxy with no server-wide key at all.
   - `DEFAULT_MAX_CHUNK_CHARS`, `LOG_LEVEL` — tuning knobs with sane defaults; see the comments in `.env.example`.

### 2. Deploy

Pick whichever fits your platform:

**Docker (recommended for most platforms).** The repo includes a multi-stage [`Dockerfile`](Dockerfile) that installs `ffmpeg` and runs as a non-root user:

```bash
docker build -t elevenlabs-tts-chunker .
docker run -p 8000:8000 -e ELEVENLABS_API_KEY=your_api_key_here elevenlabs-tts-chunker
```

This works as-is on any platform that runs a Docker image (Railway, Render, Fly.io, a plain VM, etc.) — just set your environment variables through that platform's usual mechanism.

**Vercel.** Use the Docker path via [`Dockerfile.vercel`](Dockerfile.vercel) — Vercel's native Python runtime does not include `ffmpeg`, which multi-chunk requests need for audio merging, so it isn't a viable option for this project. `Dockerfile.vercel` is a Vercel-specific variant of [`Dockerfile`](Dockerfile), kept as its own file since Vercel Functions must listen on the port given via `$PORT` rather than a fixed one. Vercel builds any `Dockerfile.vercel` it finds at the repo root into a container-backed Function instead of using that native runtime, so `ffmpeg` is available exactly as it is in the plain Docker image.

1. Import the forked repo at [vercel.com/new](https://vercel.com/new) (or run `vercel` from the repo root).
2. Set `ELEVENLABS_API_KEY` (and any other overrides you want) under Project Settings → Environment Variables.
3. Deploy.

If you change the build steps in `Dockerfile`, mirror the change in `Dockerfile.vercel` too — they're two separate files, not a symlink, because their `CMD` genuinely differs.

**Anywhere else.** Any platform that can run a Python web process works, as long as `ffmpeg` is available on `PATH`. See [Local Development](#local-development) below for running it directly without Docker.

## Local Development

Requires Python 3.11+ (the repo is pinned to 3.12 via `.python-version`), [`uv`](https://docs.astral.sh/uv/), and `ffmpeg` on `PATH`.

```bash
git clone https://github.com/kraigochieng/elevenlabs-tts-chunker.git
cd elevenlabs-tts-chunker
uv sync

# ffmpeg — macOS
brew install ffmpeg
# ffmpeg — Debian/Ubuntu
apt install ffmpeg
```

Configure your `.env` as described in [Fork & Deploy](#fork--deploy) above, then run:

```bash
uv run uvicorn elevenlabs_tts_chunker.main:app --reload --port 8000
```

The service is now at `http://localhost:8000` — see [API Reference](#api-reference) below.

## API Reference

Launch the app (see [Local Development](#local-development) or [Fork & Deploy](#fork--deploy)), then visit:

- `GET /docs` — interactive Swagger UI, generated live from the code — try requests directly in the browser
- `GET /` — the same reference as plain text
- `GET /health` — basic health check (`{"status": "ok", "api_key_loaded": bool}`; `api_key_loaded` reflects the server's default key only)

Both docs endpoints are generated straight from the actual request schema, so they can't drift out of sync the way a hand-written reference here could. See [Chunking Modes](#chunking-modes) above for a worked example of the trickiest field (`chunk_indexes`).

## Usage in n8n

1. Build your full `text` (and optionally your own `chunk_indexes`) in a Code node.
2. Point an HTTP Request node at your deployed instance's `/v1/text-to-speech/{voice_id}` endpoint instead of ElevenLabs' directly.
3. Set the HTTP Request node's response format to **File / Binary**.
4. The returned mp3 is already fully merged — no further concatenation step needed in your workflow.

## License

[MIT](LICENSE) — do whatever you like with this, including running it as your own commercial or private service. Attribution (keeping the copyright notice) is the only real obligation.
