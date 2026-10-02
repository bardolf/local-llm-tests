#!/usr/bin/env bash
# Generování obrázků přes stable-diffusion.cpp (sd-server, Vulkan) – model Z-Image-Turbo.
#   run.sh [port]
# API: POST /v1/images/generations {"prompt": "...", "size": "1024x1024"}  (OpenAI-kompatibilní)
#      + /sdapi/v1/txt2img (A1111) + web UI na /
# Výchozí parametry pro Z-Image-Turbo podle docs/z_image.md: 8 kroků, cfg 1.0.
set -euo pipefail
source "$(dirname "$0")/../common.sh"
PORT="${1:-8106}"
M="$MODELS/image"

# --offload-to-cpu  váhy v RAM, do VRAM jen právě používaná část (text enkodér → difuze → VAE)
# --diffusion-fa    flash attention v difuzním modelu (méně VRAM)
# --vae-tiling      VAE po dlaždicích – velké obrázky se vejdou
# -s -1             náhodný seed (jinak by stejný prompt dal vždy stejný obrázek)
exec "$LLM_ROOT/engines/stable-diffusion.cpp/build/bin/sd-server" \
  --listen-ip "$HOST" --listen-port "$PORT" \
  --diffusion-model "$M/z_image_turbo-Q4_K.gguf" \
  --llm "$M/Qwen3-4B-Instruct-2507-Q4_K_M.gguf" \
  --vae "$M/ae.safetensors" \
  --offload-to-cpu --diffusion-fa --vae-tiling \
  --steps "${IMAGE_STEPS:-8}" --cfg-scale 1.0 -s -1 \
  -W 1024 -H 1024 ${IMAGE_EXTRA_ARGS:-}
