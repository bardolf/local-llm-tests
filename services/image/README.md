# image – generování obrázků (Z-Image-Turbo)

[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (`engines/stable-diffusion.cpp`, build
s `-DSD_VULKAN=ON`) → `sd-server`; model **Z-Image-Turbo Q4_K** (Alibaba, 6B, 8 kroků) + text enkodér
Qwen3-4B-Instruct Q4_K_M + VAE `ae.safetensors` (z Comfy-Org/z_image_turbo – originál u FLUX.1-schnell je za přihlášením).
V orchestrátoru model `z-image` (alias `image`), TTL 5 min.

```bash
curl -s http://192.168.1.10:8100/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"model": "image", "prompt": "…", "size": "1024x1024", "response_format": "b64_json"}'
# → {"data": [{"b64_json": "<PNG>"}]}
bin/ai image "prompt" out.png [1024x1024]          # lokálně
LocalAI(url).image("prompt") → PNG bytes            # Python
```

## Naměřeno (2026-10-02)

- 1024×1024: **~65–70 s** (57 s sampling 8 kroků + 8 s VAE), 768×768 rychleji.
- VRAM špička **5.9 GB celkem** (baseline 1.2) díky `--offload-to-cpu`; po dokončení se uvolní (~1.5 GB).
  V matici běží jen s embeddingy a službou translate.

## Kvalita a pravidla pro prompt

Testy v `bench/results/image-20261002.jpg`:
- ilustrace bez textu – kvalitní, malebná (sluha s čajem v bouřce; drobná logická chyba: čaj venku v dešti),
- anglický nápis „THE SILENT FOREST / JOHN MILLER“ – **bezchybný**,
- český nápis – **diakritika správně** („Karolina Světlá“, „Černý Petříček“), ale slovo „Černý“ **zopakoval 2×**.

Pravidla:
- Text v obrázku umí, ale **vždy zkontrolovat** (vision model `vision`) – nebo generovat bez textu a nápis vsadit dodatečně.
- „no text“ turbo model (cfg 1.0) nerespektuje spolehlivě – **nepsat do promptu roky, jména a slova, která nemají být
  v obrázku** (prompt s „Dublin… in 1904“ → velký nápis „1904“).
- Slovo **„cover“ vede k mockupu** (obálka na bílém pozadí s rámečkem) → psát „full-bleed square illustration, edge to edge“.
- Náhodný seed (`-s -1`); stejný prompt dá pokaždé jiný obrázek.
