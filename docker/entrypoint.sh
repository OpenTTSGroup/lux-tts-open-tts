#!/usr/bin/env bash
set -euo pipefail

# Engine defaults (LUXTTS_* prefix)
: "${LUXTTS_MODEL:=YatharthS/LuxTTS}"
: "${LUXTTS_DEVICE:=auto}"
: "${LUXTTS_DTYPE:=float32}"

# Service-level defaults (no prefix; shared across engines)
: "${VOICES_DIR:=/voices}"
: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"
: "${LOG_LEVEL:=info}"
: "${CORS_ENABLED:=false}"
: "${PYTHONPATH:=/opt/api:/opt/api/engine}"

export LUXTTS_MODEL LUXTTS_DEVICE LUXTTS_DTYPE \
       VOICES_DIR HOST PORT LOG_LEVEL CORS_ENABLED PYTHONPATH

if [ "$#" -eq 0 ]; then
  exec uvicorn app.server:app --host "$HOST" --port "$PORT" --log-level "$LOG_LEVEL"
fi
exec "$@"
