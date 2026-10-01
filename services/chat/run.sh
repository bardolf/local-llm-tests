#!/usr/bin/env bash
# Chat LLM přes llama-server (Vulkan). OpenAI API: /v1/chat/completions
#   run.sh <varianta> [port]
# Varianty: qwen9b | qwen4b | gemma4b
set -euo pipefail
source "$(dirname "$0")/../common.sh"

VARIANT="${1:?varianta: qwen9b | qwen4b | gemma4b}"
PORT="${2:-8101}"

case "$VARIANT" in
  qwen9b)  MODEL="$MODELS/llm/Qwen3.5-9B-Q4_K_M.gguf";   CTX=16384 ;;  # 4k/slot – víc se s embed do 8 GB nevejde
  qwen4b)  MODEL="$MODELS/llm/Qwen3.5-4B-Q4_K_M.gguf";   CTX=32768 ;;
  gemma4b) MODEL="$MODELS/llm/gemma-4-E4B-it-Q4_0.gguf"; CTX=32768 ;;
  *) echo "neznámá varianta: $VARIANT" >&2; exit 2 ;;
esac

# -ngl 999      všechny vrstvy na GPU
# -fa on        flash attention (méně VRAM na KV cache)
# -ctk/-ctv q8  KV cache v q8_0 → poloviční paměť proti f16, kvalita prakticky stejná
# -np 4         4 paralelní sloty (kontext se dělí: 32k/4 = 8k na dotaz). Naměřeno gemma4b:
#               1 souběžný 46 tok/s, 2 → 68, 4 → 92, 8 → 95 tok/s celkem → 4 stačí
# --no-mmproj   bez vision části – na úklid textu nepotřebujeme, šetří VRAM
# --reasoning   off = bez „přemýšlení“. Qwen3.5 jinak na jednoduchou otázku vygeneruje tisíce
#               tokenů úvah (naměřeno 5169 tok / 4.5 min na jednu větu). LLM_REASONING=on zapne.
exec "$LLAMA_BIN/llama-server" \
  --model "$MODEL" --alias "$VARIANT" \
  --host "$HOST" --port "$PORT" \
  -ngl 999 -fa on -c "$CTX" -np "${LLM_SLOTS:-4}" \
  -ctk q8_0 -ctv q8_0 \
  --no-mmproj \
  --reasoning "${LLM_REASONING:-off}" \
  --jinja ${LLM_EXTRA_ARGS:-}
