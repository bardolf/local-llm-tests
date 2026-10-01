# upscale – zvětšení obálek

- **Výchozí model `4x_NMKD-Siax_200k`** (viz srovnání níže) přes `upscayl-bin`
  (upscayl-ncnn 20251207, fork realesrgan-ncnn-vulkan) v `engines/upscayl/`.
- Modely v `engines/upscayl/models/`: `4x_NMKD-Siax_200k`, `remacri-4x`, `4xLSDIRplusC`,
  `4xNomos8kSC`, `high-fidelity-4x`, `ultrasharp-4x`, `ultramix-balanced-4x`,
  `upscayl-standard-4x`, `digital-art-4x` (zdroj: github.com/upscayl/upscayl `resources/models`
  a github.com/upscayl/custom-models).
- Původní `realesrgan-ncnn-vulkan` (2022) v `engines/realesrgan/`: `realesrgan-x4plus`,
  `realesrgan-x4plus-anime`, `realesr-animevideov3-x2/x3/x4`. Skript sám vybere binárku podle modelu.

```bash
./upscale.sh obalka.jpg                       # → obalka.x4.png (4×)
./upscale.sh obalka.jpg velka.jpg 800         # 4× a pak zmenšit na šířku 800 (lanczos)
./upscale.sh obalky_male/ obalky_velke/       # celý adresář najednou
ESRGAN_MODEL=remacri-4x ./upscale.sh obalka.jpg      # jiný model
ESRGAN_MODEL=realesrgan-x4plus ./upscale.sh obalka.jpg
FREE_GPU=1 ./upscale.sh ...                   # nejdřív uvolnit VRAM v orchestrátoru
```

## Naměřeno

- 200×200 → 800×800: **1.5 s** (vč. načtení modelu). První spuštění vůbec ~30 s (kompilace shaderů,
  pak cache v `~/.cache`).
- Bez `OMP_WAIT_POLICY=passive` pálí ncnn ~20 s CPU času (13 jader aktivně čeká) na 1.5 s práce;
  s ním 1.6 s CPU. Skript to nastavuje.

## VRAM

Real-ESRGAN si bere VRAM jen po dobu běhu (malé obrázky stovky MB). Když je načtený velký chat
model (qwen9b ≈ 6+ GB), může dojít paměť → `FREE_GPU=1`.

## Test na reálných obálkách (2026-10-01, výsledky v ~/tmp/obalky)

3 náhodné malé obálky z knihovny (3 z prvních 10 prověřených měly šířku < 400 px), x4plus,
2–5 s na obálku, srovnání s lanczos (`*-srovnani.jpg`: vlevo lanczos, vpravo ESRGAN):

| obálka | původní | výsledek |
|---|---|---|
| Vondruška – Mrtvý posel | 342×600 | **výborné** – ostré písmo, detail klíče i mostu |
| Světlá – Černý Petříček | 300×300 | velký titulek ostrý, malebné pozadí OK; **drobné písmo** („Karolina Světlá“, „čte…“) má artefakty |
| Clavell – Král Krysa | 354×550 | titulek ostrý, ale **rytina** (šrafování) se změnila v umělou síťovinu – lanczos je věrnější |

Závěr: x4plus je dobrý na fotky, malbu a velké písmo; kazí jemné textury (rytiny, kresby) a malý
text. Originály vždy ponechat; u kreseb zkusit `ESRGAN_MODEL=realesrgan-x4plus-anime` nebo zůstat
u lanczos. Vodoznaky v obálkách (Král Krysa) upscale samozřejmě neodstraní.

## Srovnání 10 modelů (2026-10-01, ~/tmp/obalky/modely)

Všechny modely na Radeonu 1–3.6 s na obálku (digital-art 1 s – malý model). Archy:
`1-arch-pismo.png` (drobné písmo Černý Petříček, zdroj ~10 px vysoké písmo) a
`2-arch-rytina.png` (rytina Král Krysa, originál je tiskový rastr z teček).

| model | drobné písmo („čte Vojtěch Hamerský“) | rytina / rastr | verdikt |
|---|---|---|---|
| lanczos (bez AI) | rozmazané, ale nic nevymýšlí | věrné, měkké | reference |
| realesrgan-x4plus | „čte Vojtěch Hamerský“, kostrbaté | ✗ vymyslí šikmou síťovinu | starý výchozí |
| ultrasharp-4x | ✗ „člo Vojlěch Hamerslty“ | – | nejhorší na text |
| high-fidelity-4x | měkké, blízko lanczos | ✗ síťovina | – |
| remacri-4x | „čto Vojtěch Hamerský“, čisté | ✓ zachová tečky | dobrý |
| 4xLSDIRplusC | čisté, „Karolina Světlá“ nejlepší | ✓ zachová tečky, srst | dobrý |
| **4x_NMKD-Siax_200k** | „čto Vojtěch Hamerský“, čisté | ✓ zachová tečky | **nový výchozí** |
| upscayl-standard, ultramix, digital-art, Nomos8kSC | střed, místy „Hamorský“ | – | – |

Pozn.: ~10 px písmo v originále **žádný model neobnoví spolehlivě** – informace tam není, GAN
tvary písmen dokresluje („čte“ → „čto“). Pro obálky s důležitým drobným textem je lepší dohledat
větší obálku online; upscale je až záloha.
