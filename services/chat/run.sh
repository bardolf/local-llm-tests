#!/usr/bin/env bash
# Chat LLM přes llama-server (Vulkan). OpenAI API: /v1/chat/completions
#   run.sh <varianta> [port]
# Varianty: qwen9b | qwen4b | gemma4b | gemma4b-long        – jen text (long = 1 slot, 64k kontext)
#           qwen9b-vision | gemma4b-vision                  – i obrázky (image_url v messages)
set -euo pipefail
source "$(dirname "$0")/../common.sh"

VARIANT="${1:?varianta: qwen9b | qwen4b | gemma4b | gemma4b-long | qwen9b-vision | gemma4b-vision}"
PORT="${2:-8101}"

SLOTS=4
MMPROJ=()   # prázdné = bez vision části
case "$VARIANT" in
  qwen9b)  MODEL="$MODELS/llm/Qwen3.5-9B-Q4_K_M.gguf";   CTX=16384 ;;  # 4k/slot – víc se s embed do 8 GB nevejde
  qwen4b)  MODEL="$MODELS/llm/Qwen3.5-4B-Q4_K_M.gguf";   CTX=32768 ;;
  gemma4b) MODEL="$MODELS/llm/gemma-4-E4B-it-Q4_0.gguf"; CTX=32768 ;;
  # dlouhá konverzace: jeden slot s 64k kontextem (Gemma 4 umí 128k; většina vrstev má posuvné okno → KV malá)
  gemma4b-long) MODEL="$MODELS/llm/gemma-4-E4B-it-Q4_0.gguf"; CTX=65536; SLOTS=1 ;;
  # vision: obrázek ~ stovky až ~1000 tokenů → 8k kontext; VRAM qwen9b-vision ~6.5 GB (běží sám),
  # gemma4b-vision ~4 GB. Kontrola obálek: qwen přesnější (OCR bez chyb), gemma rychlejší (bench/cover_check.py)
  qwen9b-vision)  MODEL="$MODELS/llm/Qwen3.5-9B-Q4_K_M.gguf";   CTX=8192;  SLOTS=1
                  MMPROJ=(--mmproj "$MODELS/llm/mmproj-Qwen3.5-9B-F16.gguf") ;;
  gemma4b-vision) MODEL="$MODELS/llm/gemma-4-E4B-it-Q4_0.gguf"; CTX=16384; SLOTS=2
                  MMPROJ=(--mmproj "$MODELS/llm/mmproj-gemma-4-E4B-it-Q8_0.gguf") ;;
  *) echo "neznámá varianta: $VARIANT" >&2; exit 2 ;;
esac
[[ ${#MMPROJ[@]} -eq 0 ]] && MMPROJ=(--no-mmproj)

# -ngl 999      všechny vrstvy na GPU
# -fa on        flash attention (méně VRAM na KV cache)
# -ctk/-ctv q8  KV cache v q8_0 → poloviční paměť proti f16, kvalita prakticky stejná
# -np 4         4 paralelní sloty (kontext se dělí: 32k/4 = 8k na dotaz). Naměřeno gemma4b:
#               1 souběžný 46 tok/s, 2 → 68, 4 → 92, 8 → 95 tok/s celkem → 4 stačí
# --no-mmproj   u textových variant bez vision části – šetří VRAM
# --reasoning   off = bez „přemýšlení“. Qwen3.5 jinak na jednoduchou otázku vygeneruje tisíce
#               tokenů úvah (naměřeno 5169 tok / 4.5 min na jednu větu). LLM_REASONING=on zapne.
exec "$LLAMA_BIN/llama-server" \
  --model "$MODEL" --alias "$VARIANT" \
  --host "$HOST" --port "$PORT" \
  -ngl 999 -fa on -c "$CTX" -np "${LLM_SLOTS:-$SLOTS}" \
  -ctk q8_0 -ctv q8_0 \
  "${MMPROJ[@]}" \
  --reasoning "${LLM_REASONING:-off}" \
  --jinja ${LLM_EXTRA_ARGS:-}
