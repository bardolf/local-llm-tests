#!/usr/bin/env bash
# HTTP služba upscale (server.py) – spouští ji orchestrátor jako model `upscale`.
#   run.sh [port]
# Běží v venvu engines/torch-sr (PIL + PyTorch ROCm pro velké modely; ncnn modely přes upscayl-bin).
set -euo pipefail
source "$(dirname "$0")/../common.sh"
PORT="${1:-8104}"
exec "$LLM_ROOT/engines/torch-sr/bin/python" "$LLM_ROOT/services/upscale/server.py" --host "$HOST" --port "$PORT"
