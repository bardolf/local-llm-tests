# Instalace od nuly

Ověřeno na Fedora 44, RX 6600 XT, Mesa 26.2.3 (RADV). ROCm **není** potřeba.

## 1. Systémové balíky

```bash
sudo dnf install -y cmake ninja-build gcc-c++ git ccache ffmpeg \
  vulkan-headers vulkan-loader-devel vulkan-tools mesa-vulkan-drivers \
  glslc glslang glslang-devel spirv-headers-devel spirv-tools-devel \
  libcurl-devel openssl-devel chromaprint-tools
# volitelně pro testy: espeak-ng
```

Bez `glslc` a `spirv-headers-devel` Vulkan backend ggml nezkompiluje
(`Could not find a package configuration file provided by "SPIRV-Headers"`).

Kontrola GPU: `vulkaninfo --summary` → musí být `AMD Radeon RX 6600 XT (RADV NAVI23)`.

## 2. llama.cpp (chat + embeddingy)

```bash
cd engines
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -G Ninja -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DGGML_CCACHE=ON -DLLAMA_BUILD_TESTS=OFF \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON   # RUNPATH=$ORIGIN → binárky fungují i po přesunu adresáře
cmake --build build -j 20          # ~4 min
./build/bin/llama-server --list-devices   # → Vulkan0: AMD Radeon RX 6600 XT
```

## 3. whisper.cpp (přepis + VAD)

```bash
cd engines
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -G Ninja -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DGGML_CCACHE=ON \
  -DWHISPER_BUILD_TESTS=OFF -DWHISPER_FFMPEG=OFF -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON
cmake --build build -j 20
```

(`WHISPER_FFMPEG=OFF` – server převádí formáty přes externí `ffmpeg` s `--convert`.)

## 4. Real-ESRGAN (obálky)

```bash
mkdir -p engines/realesrgan && cd engines/realesrgan
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip
unzip realesrgan-ncnn-vulkan-20220424-ubuntu.zip && rm *.zip && chmod +x realesrgan-ncnn-vulkan
```

Novější modely (výchozí 4x_NMKD-Siax_200k) přes upscayl-ncnn:

```bash
mkdir -p engines/upscayl/models && cd engines/upscayl
curl -LO https://github.com/upscayl/upscayl-ncnn/releases/download/20251207-174704/upscayl-bin-20251207-174704-linux.zip
unzip upscayl-bin-*-linux.zip && rm upscayl-bin-*-linux.zip
ln -sfn upscayl-bin-20251207-174704-linux/upscayl-bin upscayl-bin && chmod +x upscayl-bin
for m in ultrasharp-4x high-fidelity-4x remacri-4x upscayl-standard-4x ultramix-balanced-4x digital-art-4x; do
  for e in param bin; do curl -sfL -o models/$m.$e https://raw.githubusercontent.com/upscayl/upscayl/main/resources/models/$m.$e; done; done
for m in 4xNomos8kSC 4xLSDIRplusC 4x_NMKD-Siax_200k; do
  for e in param bin; do curl -sfL -o models/$m.$e https://raw.githubusercontent.com/upscayl/custom-models/main/models/$m.$e; done; done
```

Velké transformerové modely (DRCT-L, HAT-L, DAT2, ATD) přes PyTorch + ROCm (venv ~15 GB):

```bash
python3 -m venv engines/torch-sr
engines/torch-sr/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.2
engines/torch-sr/bin/python -m pip install spandrel pillow numpy
# pozor: spandrel jinak natáhne torchvision z PyPI (neROCm) → „operator torchvision::nms does not exist“
B=https://github.com/Phhofm/models/releases/download
cd models/upscale
curl -LO $B/4xRealWebPhoto_v4_drct-l/4xRealWebPhoto_v4_drct-l.pth
curl -LO $B/4xNomos8kSCHAT/4xNomos8kSCHAT-L.safetensors
curl -LO $B/4xBHI_dat2_real/4xBHI_dat2_real.safetensors
curl -LO $B/4xNomosWebPhoto_atd/4xNomosWebPhoto_atd.safetensors
```

## 4b. stable-diffusion.cpp (generování obrázků)

```bash
cd engines && git clone --depth 1 --recursive --shallow-submodules https://github.com/leejet/stable-diffusion.cpp.git
cd stable-diffusion.cpp && cmake -S . -B build -G Ninja -DSD_VULKAN=ON -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DGGML_CCACHE=ON && cmake --build build -j 20
mkdir -p ../../models/image && cd ../../models/image
curl -LO https://huggingface.co/leejet/Z-Image-Turbo-GGUF/resolve/main/z_image_turbo-Q4_K.gguf
curl -LO https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
curl -LO https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors
```

## 5. llama-swap (orchestrátor)

```bash
mkdir -p engines/llama-swap && cd engines/llama-swap
curl -L https://github.com/mostlygeek/llama-swap/releases/download/v261/llama-swap_261_linux_amd64.tar.gz | tar xz
```

## 6. Modely

```bash
bin/fetch-models.sh      # ~17 GB, paralelně 4 soubory, dá se přerušit a pustit znovu
```

## 7. Spuštění

```bash
orchestrator/install.sh          # systemd --user služba, port 8100
bin/ai status
```

## Aktualizace enginů

```bash
cd engines/llama.cpp && git pull && cmake --build build -j 20
cd engines/whisper.cpp && git pull && cmake --build build -j 20
```

Pozor: llama.cpp občas mění/odstraňuje přepínače (např. `--no-mmap` už neexistuje,
nahrazen novým nastavením mmap s výchozím `auto`). Po aktualizaci spustit `bench/smoke.sh`.
