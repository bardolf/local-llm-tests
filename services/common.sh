# Společné cesty pro run skripty služeb. Načítá se přes `source`.
LLM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS="$LLM_ROOT/models"
LLAMA_BIN="$LLM_ROOT/engines/llama.cpp/build/bin"
WHISPER_BIN="$LLM_ROOT/engines/whisper.cpp/build/bin"
ESRGAN_DIR="$LLM_ROOT/engines/realesrgan"
UPSCAYL_DIR="$LLM_ROOT/engines/upscayl"

# Bez orchestrátoru poslouchá služba jen lokálně; orchestrátor předá port a host 127.0.0.1
# a ven vystavuje jen sám sebe.
HOST="${HOST:-127.0.0.1}"

# Vulkan: zařízení 0 = RX 6600 XT (RADV). llvmpipe (CPU Vulkan) nechceme.
export GGML_VK_VISIBLE_DEVICES=0
