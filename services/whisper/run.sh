#!/usr/bin/env bash
# Přepis řeči přes whisper-server (Vulkan).
#   run.sh [varianta] [port]
# Varianty: turbo-q8 (výchozí, 874 MB) | turbo (f16, 1.6 GB)
#
# Endpoint: POST /v1/audio/transcriptions  (multipart: file=..., language=cs, response_format=json|text|srt|vtt|verbose_json)
# --convert: přijme libovolný formát (mp3, m4b, opus…) a převede přes ffmpeg na 16 kHz WAV.
set -euo pipefail
source "$(dirname "$0")/../common.sh"

VARIANT="${1:-turbo-q8}"
PORT="${2:-8103}"

case "$VARIANT" in
  turbo-q8) MODEL="$MODELS/whisper/ggml-large-v3-turbo-q8_0.bin" ;;
  turbo)    MODEL="$MODELS/whisper/ggml-large-v3-turbo.bin" ;;
  *) echo "neznámá varianta: $VARIANT" >&2; exit 2 ;;
esac

# WHISPER_VAD=0 vypne VAD: na souvislé řeči je přepis ~30 % rychlejší, ale v tichu/hudbě
# hrozí halucinace („Titulky vytvořil JohnyX“). Výchozí = zapnuto.
VAD_ARGS=(--vad --vad-model "$MODELS/vad/ggml-silero-v6.2.0.bin")
[[ "${WHISPER_VAD:-1}" == 0 ]] && VAD_ARGS=()

TMP="${XDG_RUNTIME_DIR:-/tmp}/whisper-server"
mkdir -p "$TMP"

# --vad: Silero VAD vystřihne ticho → méně halucinací na dlouhých nahrávkách
exec "$WHISPER_BIN/whisper-server" \
  --model "$MODEL" \
  --host "$HOST" --port "$PORT" \
  --inference-path /v1/audio/transcriptions \
  --language cs --threads 8 \
  --convert --tmp-dir "$TMP" \
  "${VAD_ARGS[@]}" \
  ${WHISPER_EXTRA_ARGS:-}
