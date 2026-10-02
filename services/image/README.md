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

## Úprava obrázku podle instrukce – FLUX.2-klein 4B (`image-edit`)

„Udělej z fotky komiks / akvarel / kresbu“: [`edit_server.py`](edit_server.py) (model `image-edit`) spustí na každý
požadavek `sd-cli` s FLUX.2-klein 4B Q8_0 + text enkodér Qwen3-4B (na CPU) + VAE FLUX.2-small-decoder; fotka jde
jako **referenční obrázek** (`-r`), osoba se zachová.

```bash
curl -s http://192.168.1.10:8100/upstream/image-edit/edit -F file=@foto.jpg \
     -F prompt="Turn this photo into a comic book illustration of the same man: bold black ink outlines, flat vibrant colors, halftone dots. Keep his face, glasses, beard." \
     -F size=768 -D h.txt -o komiks.png        # → PNG, hlavičky X-Edit-Time-Ms / X-Edit-Size / X-Edit-Seed
bin/ai edit foto.jpg komiks.png "Turn this photo into …" [768]
LocalAI(url).edit_image("foto.jpg", "Turn this photo into …") → (PNG, hlavičky)
```

- Pole: `file`, `prompt` (anglicky), `size` = delší strana (výchozí 768, max 1024; poměr stran se zachová), `steps` (4), `seed`.
- **Naměřeno:** 768 px ~50 s (4 kroky × 9.5 s + načtení), 512 px ~25 s; VRAM špička ~6.3 GB (VAE při nedostatku
  sám přejde na dlaždice). Běží sám (matice `image_edit`).
- Kvalita (ukázky `bench/results/image-edit-20261002.jpg`): komiks i akvarel výborné, obličej, brýle, vousy
  i oblečení zachované.
- Hlídání: krok > 40 s → proces se ukončí (ochrana GPU, viz níže).

## ⚠ Pasti (2026-10-02)

- **img2img se Z-Image (sdapi `init_images`) shodil GPU**: kroky 36 s, pak „ggml_vulkan: device lost“ – jádro resetovalo
  výpočetní kanál (`amdgpu … ring comp_1.1.0 timeout … reset succeeded`). Desktop přežil, ale stable-diffusion.cpp byl
  pak ~6× pomalejší až do **restartu počítače**. → img2img se Z-Image nepoužívat; úpravy dělat přes `image-edit` (FLUX.2-klein).
- Z-Image vzorkuje ~55 s nezávisle na rozlišení (512 i 1024 px), i bez `--offload-to-cpu` → neefektivní operace na
  Vulkanu/RDNA2, ne paměť. FLUX.2-klein naopak s `--offload-to-cpu` 56 s/krok (model se nevejde a streamuje),
  bez offloadu s `--backend te=cpu` 9.5 s/krok.
