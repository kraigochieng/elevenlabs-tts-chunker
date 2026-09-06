# elevenlabs-tts-chunker

A FastAPI wrapper for the [ElevenLabs Text-to-Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert). It handles text longer than ElevenLabs' 10,000-character limit for you.

Send it any amount of text. It splits the text into safe chunks, turns each chunk into speech with ElevenLabs, and joins the audio back into one mp3. You don't have to think about the character limit at all.

This project is meant to be **forked and run by you**: clone it, add your own ElevenLabs API key (or let your callers bring their own), and host it yourself. See [Fork & Deploy](#fork--deploy) below.

> Not affiliated with or endorsed by ElevenLabs. You'll need your own ElevenLabs account and API key, and using it means following [ElevenLabs' own Terms of Service](https://elevenlabs.io/terms-of-use).

## Why

ElevenLabs' `/v1/text-to-speech/{voice_id}` endpoint rejects any request where `text` is longer than 10,000 characters. For long content (briefs, articles, multi-part scripts), that means splitting the text into several requests yourself and joining the audio back together. You have to pick good split points, keep the voice settings the same across every call, and avoid glitches where the pieces meet.

This service does all of that for you. Its API looks a lot like ElevenLabs' own, so you can drop it into an existing pipeline (like an n8n workflow) with only small changes.

## Chunking Modes

There are two ways to decide where a request gets split. Pick whichever fits what you're sending.

### Mode 1: Automatic chunking (default)

Send just `text` and leave out `chunk_indexes`. The service works out the split points for you:

1. It reads through the text, counting characters up to a safe limit below ElevenLabs' 10,000-character cap (9,500 by default, set with `DEFAULT_MAX_CHUNK_CHARS`).
2. Instead of cutting at a random spot, it moves back to the nearest space so no word gets cut in half.
3. It repeats this until the whole text is covered by a list of `{start, end}` pairs, in order.

Text only gets split when it's longer than that limit. If your whole `text` already fits under it, it's sent as one single chunk. Nothing gets divided.

This is the simplest option: just send your `text` and nothing else. It's a good default for one continuous passage where the internal structure doesn't matter.

### Mode 2: Manual chunking (`chunk_indexes`)

Instead, you can give your own list of `{start, end}` character positions in `text`. The service uses exactly those, instead of working out its own. Chunks can't overlap, but gaps between them are fine (see the worked example below).

This only kicks in when it's actually needed. If your full `text` already fits under the automatic-chunking limit above, any `chunk_indexes` you send are ignored. The request is treated as one single chunk instead, the same as Mode 1, and the service logs why. There's no reason to pay for extra ElevenLabs requests, and the extra work of request stitching, when the text already fits in one call.

**Why you'd want this.** Automatic chunking is safe, but it knows nothing about your content's structure. It just counts characters and backs off to the nearest space. That's fine for one continuous passage, but it can go wrong when your text actually has structure:

- It might split in the middle of a paragraph or section, just because that's where the character count happened to land, even though a better break point was a sentence or two earlier.
- It doesn't know that two paragraphs are unrelated. If your text is several separate stories or sections joined together, automatic chunking might mix parts of two of them into one chunk. That can hurt the audio at the seam: this service keeps the audio smooth across chunks (ElevenLabs request stitching) by using *your* chunk boundaries as a guide, so a boundary that isn't a real pause gives it worse information to work with.
- It can't respect markup like an ElevenLabs `<break time="1s" />` tag. A space-based split can still land inside one.
- It always makes chunks as large as possible (up to ~9,500 characters). If you want smaller, more predictable chunks, like one per paragraph or one per script section, you have to set that up yourself.

**A guide to chunking by paragraph.** The simplest, most reliable manual approach is one chunk per paragraph (or per section, if that's how your content is organized). Each chunk stays small, stands on its own, and is easy to check later:

1. Choose your split points in the *original* text. Usually the blank lines between paragraphs (`\n\n`), or your own section markers.
2. For each paragraph, work out its `start` and `end` as character positions **in the full `text` string you're sending**, not positions within that paragraph alone.
3. Skip the blank-line characters between chunks. Validation only checks that chunks don't overlap. It doesn't require every character to be covered, so gaps are fine.
4. Keep your chunks in reading order, sorted by `start`. They're synthesized in the order you send them.

Here's that same logic as a short helper function (JavaScript, for example for an n8n Code node; see [Usage in n8n](#usage-in-n8n)):

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

**Worked example.** This example text is kept short so it's easy to read and check by hand. A real request this short (well under the ~9,500-character limit) would actually have its `chunk_indexes` ignored, as explained above. But the offset mechanism itself works the same at any length: it's just character positions in `text`.

Take this `text`, made of three short paragraphs:

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

(The gaps `57`–`59` and `128`–`130` are the two-character `\n\n` line breaks between paragraphs. They're just skipped, not part of any chunk.)

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

Each row in the table above is one entry in `chunk_indexes`. That's the whole idea. Once text is long enough to actually need splitting, each chunk is turned into speech separately and joined back into one mp3, just like in automatic mode.

## How it works

### 1. Synthesis

Each chunk, from whichever chunking mode was used, is sent to ElevenLabs as its own call to `/v1/text-to-speech/{voice_id}`. Every chunk uses the same `voice_id` and `voice_settings`, so the voice stays consistent across the merged output.

For requests with more than one chunk, the seams also use ElevenLabs' **request stitching** (`previous_request_ids`/`next_request_ids`). This lets each chunk build on the real audio already generated for its neighbors. It runs in two passes: a forward pass, then a correction pass that covers every chunk except the last. So a request with N chunks costs roughly `2N-1` ElevenLabs API calls, not `N`. This needs logging/history turned on for your ElevenLabs account, which is the default, and it doesn't work with the `eleven_v3` model.

### 2. Merging

The mp3 audio from each chunk is joined together using [`pydub`](https://github.com/jiaaro/pydub), which uses `ffmpeg` to decode, re-encode, and join the files cleanly. This avoids the glitches you get from just pasting mp3 files together byte by byte. You can also add a short silence gap (`silence_between_chunks_ms`) at each seam, to smooth out the transition between chunks.

The final result is one continuous mp3 file. As far as the caller is concerned, the 10,000-character limit doesn't exist.

## Fork & Deploy

The intended way to use this project is to fork it on GitHub and deploy your own copy. You don't need anyone's permission, and you don't need to share a hosted copy with anyone else.

### 1. Fork and configure

1. Fork [kraigochieng/elevenlabs-tts-chunker](https://github.com/kraigochieng/elevenlabs-tts-chunker) on GitHub.
2. Copy [`.env.example`](.env.example) to `.env` and fill in what you need. Everything in it is optional:
   - `ELEVENLABS_API_KEY`: a fallback key for the whole server. Any request can instead send its own key in the `xi-api-key` header, same as ElevenLabs' own API. A request's own key wins if both are set. If a request has neither, it gets a `401` error. Leave `ELEVENLABS_API_KEY` unset if you want every caller to bring their own key. That turns this into a shared proxy with no server-wide key at all.
   - `DEFAULT_MAX_CHUNK_CHARS`, `LOG_LEVEL`: settings with sensible defaults. See the comments in `.env.example` for details.

### 2. Deploy

Pick whichever fits your platform:

**Docker (recommended for most platforms).** The repo includes a multi-stage [`Dockerfile`](Dockerfile) that installs `ffmpeg` and runs as a non-root user:

```bash
docker build -t elevenlabs-tts-chunker .
docker run -p 8000:8000 -e ELEVENLABS_API_KEY=your_api_key_here elevenlabs-tts-chunker
```

This works as-is on any platform that can run a Docker image (Railway, Render, Fly.io, a plain VM, and so on). Just set your environment variables the usual way for that platform.

**Vercel.** Use the Docker path, via [`Dockerfile.vercel`](Dockerfile.vercel). Vercel's own Python runtime doesn't include `ffmpeg`, which multi-chunk requests need for merging audio, so that runtime won't work for this project. `Dockerfile.vercel` is a Vercel-specific version of [`Dockerfile`](Dockerfile). It's a separate file because Vercel Functions have to listen on the port given in `$PORT`, not a fixed one. If Vercel finds a `Dockerfile.vercel` at the root of your repo, it builds that into a container-backed Function instead of using its native runtime. That way, `ffmpeg` is available, just like in the plain Docker image.

1. Import the forked repo at [vercel.com/new](https://vercel.com/new) (or run `vercel` from the repo root).
2. Set `ELEVENLABS_API_KEY` (and any other overrides you want) under Project Settings → Environment Variables.
3. Deploy.

If you change the build steps in `Dockerfile`, make the same change in `Dockerfile.vercel`. They're two separate files, not one shared file, because their `CMD` line is actually different.

**Anywhere else.** Any platform that can run a Python web process will work, as long as `ffmpeg` is on `PATH`. See [Local Development](#local-development) below for running it without Docker.

## Local Development

You'll need Python 3.11 or newer (this repo is pinned to 3.12 in `.python-version`), [`uv`](https://docs.astral.sh/uv/), and `ffmpeg` on your `PATH`.

```bash
git clone https://github.com/kraigochieng/elevenlabs-tts-chunker.git
cd elevenlabs-tts-chunker
uv sync

# ffmpeg: macOS
brew install ffmpeg
# ffmpeg: Debian/Ubuntu
apt install ffmpeg
```

Set up your `.env` as described in [Fork & Deploy](#fork--deploy) above, then run:

```bash
uv run uvicorn elevenlabs_tts_chunker.main:app --reload --port 8000
```

The service is now running at `http://localhost:8000`. See [API Reference](#api-reference) below.

## API Reference

Start the app (see [Local Development](#local-development) or [Fork & Deploy](#fork--deploy)), then open:

- `GET /docs`: an interactive Swagger UI, built live from the code, where you can try requests right in your browser
- `GET /`: the same reference as plain text
- `GET /health`: a simple health check. Returns `{"status": "ok", "api_key_loaded": bool}`. `api_key_loaded` only reflects the server's default key.

Both of these are built straight from the real request schema, so they can't fall out of date the way a hand-written reference here could. See [Chunking Modes](#chunking-modes) above for a full example of the trickiest field, `chunk_indexes`.

## Usage in n8n

1. Build your full `text` (and optionally your own `chunk_indexes`) in a Code node.
2. Point an HTTP Request node at your deployed instance's `/v1/text-to-speech/{voice_id}` endpoint, instead of ElevenLabs' own.
3. Set the HTTP Request node's response format to **File / Binary**.
4. The mp3 you get back is already fully merged, so you don't need any extra step to join files in your workflow.

## License

[MIT](LICENSE). Do whatever you like with this, including running it as your own paid or private service. The only real requirement is keeping the copyright notice.
