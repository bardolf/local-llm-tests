#!/usr/bin/env bash
# Stáhne modely do models/. Idempotentní (curl -C - navazuje přerušené stahování).
#   fetch-models.sh              → stáhne vše ze seznamu, 4 soubory souběžně
#   fetch-models.sh one R F D    → jeden soubor (repo, soubor, cílový podadresář)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HF=https://huggingface.co

get() { # repo file target_dir
  local url="$HF/$1/resolve/main/$2" out="$ROOT/models/$3/$(basename "$2")"
  mkdir -p "$(dirname "$out")"
  if [[ -f "$out" && ! -f "$out.part" ]]; then echo "OK   $out"; return; fi
  echo "GET  $url"
  touch "$out.part"
  curl -sSfL --retry 5 -C - -o "$out" "$url" && rm -f "$out.part" && echo "DONE $out"
}

if [[ "${1:-}" == one ]]; then get "$2" "$3" "$4"; exit; fi

# repo                              soubor                           adresář
LIST='
ggml-org/whisper-vad                ggml-silero-v6.2.0.bin           vad
ggerganov/whisper.cpp               ggml-large-v3-turbo-q8_0.bin     whisper
unsloth/Qwen3.5-9B-GGUF             Qwen3.5-9B-Q4_K_M.gguf           llm
ggml-org/bge-m3-Q8_0-GGUF           bge-m3-q8_0.gguf                 embed
unsloth/Qwen3.5-4B-GGUF             Qwen3.5-4B-Q4_K_M.gguf           llm
ggml-org/gemma-4-E4B-it-GGUF        gemma-4-E4B-it-Q4_0.gguf         llm
Qwen/Qwen3-Embedding-0.6B-GGUF      Qwen3-Embedding-0.6B-Q8_0.gguf   embed
ggerganov/whisper.cpp               ggml-large-v3-turbo.bin          whisper
'
grep . <<<"$LIST" | xargs -P 4 -L 1 "$0" one
