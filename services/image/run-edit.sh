#!/usr/bin/env bash
# Úprava obrázku podle instrukce (FLUX.2-klein 4B) – služba edit_server.py, model `image-edit` v orchestrátoru.
#   run-edit.sh [port]
set -euo pipefail
source "$(dirname "$0")/../common.sh"
PORT="${1:-8107}"
exec python3 "$LLM_ROOT/services/image/edit_server.py" --host "$HOST" --port "$PORT"
