#!/usr/bin/env bash
# Embeddingy přes llama-server --embedding. OpenAI API: /v1/embeddings
#   run.sh <varianta> [port]
# Varianty: bge-m3 (1024 dim, 8k kontext) | qwen3-emb (1024 dim)
set -euo pipefail
source "$(dirname "$0")/../common.sh"

VARIANT="${1:?varianta: bge-m3 | qwen3-emb}"
PORT="${2:-8102}"

case "$VARIANT" in
  bge-m3)    MODEL="$MODELS/embed/bge-m3-q8_0.gguf";               POOL=cls  ;;
  qwen3-emb) MODEL="$MODELS/embed/Qwen3-Embedding-0.6B-Q8_0.gguf"; POOL=last ;;
  *) echo "neznámá varianta: $VARIANT" >&2; exit 2 ;;
esac

# -c 8192 -ub 8192: u embeddingů musí jeden vstup projít celý v jedné dávce
exec "$LLAMA_BIN/llama-server" \
  --model "$MODEL" --alias "$VARIANT" \
  --host "$HOST" --port "$PORT" \
  --embedding --pooling "$POOL" \
  -ngl 999 -c 8192 -b 8192 -ub 8192 -np 4 ${EMBED_EXTRA_ARGS:-}
