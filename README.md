# lux-tts-open-tts

**English** · [中文](./README.zh.md)

An [Open TTS](https://github.com/OpenTTSGroup/open-tts-spec) compliant HTTP
service wrapping the [LuxTTS](https://github.com/ysharma3501/LuxTTS) zero-shot
voice-cloning engine behind an OpenAI-compatible API.

## Features

- **OpenAI-compatible** `POST /v1/audio/speech` — any OpenAI SDK works out of the box.
- **Zero-shot voice cloning** only. Reference audio + transcript pair (`<id>.wav` + `<id>.txt`) lives on a mounted directory; optional YAML metadata per voice.
- **One-shot upload cloning** via `POST /v1/audio/clone` (multipart).
- **Six audio formats**: `mp3` / `opus` / `aac` / `flac` / `wav` / `pcm`.
- **Engine-specific tuning**: `num_steps`, `guidance_scale`, `t_shift`, `duration` are accepted on both `/speech` and `/clone`.
- **Fixed sample rate per process**: 48 kHz by default, 24 kHz when `LUXTTS_RETURN_SMOOTH=true`.

**Capabilities matrix**:

| Capability | Supported |
|---|---|
| `clone` | ✓ |
| `streaming` | ✗ (upstream does not expose a streaming API) |
| `design` | ✗ |
| `languages` | ✗ |
| `builtin_voices` | ✗ |

## Quick Start (Docker)

```bash
docker pull ghcr.io/seancheung/lux-tts-open-tts:latest

mkdir -p voices cache
# Drop a reference pair into voices/ — see "Voice Directory" below.
# e.g. voices/alice.wav + voices/alice.txt

docker run --rm -p 8000:8000 --gpus all \
  -v "$(pwd)/voices:/voices:ro" \
  -v "$(pwd)/cache:/root/.cache" \
  ghcr.io/seancheung/lux-tts-open-tts:latest
```

No GPU? Append `-e LUXTTS_DEVICE=cpu` and drop `--gpus all`. First start downloads the LuxTTS weights (plus the bundled Whisper ASR checkpoint) to `/root/.cache`; subsequent starts reuse the cache.

Synthesize:

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello, world.","voice":"file://alice","response_format":"mp3"}' \
  --output out.mp3
```

## Configuration

All variables are overridable via `-e FOO=bar` or Compose `environment:`.

### Engine (`LUXTTS_*` prefix)

| Variable | Default | Description |
|---|---|---|
| `LUXTTS_MODEL` | `YatharthS/LuxTTS` | HuggingFace repo id or local directory. A local directory is used verbatim; anything else is resolved via `huggingface_hub.snapshot_download` (LuxTTS only supports HF). |
| `LUXTTS_DEVICE` | `auto` | `auto` / `cuda` / `cpu`. `auto` picks CUDA when available. |
| `LUXTTS_CUDA_INDEX` | `0` | GPU ordinal when multiple are present. |
| `LUXTTS_DTYPE` | `float32` | Engine only runs in fp32; field exists for spec parity. |
| `LUXTTS_CPU_THREADS` | `4` | ONNX Runtime thread count when running on CPU. |
| `LUXTTS_NUM_STEPS` | `4` | Default diffusion sampling steps (`[1, 64]`). |
| `LUXTTS_GUIDANCE_SCALE` | `3.0` | Default classifier-free guidance scale (`[0.0, 10.0]`). |
| `LUXTTS_T_SHIFT` | `0.5` | Default sampling temperature shift (`[0.0, 1.0]`). |
| `LUXTTS_PROMPT_DURATION` | `5.0` | Reference-audio crop length in seconds (`[0.5, 30.0]`). |
| `LUXTTS_PROMPT_RMS` | `0.001` | RMS normalisation target for the reference audio. |
| `LUXTTS_RETURN_SMOOTH` | `false` | `false` → 48 kHz output, `true` → 24 kHz. Fixed for the process lifetime; surfaced through `/healthz.sample_rate`. |
| `LUXTTS_USE_PROMPT_TEXT` | `true` | `true` → use the supplied transcript (`<id>.txt` on `/speech`, form field on `/clone`) and skip Whisper. `false` → let LuxTTS' bundled Whisper re-transcribe the reference audio (the upstream default behaviour). |
| `LUXTTS_PROMPT_CACHE_SIZE` | `16` | LRU cap for cached Vocos prompt features (keyed by path, mtime, duration, rms, and reference text). |

### Service-level (no prefix)

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | uvicorn bind address. |
| `PORT` | `8000` | uvicorn bind port. |
| `LOG_LEVEL` | `info` | uvicorn log level. |
| `VOICES_DIR` | `/voices` | Directory scanned for `<id>.wav` + `<id>.txt` pairs. |
| `MAX_INPUT_CHARS` | `8000` | Upper bound on the `input` field; exceeding returns 413. |
| `DEFAULT_RESPONSE_FORMAT` | `mp3` | Used when the request omits `response_format`. |
| `MAX_CONCURRENCY` | `1` | Inference requests allowed to run concurrently. |
| `MAX_QUEUE_SIZE` | `0` | `0` = unlimited queue. Exceeding returns 503. |
| `QUEUE_TIMEOUT` | `0.0` | `0` = wait forever. Otherwise return 503 after N seconds. |
| `MAX_AUDIO_BYTES` | `20971520` | Upper bound for `/v1/audio/clone` uploads (20 MiB). |
| `CORS_ENABLED` | `false` | `true` mounts a wide-open CORS middleware on every route. |

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Engine status, capabilities, concurrency snapshot. |
| `GET` | `/v1/audio/voices` | List file-cloning voices. |
| `GET` | `/v1/audio/voices/preview?id=<id>` | Stream the reference WAV back. |
| `POST` | `/v1/audio/speech` | Synthesize using a voice already on disk. |
| `POST` | `/v1/audio/clone` | One-shot upload + synthesize. |

### `POST /v1/audio/speech`

Request body: JSON.

| Field | Type | Default | Status | Notes |
|---|---|---|---|---|
| `model` | string | `null` | `ignored` | Accepted for OpenAI compatibility. |
| `input` | string | — | `required` | 1..`MAX_INPUT_CHARS` characters. |
| `voice` | string | — | `required` | Must use `file://<id>` form. Bare names return 422 (LuxTTS is clone-only). |
| `response_format` | enum | `mp3` | `supported` | `mp3` / `opus` / `aac` / `flac` / `wav` / `pcm`. |
| `speed` | float | `1.0` | `supported` | Clamped to `[0.25, 4.0]`. Forwarded to `generate_speech`. |
| `instructions` | string | `null` | `ignored` | LuxTTS has no instruct API; the field is accepted but discarded (a warning is logged when non-empty). |
| *(via voice)* `prompt_text` | string | — | `conditional` | Content of `<id>.txt`. Fed to the tokenizer verbatim when `LUXTTS_USE_PROMPT_TEXT=true` (default); discarded in favour of Whisper's own transcription when `LUXTTS_USE_PROMPT_TEXT=false`. |
| `num_steps` | int | `LUXTTS_NUM_STEPS` | `extension` | Diffusion steps, `[1, 64]`. |
| `guidance_scale` | float | `LUXTTS_GUIDANCE_SCALE` | `extension` | Classifier-free guidance, `[0.0, 10.0]`. |
| `t_shift` | float | `LUXTTS_T_SHIFT` | `extension` | Sampling temperature shift, `[0.0, 1.0]`. |
| `duration` | float | `LUXTTS_PROMPT_DURATION` | `extension` | Reference-audio crop length in seconds, `[0.5, 30.0]`. |

By default (`LUXTTS_USE_PROMPT_TEXT=true`) the reference transcript `<id>.txt` is fed to LuxTTS' tokenizer unchanged and participates in synthesis; Whisper is skipped. Setting `LUXTTS_USE_PROMPT_TEXT=false` reverts to the upstream behaviour where `process_audio()` runs Whisper on the reference WAV and discards the supplied transcript. The `<id>.txt` file is required either way so the voice can be listed per spec §6.

### `POST /v1/audio/clone`

Request body: `multipart/form-data`.

| Field | Type | Default | Status | Notes |
|---|---|---|---|---|
| `audio` | file | — | `required` | Reference clip. `wav` / `mp3` / `flac` / `ogg` / `opus` / `m4a` / `aac` / `webm`. `MAX_AUDIO_BYTES` cap (default 20 MiB). |
| `prompt_text` | string | — | `conditional` | Must be non-empty (spec §5.1). Fed to the tokenizer verbatim when `LUXTTS_USE_PROMPT_TEXT=true` (default); discarded in favour of Whisper's own transcription when `LUXTTS_USE_PROMPT_TEXT=false`. |
| `input` | string | — | `required` | 1..`MAX_INPUT_CHARS` characters. |
| `response_format` | string | `mp3` | `supported` | Same enum as `/speech`. |
| `speed` | float | `1.0` | `supported` | `[0.25, 4.0]`. |
| `instructions` | string | `null` | `ignored` | Same as `/speech`. |
| `model` | string | `null` | `ignored` | OpenAI compatibility. |
| `num_steps` | int | `LUXTTS_NUM_STEPS` | `extension` | `[1, 64]`. |
| `guidance_scale` | float | `LUXTTS_GUIDANCE_SCALE` | `extension` | `[0.0, 10.0]`. |
| `t_shift` | float | `LUXTTS_T_SHIFT` | `extension` | `[0.0, 1.0]`. |
| `duration` | float | `LUXTTS_PROMPT_DURATION` | `extension` | `[0.5, 30.0]`. |

The uploaded audio is streamed to a tempfile, consumed by the engine, and deleted afterwards — it is **not** persisted to `VOICES_DIR`.

## Voice Directory

`$VOICES_DIR` (default `/voices`) is scanned on every list/lookup. Each voice is a triple:

```
voices/
├── alice.wav          # required, reference audio (16 kHz+ WAV recommended, 5–15 s)
├── alice.txt          # required, UTF-8 transcript (kept for metadata display)
└── alice.yml          # optional, YAML metadata mapping
```

See the `metadata` guidance in [`http-api-spec.md` §4.2](https://github.com/OpenTTSGroup/open-tts-spec/blob/main/http-api-spec.md#42-get-v1audiovoices) for suggested keys (`name`, `gender`, `age`, `language`, `accent`, `tags`, `description`).

Mount the directory read-only: `-v ./voices:/voices:ro`.

## Development

```bash
# Install deps locally (mirrors docker/requirements.api.txt + engine subset).
python -m venv .venv && source .venv/bin/activate
pip install -r docker/requirements.api.txt
pip install --find-links https://k2-fsa.github.io/icefall/piper_phonemize.html \
  -r docker/requirements.engine.txt
pip install torch==2.7.1 torchaudio==2.7.1

# Run the API (with engine exposed via PYTHONPATH).
export PYTHONPATH="$PWD:$PWD/engine"
uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

Upstream engine source lives in `engine/` as a git submodule pinned to `github.com/ysharma3501/LuxTTS`. Upgrade via `git submodule update --remote engine` followed by an explicit commit.

---

Built to the [Open TTS specification](https://github.com/OpenTTSGroup/open-tts-spec).
