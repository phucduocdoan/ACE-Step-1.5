# ACE-Step API Client Documentation

**Language / 语言 / 言語:** [English](API.md) | [中文](../zh/API.md) | [日本語](../ja/API.md)

---

This service provides an HTTP-based asynchronous music generation API.

**Basic Workflow**:
1. Call `POST /release_task` to submit a task and obtain a `task_id`.
2. Call `POST /query_result` to batch query task status until `status` is `1` (succeeded) or `2` (failed).
3. Download audio files via `GET /v1/audio?path=...` URLs returned in the result.

---

## Table of Contents

- [Authentication](#1-authentication)
- [Response Format](#2-response-format)
- [Task Status Description](#3-task-status-description)
- [Create Generation Task](#4-create-generation-task)
- [Batch Query Task Results](#5-batch-query-task-results)
- [Format Input](#6-format-input)
- [Get Random Sample](#7-get-random-sample)
- [List Available Models](#8-list-available-models)
- [Server Statistics](#9-server-statistics)
- [Download Audio Files](#10-download-audio-files)
- [Health Check](#11-health-check)
- [Environment Variables](#12-environment-variables)
- [CLI Clients (api_client.py / api_batch.py)](#14-cli-clients-api_clientpy--api_batchpy)
- [Training API](#training-api)

---

## 1. Authentication

The API supports optional API key authentication. When enabled, a valid key must be provided in requests.

### Authentication Methods

Two authentication methods are supported:

**Method A: ai_token in request body**

```json
{
  "ai_token": "your-api-key",
  "prompt": "upbeat pop song",
  ...
}
```

**Method B: Authorization header**

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Authorization: Bearer your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "upbeat pop song"}'
```

### Configuring API Key

Set via environment variable (this is the only method that currently works — see the warning below):

```bash
export ACESTEP_API_KEY=your-secret-key
python -m acestep.api_server
```

> **Known bug: `--api-key` on the server is silently ignored.** `acestep/api_server.py` calls `app = create_app()` at **module import time** (line 359), and `create_app()` reads `ACESTEP_API_KEY` from the environment at that point (line 193). `run_api_server_main()` in `acestep/api/server_cli.py` only sets `os.environ["ACESTEP_API_KEY"]` from the `--api-key` flag *after* that import has already happened (inside `main()`, which runs after `app` is built), so the key it sets is never seen by `create_app()`. `python -m acestep.api_server --api-key your-secret-key` starts the server with auth **disabled**, with no error or warning. Until this is fixed in code, set `ACESTEP_API_KEY` in the environment before launching the server, as shown above.

---

## 2. Response Format

All API responses use a unified wrapper format:

```json
{
  "data": { ... },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| `data` | any | Actual response data |
| `code` | int | Status code (200=success) |
| `error` | string | Error message (null on success) |
| `timestamp` | int | Response timestamp (milliseconds) |
| `extra` | any | Extra information (usually null) |

---

## 3. Task Status Description

Task status (`status`) is represented as integers:

| Status Code | Status Name | Description |
| :--- | :--- | :--- |
| `0` | queued/running | Task is queued or in progress |
| `1` | succeeded | Generation succeeded, result is ready |
| `2` | failed | Generation failed |

---

## 4. Create Generation Task

### 4.1 API Definition

- **URL**: `/release_task`
- **Method**: `POST`
- **Content-Type**: `application/json`, `multipart/form-data`, or `application/x-www-form-urlencoded`

### 4.2 Request Parameters

#### Parameter Naming Convention

The API supports both **snake_case** and **camelCase** naming for most parameters. For example:
- `audio_duration` / `duration` / `audioDuration`
- `key_scale` / `keyscale` / `keyScale`
- `time_signature` / `timesignature` / `timeSignature`
- `sample_query` / `sampleQuery` / `description` / `desc`
- `use_format` / `useFormat` / `format`

Additionally, metadata can be passed in a nested object (`metas`, `metadata`, or `user_metadata`).

#### Method A: JSON Request (application/json)

Suitable for passing only text parameters, or referencing audio file paths that already exist on the server.

**Basic Parameters**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `prompt` | string | `""` | Music description prompt (alias: `caption`) |
| `lyrics` | string | `""` | Lyrics content |
| `thinking` | bool | `false` | Whether to use 5Hz LM to generate audio codes (lm-dit behavior) |
| `vocal_language` | string | `"en"` | Lyrics language (en, zh, ja, etc.) |
| `audio_format` | string | `"mp3"` | Output format: `flac`, `mp3`, `opus`, `aac`, `wav`, `wav32` |

**Sample/Description Mode Parameters**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `sample_mode` | bool | `false` | Enable random sample generation mode (auto-generates caption/lyrics/metas via LM) |
| `sample_query` | string | `""` | Natural language description for sample generation (e.g., "a soft Bengali love song"). Aliases: `description`, `desc` |
| `use_format` | bool | `false` | Use LM to enhance/format the provided caption and lyrics. Alias: `format` |

**Multi-Model Support**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `model` | string | null | Select which DiT model to use (e.g., `"acestep-v15-turbo"`, `"acestep-v15-turbo-shift3"`). Use `/v1/models` to list available models. If not specified, uses the default model. |

**thinking Semantics (Important)**:

- `thinking=false`:
  - The server will **NOT** use 5Hz LM to generate `audio_code_string`.
  - DiT runs in **text2music** mode and **ignores** any provided `audio_code_string`.
- `thinking=true`:
  - The server will use 5Hz LM to generate `audio_code_string` (lm-dit behavior).
  - DiT runs with LM-generated codes for enhanced music quality.

> **Note:** The LM is **automatically skipped** for `cover`, `repaint`, and `extract` task types, even if `thinking=true` is set. These tasks work directly with source audio and do not benefit from LM planning. Setting `thinking=true` has no effect for these tasks. The LM is only used when the task type is `text2music`, `lego`, or `complete`.

**Metadata Auto-Completion (Conditional)**:

When `use_cot_caption=true` or `use_cot_language=true` or metadata fields are missing, the server may call 5Hz LM to fill the missing fields based on `caption`/`lyrics`:

- `bpm`
- `key_scale`
- `time_signature`
- `audio_duration`

User-provided values always win; LM only fills the fields that are empty/missing.

**Music Attribute Parameters**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `bpm` | int | null | Specify tempo (BPM), range 30-300 |
| `key_scale` | string | `""` | Key/scale (e.g., "C Major", "Am"). Aliases: `keyscale`, `keyScale` |
| `time_signature` | string | `""` | Time signature (2, 3, 4, 6 for 2/4, 3/4, 4/4, 6/8). Aliases: `timesignature`, `timeSignature` |
| `audio_duration` | float | null | Generation duration (seconds), range 10-600. Aliases: `duration`, `target_duration` |

**Audio Codes (Optional)**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `audio_code_string` | string or string[] | `""` | Audio semantic tokens (5Hz) for `llm_dit`. Alias: `audioCodeString` |

**Generation Control Parameters**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `inference_steps` | int | `8` | Number of inference steps. Turbo model: 1-20 (recommended 8). Base model: 1-200 (recommended 32-64). |
| `guidance_scale` | float | `7.0` | Prompt guidance coefficient. Only effective for base model. |
| `use_random_seed` | bool | `true` | Whether to use random seed |
| `seed` | int | `-1` | Specify seed (when use_random_seed=false) |
| `batch_size` | int | `2` | Batch generation count (max 8) |

**Advanced DiT Parameters**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `shift` | float | `3.0` | Timestep shift factor (range 1.0-5.0). Only effective for base models, not turbo models. |
| `infer_method` | string | `"ode"` | Diffusion inference method: `"ode"` (Euler, faster) or `"sde"` (stochastic). |
| `timesteps` | string | null | Custom timesteps as comma-separated values (e.g., `"0.97,0.76,0.615,0.5,0.395,0.28,0.18,0.085,0"`). Overrides `inference_steps` and `shift`. |
| `use_adg` | bool | `false` | Use Adaptive Dual Guidance (base model only) |
| `cfg_interval_start` | float | `0.0` | CFG application start ratio (0.0-1.0) |
| `cfg_interval_end` | float | `1.0` | CFG application end ratio (0.0-1.0) |

**5Hz LM Parameters (Optional, server-side)**:

These parameters control 5Hz LM sampling, used for metadata auto-completion and (when `thinking=true`) codes generation.

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `lm_model_path` | string | null | 5Hz LM checkpoint dir name (e.g. `acestep-5Hz-lm-0.6B`) |
| `lm_backend` | string | `"vllm"` | `vllm` or `pt` |
| `lm_temperature` | float | `0.85` | Sampling temperature |
| `lm_cfg_scale` | float | `2.5` | CFG scale (>1 enables CFG) |
| `lm_negative_prompt` | string | `"NO USER INPUT"` | Negative prompt used by CFG |
| `lm_top_k` | int | null | Top-k (0/null disables) |
| `lm_top_p` | float | `0.9` | Top-p (>=1 will be treated as disabled) |
| `lm_repetition_penalty` | float | `1.0` | Repetition penalty |

**LM CoT (Chain-of-Thought) Parameters**:

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `use_cot_caption` | bool | `true` | Let LM rewrite/enhance the input caption via CoT reasoning. Aliases: `cot_caption`, `cot-caption` |
| `use_cot_language` | bool | `true` | Let LM detect vocal language via CoT. Aliases: `cot_language`, `cot-language` |
| `constrained_decoding` | bool | `true` | Enable FSM-based constrained decoding for structured LM output. Aliases: `constrainedDecoding`, `constrained` |
| `constrained_decoding_debug` | bool | `false` | Enable debug logging for constrained decoding |
| `allow_lm_batch` | bool | `true` | Allow LM batch processing for efficiency |

**Edit/Reference Audio Parameters** (requires absolute path on server):

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `reference_audio_path` | string | null | Reference audio path (Style Transfer) |
| `src_audio_path` | string | null | Source audio path (Repainting/Cover) |
| `task_type` | string | `"text2music"` | Task type: `text2music`, `cover`, `repaint`, `lego`, `extract`, `complete` |
| `instruction` | string | auto | Edit instruction (auto-generated based on task_type if not provided) |
| `repainting_start` | float | `0.0` | Repainting start time (seconds) |
| `repainting_end` | float | null | Repainting end time (seconds), -1 for end of audio |
| `chunk_mask_mode` | string | `"auto"` | Chunk-mask control: `"explicit"` uses the repaint time range as a 0/1 mask; `"auto"` uses automatic chunk control. |
| `audio_cover_strength` | float | `1.0` | Cover strength (0.0-1.0). Lower values (0.2) for style transfer. |

#### Method B: File Upload (multipart/form-data)

Use this when you need to upload local audio files as reference or source audio.

In addition to supporting all the above fields as Form Fields, the following file fields are also supported:

- `reference_audio` or `ref_audio`: (File) Upload reference audio file
- `src_audio` or `ctx_audio`: (File) Upload source audio file

> **Note**: After uploading files, the corresponding `_path` parameters will be automatically ignored, and the system will use the temporary file path after upload.

### 4.3 Response Example

```json
{
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "queued",
    "queue_position": 1
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

### 4.4 Usage Examples (cURL)

**Basic JSON Method**:

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "upbeat pop song",
    "lyrics": "Hello world",
    "inference_steps": 8
  }'
```

**With thinking=true (LM generates codes + fills missing metas)**:

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "upbeat pop song",
    "lyrics": "Hello world",
    "thinking": true,
    "lm_temperature": 0.85,
    "lm_cfg_scale": 2.5
  }'
```

**Description-driven generation (sample_query)**:

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Content-Type: application/json' \
  -d '{
    "sample_query": "a soft Bengali love song for a quiet evening",
    "thinking": true
  }'
```

**With format enhancement (use_format=true)**:

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "pop rock",
    "lyrics": "[Verse 1]\nWalking down the street...",
    "use_format": true,
    "thinking": true
  }'
```

**Select specific model**:

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "electronic dance music",
    "model": "acestep-v15-turbo",
    "thinking": true
  }'
```

**With custom timesteps**:

```bash
curl -X POST http://localhost:8001/release_task \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "jazz piano trio",
    "timesteps": "0.97,0.76,0.615,0.5,0.395,0.28,0.18,0.085,0",
    "thinking": true
  }'
```

**File Upload Method**:

```bash
curl -X POST http://localhost:8001/release_task \
  -F "prompt=remix this song" \
  -F "src_audio=@/path/to/local/song.mp3" \
  -F "task_type=repaint" \
  -F "repainting_start=10" \
  -F "repainting_end=20" \
  -F "chunk_mask_mode=explicit"
```

---

## 5. Batch Query Task Results

### 5.1 API Definition

- **URL**: `/query_result`
- **Method**: `POST`
- **Content-Type**: `application/json` or `application/x-www-form-urlencoded`

### 5.2 Request Parameters

| Parameter Name | Type | Description |
| :--- | :--- | :--- |
| `task_id_list` | string (JSON array) or array | List of task IDs to query |

### 5.3 Response Example

```json
{
  "data": [
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": 1,
      "result": "[{\"file\": \"/v1/audio?path=...\", \"wave\": \"\", \"status\": 1, \"create_time\": 1700000000, \"env\": \"development\", \"prompt\": \"upbeat pop song\", \"lyrics\": \"Hello world\", \"metas\": {\"bpm\": 120, \"duration\": 30, \"genres\": \"\", \"keyscale\": \"C Major\", \"timesignature\": \"4\"}, \"generation_info\": \"...\", \"seed_value\": \"12345,67890\", \"lm_model\": \"acestep-5Hz-lm-0.6B\", \"dit_model\": \"acestep-v15-turbo\"}]"
    }
  ],
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

**Result Field Description** (result is a JSON string, after parsing contains):

| Field | Type | Description |
| :--- | :--- | :--- |
| `file` | string | Audio file URL (use with `/v1/audio` endpoint) |
| `wave` | string | Waveform data (usually empty) |
| `status` | int | Status code (0=in progress, 1=success, 2=failed) |
| `create_time` | int | Creation time (Unix timestamp) |
| `env` | string | Environment identifier |
| `prompt` | string | Prompt used |
| `lyrics` | string | Lyrics used |
| `metas` | object | Metadata (bpm, duration, genres, keyscale, timesignature) |
| `generation_info` | string | Generation info summary |
| `seed_value` | string | Seed values used (comma-separated) |
| `lm_model` | string | LM model name used |
| `dit_model` | string | DiT model name used |

### 5.4 Usage Example

```bash
curl -X POST http://localhost:8001/query_result \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id_list": ["550e8400-e29b-41d4-a716-446655440000"]
  }'
```

---

## 6. Format Input

### 6.1 API Definition

- **URL**: `/format_input`
- **Method**: `POST`

This endpoint uses LLM to enhance and format user-provided caption and lyrics.

### 6.2 Request Parameters

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `prompt` | string | `""` | Music description prompt |
| `lyrics` | string | `""` | Lyrics content |
| `temperature` | float | `0.85` | LM sampling temperature |
| `param_obj` | string (JSON) | `"{}"` | JSON object containing metadata (duration, bpm, key, time_signature, language) |

### 6.3 Response Example

```json
{
  "data": {
    "caption": "Enhanced music description",
    "lyrics": "Formatted lyrics...",
    "bpm": 120,
    "key_scale": "C Major",
    "time_signature": "4",
    "duration": 180,
    "vocal_language": "en"
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

### 6.4 Usage Example

```bash
curl -X POST http://localhost:8001/format_input \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "pop rock",
    "lyrics": "Walking down the street",
    "param_obj": "{\"duration\": 180, \"language\": \"en\"}"
  }'
```

---

## 7. Get Random Sample

### 7.1 API Definition

- **URL**: `/create_random_sample`
- **Method**: `POST`

This endpoint returns random sample parameters from pre-loaded example data for form filling.

### 7.2 Request Parameters

| Parameter Name | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `sample_type` | string | `"simple_mode"` | Sample type: `"simple_mode"` or `"custom_mode"` |

### 7.3 Response Example

```json
{
  "data": {
    "caption": "Upbeat pop song with guitar accompaniment",
    "lyrics": "[Verse 1]\nSunshine on my face...",
    "bpm": 120,
    "key_scale": "G Major",
    "time_signature": "4",
    "duration": 180,
    "vocal_language": "en"
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

### 7.4 Usage Example

```bash
curl -X POST http://localhost:8001/create_random_sample \
  -H 'Content-Type: application/json' \
  -d '{"sample_type": "simple_mode"}'
```

---

## 8. List Available Models

### 8.1 API Definition

- **URL**: `/v1/models`
- **Method**: `GET`

Returns a list of available DiT models loaded on the server.

### 8.2 Response Example

```json
{
  "data": {
    "models": [
      {
        "name": "acestep-v15-turbo",
        "is_default": true
      },
      {
        "name": "acestep-v15-turbo-shift3",
        "is_default": false
      }
    ],
    "default_model": "acestep-v15-turbo"
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

### 8.3 Usage Example

```bash
curl http://localhost:8001/v1/models
```

---

## 9. Initialize or Switch Models

### 9.1 API Definition

- **URL**: `/v1/init`
- **Method**: `POST`

Initialize or switch DiT and LM models on demand without restarting the server.

### 9.2 Request Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `model` | string | null | DiT model name to load (e.g., `"acestep-v15-base"`). If omitted, re-initializes the current model for the target slot. |
| `slot` | int (1-3) | 1 | Handler slot to initialize. Slots 2 and 3 require `ACESTEP_CONFIG_PATH2` / `ACESTEP_CONFIG_PATH3` to have been set at startup. |
| `init_llm` | bool | false | Whether to also initialize the LM in this request. |
| `lm_model_path` | string | null | LM model path override (e.g., `"acestep-5Hz-lm-1.7B"`). |

### 9.3 Response Example

```json
{
  "data": {
    "message": "Model initialization completed",
    "slot": 2,
    "loaded_model": "acestep-v15-base",
    "loaded_lm_model": null,
    "models": [
      {"name": "acestep-v15-base", "is_default": false, "is_loaded": true},
      {"name": "acestep-v15-turbo", "is_default": true, "is_loaded": true}
    ],
    "lm_models": [],
    "llm_initialized": false
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

### 9.4 Usage Examples

```bash
# Initialize default slot (slot 1)
curl -X POST http://localhost:8001/v1/init \
  -H 'Content-Type: application/json' \
  -d '{"model": "acestep-v15-base"}'

# Load a different model into slot 2
curl -X POST http://localhost:8001/v1/init \
  -H 'Content-Type: application/json' \
  -d '{"model": "acestep-v15-base", "slot": 2}'

# Initialize slot 1 with LM
curl -X POST http://localhost:8001/v1/init \
  -H 'Content-Type: application/json' \
  -d '{"model": "acestep-v15-turbo", "init_llm": true, "lm_model_path": "acestep-5Hz-lm-1.7B"}'
```

> **Note**: Slots 2 and 3 are only available when `ACESTEP_CONFIG_PATH2` / `ACESTEP_CONFIG_PATH3` environment variables were set before starting the server. Attempting to initialize an unavailable slot returns a `400` error.

---

## 10. Server Statistics

### 10.1 API Definition

- **URL**: `/v1/stats`
- **Method**: `GET`

Returns server runtime statistics.

### 10.2 Response Example

```json
{
  "data": {
    "jobs": {
      "total": 100,
      "queued": 5,
      "running": 1,
      "succeeded": 90,
      "failed": 4
    },
    "queue_size": 5,
    "queue_maxsize": 200,
    "avg_job_seconds": 8.5
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

### 10.3 Usage Example

```bash
curl http://localhost:8001/v1/stats
```

---

## 11. Download Audio Files

### 11.1 API Definition

- **URL**: `/v1/audio`
- **Method**: `GET`

Download generated audio files by path.

### 11.2 Request Parameters

| Parameter Name | Type | Description |
| :--- | :--- | :--- |
| `path` | string | URL-encoded path to the audio file |

### 11.3 Usage Example

```bash
# Download using the URL from task result
curl "http://localhost:8001/v1/audio?path=%2Ftmp%2Fapi_audio%2Fabc123.mp3" -o output.mp3
```

---

## 12. Health Check

### 12.1 API Definition

- **URL**: `/health`
- **Method**: `GET`

Returns service health status.

### 12.2 Response Example

```json
{
  "data": {
    "status": "ok",
    "service": "ACE-Step API",
    "version": "1.0"
  },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

---

## 13. Environment Variables

The API server can be configured using environment variables:

### Server Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ACESTEP_API_HOST` | `127.0.0.1` | Server bind host |
| `ACESTEP_API_PORT` | `8001` | Server bind port |
| `ACESTEP_API_KEY` | (empty) | API authentication key (empty disables auth) |
| `ACESTEP_API_WORKERS` | `1` | API worker thread count |

### Model Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ACESTEP_CONFIG_PATH` | `acestep-v15-turbo` | Primary DiT model path |
| `ACESTEP_CONFIG_PATH2` | (empty) | Secondary DiT model path (optional) |
| `ACESTEP_CONFIG_PATH3` | (empty) | Third DiT model path (optional) |
| `ACESTEP_DEVICE` | `auto` | Device for model loading |
| `ACESTEP_USE_FLASH_ATTENTION` | `true` | Enable flash attention |
| `ACESTEP_OFFLOAD_TO_CPU` | `false` | Offload models to CPU when idle |
| `ACESTEP_OFFLOAD_DIT_TO_CPU` | `false` | Offload DiT specifically to CPU |

### LM Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ACESTEP_INIT_LLM` | auto | Whether to initialize LM at startup (auto determines based on GPU) |
| `ACESTEP_LM_MODEL_PATH` | `acestep-5Hz-lm-0.6B` | Default 5Hz LM model |
| `ACESTEP_LM_BACKEND` | `vllm` | LM backend (vllm or pt) |
| `ACESTEP_LM_DEVICE` | (same as ACESTEP_DEVICE) | Device for LM |
| `ACESTEP_LM_OFFLOAD_TO_CPU` | `false` | Offload LM to CPU |

### Queue Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ACESTEP_QUEUE_MAXSIZE` | `200` | Maximum queue size |
| `ACESTEP_QUEUE_WORKERS` | `1` | Number of queue workers |
| `ACESTEP_AVG_JOB_SECONDS` | `5.0` | Initial average job duration estimate |
| `ACESTEP_AVG_WINDOW` | `50` | Window for averaging job duration |

### Cache Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ACESTEP_TMPDIR` | `.cache/acestep/tmp` | Temporary file directory |
| `TRITON_CACHE_DIR` | `.cache/acestep/triton` | Triton cache directory |
| `TORCHINDUCTOR_CACHE_DIR` | `.cache/acestep/torchinductor` | TorchInductor cache directory |

---

## 14. CLI Clients (api_client.py / api_batch.py)

`acestep/api_client.py` and `acestep/api_batch.py` are command-line clients for the `/release_task` / `/query_result` API described above: a single-job runner and a batch runner over a JSONL job file. Both require a running API server (see [Authentication](#1-authentication) above for the `--api-key` caveat).

### 14.1 Single Job: `api_client.py`

Submits one `/release_task`, polls `/query_result` until it finishes, and downloads the resulting audio.

```bash
# Basic text2music job
python -m acestep.api_client --base-url http://127.0.0.1:8001 \
  --prompt "upbeat pop song" --lyrics "Hello world" --audio-duration 120

# With LM thinking mode and an API key
python -m acestep.api_client --base-url http://127.0.0.1:8001 --api-key your-secret-key \
  --prompt "moody synthwave" --thinking --batch-size 4 --output-dir out/synthwave
```

Every flag comes from `build_arg_parser()` in `acestep/api_client.py`; run `python -m acestep.api_client --help` for the exhaustive, current list. Key behaviors:

- `--seed` accepts a single seed or a comma-separated list; setting it also forces `use_random_seed=false` in the payload.
- `--src-audio` is required when `--task-type` is `cover`, `cover-nofsq`, or `repaint`; `--repainting-end` is additionally required for `repaint`. These are enforced by `validate_args()` before any network call.
- `--no-download` prints the returned audio URLs instead of downloading them.
- `--timeout` (default `900`s) is how long this single job is allowed to poll before the client gives up and raises `TimeoutError`. `--poll-interval` (default `2`s) is the wait between polls.
- Exit code: `0` on success, `1` on any error (including timeout), with `error: ...` printed to stdout.

### 14.2 Batch: `api_batch.py`

Runs many jobs from a JSONL file through the same API, submitting new jobs as soon as the server frees up, and recording a resumable manifest.

```bash
python -m acestep.api_batch --base-url http://127.0.0.1:8001 \
  --jobs examples/batch_jobs.jsonl --output-dir out/batch1 --max-inflight 4
```

See [`examples/batch_jobs.jsonl`](../../examples/batch_jobs.jsonl) for a small, runnable job file.

#### Job file format

One JSON object per line (blank lines and lines starting with `#` are skipped). Every key is optional — anything not set on a job line falls back to the matching `--flag` given on the command line (e.g. jobs without `"inference_steps"` use the batch command's `--inference-steps`, default `8`).

**Job keys** — these are the `build_arg_parser()` dest names verbatim, not the API's snake_case/camelCase aliases (see [4.2](#42-request-parameters)): a job line with `"duration"` instead of `"audio_duration"` is rejected as an unknown field, it is not treated as an alias.

| Job key | Type | Default | Notes |
| :--- | :--- | :--- | :--- |
| `id` | string | auto-generated | See [Job IDs](#job-ids) below. Not passed through to the API payload. |
| `task_type` | string | `"text2music"` | One of `text2music`, `cover`, `cover-nofsq`, `repaint` |
| `prompt` | string | `""` | Music prompt/caption |
| `lyrics` | string | `""` | Lyrics text |
| `src_audio` | string (path) | `null` | Local file, required for `cover`/`cover-nofsq`/`repaint` |
| `reference_audio` | string (path) | `null` | Optional local reference audio file |
| `audio_duration` | float | `null` | Target duration in seconds |
| `batch_size` | int | `1` | Variations of this one job's prompt — see [batch_size vs. separate jobs](#batch_size-vs-separate-jobs) |
| `inference_steps` | int | `8` | Diffusion inference steps |
| `guidance_scale` | float | `7.0` | CFG scale |
| `thinking` | bool | `false` | Enable 5Hz LM thinking mode |
| `model` | string | `null` | Optional DiT model name |
| `audio_format` | string | `"mp3"` | `mp3`/`flac`/`wav`/`opus`/`aac`/`wav32` |
| `seed` | string/int | `null` | Seed or comma-separated seeds; also sets `use_random_seed=false` |
| `vocal_language` | string | `"en"` | Lyrics language code |
| `repainting_start` | float | `0.0` | Repaint region start (seconds) |
| `repainting_end` | float | `null` | Repaint region end (seconds); required for `repaint` |
| `repaint_mode` | string | `"balanced"` | `conservative`/`balanced`/`aggressive` |
| `repaint_strength` | float | `0.5` | Repaint strength |

**Command-line-only flags** — rejected inside a job line, because `run_batch` reads them from the top-level `args`, so a per-job override would be silently ignored otherwise: `base_url`, `api_key`, `output_dir`, `timeout`, `poll_interval`, `no_download` (`CLI_ONLY_FIELDS` in `acestep/api_batch.py`). A job line setting one of these fails to load with:

```
<jobs_path>:<line>: field(s) can only be set on the command line, not per job: <field, ...>
```

The batch-only flags `jobs`, `max_inflight`, `manifest`, `no_resume` (`BATCH_ONLY_FIELDS`) are likewise rejected per job, since they configure the runner itself, not a single job.

Any other unrecognized key fails with `<jobs_path>:<line>: unknown job field(s): <field, ...>`. Invalid JSON on a line fails with `<jobs_path>:<line>: invalid JSON: <reason>`.

#### Job IDs

- Set `"id"` explicitly to name a job. IDs must not contain `/` or `\`, and must be unique within the file — a duplicate raises `<jobs_path>:<line>: duplicate job id '<id>'`.
- If `"id"` is omitted, the ID is derived by hashing the job's own JSON content (`job-<8 hex chars>` from a SHA-256 of the sorted-key JSON, `auto_job_id()` in `acestep/api_batch.py`), not the line's position. This is deliberate: resume matches by job ID, and a positional ID like `job-0003` would silently rebind to a different job as soon as a line is inserted or removed above it. Content hashing keeps a job's identity attached to what it actually asks for; byte-identical lines get a `-2`, `-3`, ... suffix.
- IDs (explicit or auto) also become the filename prefix for downloaded audio and the `id` field in the manifest.

#### The manifest

Defaults to `<output-dir>/manifest.jsonl`, or `--manifest <path>`. One JSON object appended per completed/failed job, flushed immediately, so it is safe to read (or interrupt the batch) at any time. Fields per row: `id`, `prompt`, `status` (`"succeeded"`/`"failed"`), plus `task_id`, `files` (on success), or `error` (on failure).

On the next run, jobs whose manifest row has `status == "succeeded"` are skipped automatically (resume). Pass `--no-resume` to re-run everything, including previously succeeded jobs, ignoring the manifest.

#### Failure and stalls

- A job that fails to submit (HTTP error other than 429, malformed job, etc.) or whose task comes back with a non-success status is recorded as `"failed"` in the manifest and does not stop the batch.
- HTTP `429 Server busy: queue is full` is not a failure: the batch simply stops submitting until the queue has room.
- `--timeout` means something different in batch mode than for `api_client.py`: it is a **stall timeout** — the batch gives up on all currently in-flight jobs if *no job at all* completes within that many seconds (default `1800`s). This is unrelated to how long any individual job may sit in the queue behind others.
- Stalls are cumulative: after `MAX_CONSECUTIVE_STALLS` (3) consecutive stall windows with zero completions, the batch aborts entirely and fails every remaining pending job too, on the assumption the server is down or unresponsive rather than merely slow.

#### Exit codes

`0` if every job succeeded (or there was nothing left to do after resume); `1` if any job failed, or the jobs file failed to load (bad `--jobs` path, invalid JSON, bad `--max-inflight`); `130` on `Ctrl-C` (the manifest reflects whatever had completed so far, and a re-run resumes from it).

#### `--max-inflight`

Caps how many submitted-but-not-yet-finished jobs the batch keeps outstanding (default `8`). **This does not parallelize generation.** The server that `create_app()` builds runs a single worker (`WORKER_COUNT = int(os.getenv("ACESTEP_QUEUE_WORKERS", "1"))` in `acestep/api_server.py`), so every job is generated strictly serially on one GPU regardless of `--max-inflight`. Raising it only lets the batch keep more jobs queued server-side at once, which avoids repeatedly hitting HTTP 429 and re-submitting; it buys queue depth, not throughput.

#### `batch_size` vs. separate jobs

`batch_size: N` inside one job produces **N variations of that job's one prompt**, not N different songs — the LM/DiT generate `N` samples from the same `prompt`/`lyrics` in one task. It does not help you generate many different songs faster; for that, use one job per song and let the batch runner queue them.

Measured on this machine: 8 separate single-song jobs took 79.25s total (9.91 s/file); one job with `batch_size: 8` took ~16.4s (2.06 s/file) — about 4.8x faster per file. That speedup is specific to generating variations of one prompt. If you need many different songs, you get no such speedup from `batch_size`; running them as separate jobs through `api_batch.py` instead gains you queue automation, resume, and eliminating GPU idle time between jobs (roughly 6% here) — not a per-file speedup.

**Which should I use?**

| You want... | Use |
| :--- | :--- |
| Several *different* songs (different prompt/lyrics each) | One job per song in the JSONL file, `batch_size: 1` (default) |
| Several *variations* of the *same* prompt | One job, `batch_size: N` |

The server advertises `Max Batch Size (with LM): 8` at startup (`acestep/api/startup_model_init.py`), and the LM stage processes batches sequentially in chunks of `lm_batch_chunk_size` (default `8`, `acestep/inference.py:258`), so `batch_size` above 8 gains nothing even for the variations case. Worse, over REST it **fails outright**. Measured twice on this machine's 80 GB H100: `batch_size: 16` returned a failed task producing 0 files (peak VRAM only ~68 GB, so this is not an out-of-memory condition), while `batch_size: 8` succeeded in the same run. Nothing on the REST path clamps the request down to the advertised limit — the VRAM-based auto-reduce in `_vram_guard_reduce_batch` (`acestep/core/generation/handler/memory_utils.py:~155`) sizes the batch from currently-free VRAM rather than the GPU's tier limit, so on a large-VRAM GPU it does not shrink an oversized request. Only the Gradio UI clamps `batch_size`, via the slider's `maximum`. Keep `batch_size` at 8 or below when calling the REST API directly.

---

## Training API

The API server exposes endpoints for fine-tuning adapters from preprocessed tensor datasets. Training runs asynchronously in the background; use the status and stop endpoints to monitor and control training.

### LoRA Training

- **URL**: `/v1/training/start`
- **Method**: `POST`

Starts a LoRA training run. See the [LoRA Training Tutorial](LoRA_Training_Tutorial.md) for parameter details.

### LoKr Training

- **URL**: `/v1/training/start_lokr`
- **Method**: `POST`

Starts a LoKr (Kronecker) training run. LoKr is a faster alternative to LoRA that uses Kronecker decomposition.

**LoKr-specific parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `tensor_dir` | string | (required) | Directory with preprocessed tensors |
| `output_dir` | string | `"./lokr_output"` | Output directory for checkpoints |
| `lokr_linear_dim` | int | `64` | Linear dimension (1-256) |
| `lokr_linear_alpha` | int | `128` | Linear alpha (1-512) |
| `lokr_factor` | int | `-1` | Kronecker factor (-1 = auto, otherwise 1-8) |
| `lokr_decompose_both` | bool | `false` | Decompose both matrices |
| `lokr_use_tucker` | bool | `false` | Use Tucker decomposition |
| `lokr_use_scalar` | bool | `false` | Use scalar calibration |
| `lokr_weight_decompose` | bool | `true` | Enable DoRA mode |
| `learning_rate` | float | `0.03` | Learning rate |
| `train_epochs` | int | `500` | Training epochs |
| `train_batch_size` | int | `1` | Batch size |
| `gradient_accumulation` | int | `4` | Gradient accumulation steps |
| `save_every_n_epochs` | int | `5` | Checkpoint save frequency |
| `training_shift` | float | `3.0` | Timestep shift |
| `training_seed` | int | `42` | Random seed |
| `gradient_checkpointing` | bool | `false` | Trade speed for lower VRAM |

**Usage example:**

```bash
curl -X POST http://localhost:8001/v1/training/start_lokr \
  -H 'Content-Type: application/json' \
  -d '{
    "tensor_dir": "/path/to/tensors",
    "output_dir": "./lokr_output",
    "lokr_linear_dim": 64,
    "lokr_linear_alpha": 128,
    "learning_rate": 0.03,
    "train_epochs": 500
  }'
```

---

## Error Handling

**HTTP Status Codes**:

- `200`: Success
- `400`: Invalid request (bad JSON, missing fields)
- `401`: Unauthorized (missing or invalid API key)
- `404`: Resource not found
- `415`: Unsupported Content-Type
- `429`: Server busy (queue is full)
- `500`: Internal server error

**Error Response Format**:

```json
{
  "detail": "Error message describing the issue"
}
```

---

## Best Practices

1. **Use `thinking=true`** for best quality results with LM-enhanced generation.

2. **Use `sample_query`/`description`** for quick generation from natural language descriptions.

3. **Use `use_format=true`** when you have caption/lyrics but want LM to enhance them.

4. **Batch query task status** using the `/query_result` endpoint to query multiple tasks at once.

5. **Check `/v1/stats`** to understand server load and average job time.

6. **Use multi-model support** by setting `ACESTEP_CONFIG_PATH2` and `ACESTEP_CONFIG_PATH3` environment variables, then select with the `model` parameter.

7. **For production**, set `ACESTEP_API_KEY` to enable authentication and secure your API.

8. **For low VRAM environments**, enable `ACESTEP_OFFLOAD_TO_CPU=true` to support longer audio generation.
