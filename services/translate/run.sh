#!/usr/bin/env bash
# Překladová služba (server.py) – spouští ji orchestrátor jako model `translate`.
# Sama nic na GPU nedrží: skládá prompt a volá překladový model přes orchestrátor (translategemma / hunyuan-mt).
#   run.sh [port]
set -euo pipefail
source "$(dirname "$0")/../common.sh"
PORT="${1:-8105}"
exec python3 "$LLM_ROOT/services/translate/server.py" --host "$HOST" --port "$PORT"
