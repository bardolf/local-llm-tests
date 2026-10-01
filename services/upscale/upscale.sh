#!/usr/bin/env bash
# Zvětšení obálek – ESRGAN modely přes ncnn (Vulkan, Radeon).
#   upscale.sh vstup.jpg [výstup.jpg] [cílová_šířka]
#   upscale.sh adresář_vstup/ adresář_výstup/        # dávka (rychlejší – model se načte jednou)
#
# Výchozí model 4x_NMKD-Siax_200k (v testu nejvěrnější: drobné písmo i tiskový rastr), 4×.
# Jiný: ESRGAN_MODEL=remacri-4x | 4xLSDIRplusC | realesrgan-x4plus | … (seznam: README.md).
# Při zadání cílové šířky se výsledek
# zmenší ffmpegem (lanczos) – např. 200px × 4 = 800, ale chceš 1000 → spusť dvakrát nebo
# použij cílovou šířku menší než 4× vstup.
#
# FREE_GPU=1  → před spuštěním požádá orchestrátor o uvolnění všech modelů z VRAM.
set -euo pipefail
source "$(dirname "$0")/../common.sh"

IN="${1:?vstup}"
OUT="${2:-}"
WIDTH="${3:-}"
# OpenMP vlákna ncnn jinak aktivně čekají a pálí ~13 jader CPU naprázdno (20 s CPU na 1.5 s práce)
export OMP_WAIT_POLICY=passive
MODEL="${ESRGAN_MODEL:-4x_NMKD-Siax_200k}"

# Modely z upscayl (novější) běží přes upscayl-bin, původní Real-ESRGAN přes realesrgan-ncnn-vulkan.
if [[ -f "$UPSCAYL_DIR/models/$MODEL.param" ]]; then
  BIN="$UPSCAYL_DIR/upscayl-bin"; MDIR="$UPSCAYL_DIR/models"
elif [[ -f "$ESRGAN_DIR/models/$MODEL.param" ]]; then
  BIN="$ESRGAN_DIR/realesrgan-ncnn-vulkan"; MDIR="$ESRGAN_DIR/models"
else
  echo "neznámý model: $MODEL" >&2; exit 2
fi

if [[ "${FREE_GPU:-0}" == 1 ]]; then
  curl -sf -X POST "http://127.0.0.1:${LLAMA_SWAP_PORT:-8100}/api/models/unload" >/dev/null || true
fi

if [[ -d "$IN" ]]; then
  OUT="${OUT:?u dávky je výstupní adresář povinný}"
  mkdir -p "$OUT"
  exec "$BIN" -i "$IN" -o "$OUT" -n "$MODEL" -s 4 -g 0 -m "$MDIR" -f png
fi

if [[ -z "$OUT" ]]; then OUT="${IN%.*}.x4.png"; fi
TMP="$(mktemp --suffix=.png)"
trap 'rm -f "$TMP"' EXIT
"$BIN" -i "$IN" -o "$TMP" -n "$MODEL" -s 4 -g 0 -m "$MDIR" >/dev/null 2>&1
if [[ -n "$WIDTH" ]]; then
  ffmpeg -loglevel error -y -i "$TMP" -vf "scale=${WIDTH}:-2:flags=lanczos" -q:v 2 "$OUT"
else
  ffmpeg -loglevel error -y -i "$TMP" -q:v 2 "$OUT"
fi
echo "$OUT"
