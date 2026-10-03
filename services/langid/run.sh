#!/usr/bin/env bash
# Rozpoznání jazyka audio stopy (server.py) – model `langid` v orchestrátoru. Sama GPU nedrží:
# VAD a ffmpeg na CPU, jazyk určuje whisper přes orchestrátor.
#   run.sh [port]
set -euo pipefail
source "$(dirname "$0")/../common.sh"
PORT="${1:-8108}"
exec python3 "$LLM_ROOT/services/langid/server.py" --host "$HOST" --port "$PORT"
