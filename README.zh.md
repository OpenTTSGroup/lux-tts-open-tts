# lux-tts-open-tts

[English](./README.md) · **中文**

把 [LuxTTS](https://github.com/ysharma3501/LuxTTS) 零样本语音克隆引擎封装成
符合 [Open TTS 规范](https://github.com/OpenTTSGroup/open-tts-spec) 的
OpenAI 兼容 HTTP 服务。

## 功能特性

- **OpenAI 兼容** 的 `POST /v1/audio/speech`,任何 OpenAI SDK 开箱即用。
- **仅支持零样本声音克隆**。参考音频 + 转录对(`<id>.wav` + `<id>.txt`)放在挂载目录中,可选 YAML 元数据。
- **一次性上传克隆** `POST /v1/audio/clone`(multipart)。
- **6 种音频格式**:`mp3` / `opus` / `aac` / `flac` / `wav` / `pcm`。
- **引擎特定调参**:`num_steps` / `guidance_scale` / `t_shift` / `duration` 在 `/speech` 与 `/clone` 都可覆盖默认。
- **进程内采样率固定**:默认 48 kHz,`LUXTTS_RETURN_SMOOTH=true` 时 24 kHz。

**能力矩阵**:

| 能力 | 支持 |
|---|---|
| `clone` | ✓ |
| `streaming` | ✗ (上游不提供流式 API) |
| `design` | ✗ |
| `languages` | ✗ |
| `builtin_voices` | ✗ |

## 快速开始(Docker)

```bash
docker pull ghcr.io/seancheung/lux-tts-open-tts:latest

mkdir -p voices cache
# 往 voices/ 放一对参考文件,参考下文"声音目录"
# 例如:voices/alice.wav + voices/alice.txt

docker run --rm -p 8000:8000 --gpus all \
  -v "$(pwd)/voices:/voices:ro" \
  -v "$(pwd)/cache:/root/.cache" \
  ghcr.io/seancheung/lux-tts-open-tts:latest
```

无 GPU 时追加 `-e LUXTTS_DEVICE=cpu`,并去掉 `--gpus all`。首次启动会把 LuxTTS 权重(以及内置的 Whisper ASR)下载到 `/root/.cache`,后续复用。

合成示例:

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"你好,世界。","voice":"file://alice","response_format":"mp3"}' \
  --output out.mp3
```

## 配置

所有变量都通过 `-e FOO=bar` 或 Compose `environment:` 覆盖。

### 引擎(`LUXTTS_*` 前缀)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LUXTTS_MODEL` | `YatharthS/LuxTTS` | HuggingFace repo id 或本地目录。本地目录直接使用;其他字符串通过 `huggingface_hub.snapshot_download` 拉取(LuxTTS 只支持 HuggingFace)。 |
| `LUXTTS_DEVICE` | `auto` | `auto` / `cuda` / `cpu`。`auto` 下有 GPU 走 CUDA,否则 CPU。 |
| `LUXTTS_CUDA_INDEX` | `0` | 多卡时指定 GPU 序号。 |
| `LUXTTS_DTYPE` | `float32` | 引擎仅支持 fp32;保留此字段仅为与规范对齐。 |
| `LUXTTS_CPU_THREADS` | `4` | CPU 推理时 ONNX Runtime 的线程数。 |
| `LUXTTS_NUM_STEPS` | `4` | 扩散步数默认值(`[1, 64]`)。 |
| `LUXTTS_GUIDANCE_SCALE` | `3.0` | 默认无分类器指导强度(`[0.0, 10.0]`)。 |
| `LUXTTS_T_SHIFT` | `0.5` | 默认采样温度偏移(`[0.0, 1.0]`)。 |
| `LUXTTS_PROMPT_DURATION` | `5.0` | 参考音频截取长度,秒(`[0.5, 30.0]`)。 |
| `LUXTTS_PROMPT_RMS` | `0.001` | 参考音频的 RMS 归一化目标。 |
| `LUXTTS_RETURN_SMOOTH` | `false` | `false` → 48 kHz 输出,`true` → 24 kHz。进程内固定,`/healthz.sample_rate` 反映当前值。 |
| `LUXTTS_USE_PROMPT_TEXT` | `true` | `true` → 直接用传入的转录(`/speech` 走 `<id>.txt`,`/clone` 走表单 `prompt_text` 字段)喂给 tokenizer,跳过 Whisper。`false` → 回退到上游默认,让 LuxTTS 内置的 Whisper 重新转写参考音频。 |
| `LUXTTS_PROMPT_CACHE_SIZE` | `16` | 缓存的 Vocos prompt 特征的 LRU 容量(按 路径/mtime/duration/rms/参考文本 组合键)。 |

### 服务级(无前缀)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` | `0.0.0.0` | uvicorn 绑定地址。 |
| `PORT` | `8000` | uvicorn 绑定端口。 |
| `LOG_LEVEL` | `info` | uvicorn 日志级别。 |
| `VOICES_DIR` | `/voices` | 扫描 `<id>.wav` + `<id>.txt` 的目录。 |
| `MAX_INPUT_CHARS` | `8000` | `input` 字段上限,超出返回 413。 |
| `DEFAULT_RESPONSE_FORMAT` | `mp3` | 请求未指定 `response_format` 时使用。 |
| `MAX_CONCURRENCY` | `1` | 允许同时执行的推理数。 |
| `MAX_QUEUE_SIZE` | `0` | `0` 表示队列不限;超出返回 503。 |
| `QUEUE_TIMEOUT` | `0.0` | `0` 表示无限等待;否则超时返回 503。 |
| `MAX_AUDIO_BYTES` | `20971520` | `/v1/audio/clone` 上传大小上限(20 MiB)。 |
| `CORS_ENABLED` | `false` | `true` 时对所有端点挂载开放式 CORS 中间件。 |

## API 参考

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/healthz` | 引擎状态、能力、并发快照 |
| `GET` | `/v1/audio/voices` | 列出文件克隆声音 |
| `GET` | `/v1/audio/voices/preview?id=<id>` | 回传参考 WAV |
| `POST` | `/v1/audio/speech` | 使用声音目录中的参考声音合成 |
| `POST` | `/v1/audio/clone` | 一次性上传 + 合成 |

### `POST /v1/audio/speech`

请求体:JSON。

| 字段 | 类型 | 默认 | 状态 | 说明 |
|---|---|---|---|---|
| `model` | string | `null` | `ignored` | 仅为 OpenAI 兼容而接受。 |
| `input` | string | — | `required` | 长度 `1..MAX_INPUT_CHARS`。 |
| `voice` | string | — | `required` | 必须 `file://<id>` 形式;裸名返回 422(LuxTTS 仅支持克隆)。 |
| `response_format` | enum | `mp3` | `supported` | `mp3` / `opus` / `aac` / `flac` / `wav` / `pcm`。 |
| `speed` | float | `1.0` | `supported` | 限定在 `[0.25, 4.0]`,透传给 `generate_speech`。 |
| `instructions` | string | `null` | `ignored` | LuxTTS 无指令 API;接受字段但不使用,非空时记录 warning。 |
| *(经由 voice 关联)* `prompt_text` | string | — | `conditional` | `<id>.txt` 的内容。`LUXTTS_USE_PROMPT_TEXT=true`(默认)时原样喂给 tokenizer 参与合成;`LUXTTS_USE_PROMPT_TEXT=false` 时被 Whisper 的自动转写覆盖。 |
| `num_steps` | int | `LUXTTS_NUM_STEPS` | `extension` | 扩散步数,`[1, 64]`。 |
| `guidance_scale` | float | `LUXTTS_GUIDANCE_SCALE` | `extension` | 无分类器指导强度,`[0.0, 10.0]`。 |
| `t_shift` | float | `LUXTTS_T_SHIFT` | `extension` | 采样温度偏移,`[0.0, 1.0]`。 |
| `duration` | float | `LUXTTS_PROMPT_DURATION` | `extension` | 参考音频截取长度,秒,`[0.5, 30.0]`。 |

默认情况(`LUXTTS_USE_PROMPT_TEXT=true`)下,`<id>.txt` 会被原样喂给 LuxTTS 的 tokenizer 并真正参与合成,跳过 Whisper。设置 `LUXTTS_USE_PROMPT_TEXT=false` 可回退到上游行为——此时 `process_audio()` 会用 Whisper 重新转写参考 WAV 并忽略传入的文本。无论哪种模式,`<id>.txt` 都必须存在,这是规范 §6 把音色列出来的硬性前提。

### `POST /v1/audio/clone`

请求体:`multipart/form-data`。

| 字段 | 类型 | 默认 | 状态 | 说明 |
|---|---|---|---|---|
| `audio` | file | — | `required` | 参考音频。接受 `wav` / `mp3` / `flac` / `ogg` / `opus` / `m4a` / `aac` / `webm`;大小受 `MAX_AUDIO_BYTES`(默认 20 MiB)限制。 |
| `prompt_text` | string | — | `conditional` | 规范要求非空(§5.1)。`LUXTTS_USE_PROMPT_TEXT=true`(默认)时直接喂给 tokenizer 参与合成;`LUXTTS_USE_PROMPT_TEXT=false` 时被 Whisper 的自动转写覆盖。 |
| `input` | string | — | `required` | 长度 `1..MAX_INPUT_CHARS`。 |
| `response_format` | string | `mp3` | `supported` | 与 `/speech` 相同。 |
| `speed` | float | `1.0` | `supported` | `[0.25, 4.0]`。 |
| `instructions` | string | `null` | `ignored` | 同 `/speech`。 |
| `model` | string | `null` | `ignored` | OpenAI 兼容。 |
| `num_steps` | int | `LUXTTS_NUM_STEPS` | `extension` | `[1, 64]`。 |
| `guidance_scale` | float | `LUXTTS_GUIDANCE_SCALE` | `extension` | `[0.0, 10.0]`。 |
| `t_shift` | float | `LUXTTS_T_SHIFT` | `extension` | `[0.0, 1.0]`。 |
| `duration` | float | `LUXTTS_PROMPT_DURATION` | `extension` | `[0.5, 30.0]`。 |

上传音频会写入临时文件供引擎使用,完成后删除——**不会**持久化到 `VOICES_DIR`。

## 声音目录

`$VOICES_DIR`(默认 `/voices`)在每次列表/查询时实时扫描。每个声音是一组三元文件:

```
voices/
├── alice.wav          # 必需,参考音频(推荐 16 kHz+ WAV, 5–15 秒)
├── alice.txt          # 必需,UTF-8 转录(仅用于元数据展示)
└── alice.yml          # 可选,YAML 元信息
```

可选建议键(`name` / `gender` / `age` / `language` / `accent` / `tags` / `description` 等)见 [`http-api-spec.md` §4.2](https://github.com/OpenTTSGroup/open-tts-spec/blob/main/http-api-spec.md#42-get-v1audiovoices)。

推荐以只读方式挂载:`-v ./voices:/voices:ro`。

## 本地开发

```bash
# 本地装依赖(与 docker/requirements.api.txt + 引擎子集一致)
python -m venv .venv && source .venv/bin/activate
pip install -r docker/requirements.api.txt
pip install --find-links https://k2-fsa.github.io/icefall/piper_phonemize.html \
  -r docker/requirements.engine.txt
pip install torch==2.7.1 torchaudio==2.7.1

# 通过 PYTHONPATH 暴露引擎
export PYTHONPATH="$PWD:$PWD/engine"
uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

引擎源码位于 `engine/` 子模块,pin 到 `github.com/ysharma3501/LuxTTS`。升级:`git submodule update --remote engine` 后显式 commit。

---

基于 [Open TTS 规范](https://github.com/OpenTTSGroup/open-tts-spec) 实现。
