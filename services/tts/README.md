# tts – namluvení textu (XTTS v2)

Coqui **XTTS v2** (udržovaný fork `coqui-tts` 0.27.5), venv `engines/tts` (PyTorch 2.14.1+rocm7.2, GPU RX 6600),
model `models/tts` (1.8 GB). Umí češtinu, 58 vestavěných mluvčích (ženské např. *Claribel Dervla*, *Sofia Hellen*,
*Ana Florence*, *Daisy Studious*) nebo klonování hlasu z nahrávky 6–15 s (`--ref`).
Licence vah **CPML – jen nekomerční použití**.

```bash
engines/tts/bin/python services/tts/say.py -o out.wav -s "Claribel Dervla" --speed 0.9 "Dobrý den."
engines/tts/bin/python services/tts/say.py -o out.wav --ref vzorek.wav "Dobrý den."
```

- Emoce/tón nejde řídit parametrem – jen volbou mluvčího / referenční nahrávky a textem (výpustky `...` = pauzy,
  citoslovce „Mmm… Ach…“ model vysloví jako vzdech/zamručení).
- Rychlost: ~3–4 s výpočtu na 1 s zvuku (načtení modelu ~10 s); zatím není v orchestrátoru.
- Instalace: `transformers<5` (5.x nemá `isin_mps_friendly`), nutné `torchcodec`.
