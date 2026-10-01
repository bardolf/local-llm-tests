# Desktop – přepis řeči (GPU)

`ssh milan@192.168.1.10` (hostname **desktopium**, Fedora/sway, Radeon RX 6600 XT 8 GB). Bývá uspaný – probudit přes desktop-on-off.

## Co tam běží
- Projekt **`~/projects/llm`** (vlastní, spravuje ho Claude session na desktopu):
  - `engines/whisper.cpp` – `whisper-server` s **Vulkanem**, model `models/whisper/ggml-large-v3-turbo-q8_0.bin`,
    VAD `models/vad/ggml-silero-v6.2.0.bin`; poslouchá jen na `127.0.0.1:8206`, OpenAI-kompatibilní `/v1/audio/transcriptions`.
  - orchestrátor (`bin/ai status`) whisper spouští podle potřeby; klient `clients/localai.py`.
- Knihovna je namountovaná přes CIFS z NASu: **`/media/disks/disk3/audio/spoken`** (= serverové `/media/disk3/audio/spoken`),
  autofs, uid/gid milan. Úlohy z ní jen čtou.

## Úloha intro-outro
Kopie (snapshot) v `intro-outro/` – **zdroj pravdy je na desktopu** `~/projects/llm/jobs/intro-outro/`; obnovit `./sync.sh`.
- Pro každou knihu (adresář s audiem, CD1/CD2 sloučeny) VAD najde první/poslední řeč (přeskočí hudbu), přepíše ~60 s
  začátku a konce, přidá ID3 tagy 1. souboru (`probe_first`), označí `suspect`, odfiltruje halucinace.
- Výstup na desktopu `~/projects/llm/data/intro-outro.jsonl` (průběžně) a `intro-outro.json` (na konci běhu / po Ctrl+C).
  Klíč `book` = cesta relativně ke kořeni knihovny. Formát viz `intro-outro/README.md`.
- ~6 s/kniha; celá knihovna (3–4 tis. knih) ≈ 5–7 h. **Běh celé knihovny spuštěn 2026-10-01.**
- Stažení výsledků na server: `./sync.sh` → `../data/transcripts/`.

## Nové knihy – přepis je potřeba VYTVOŘIT
Hromadný běh pokrývá jen knihy, které už v knihovně jsou. Pro nové knihy (import) se přepis musí pustit zvlášť.
Plán:
1. zdroje importu dávat na NAS do `/media/disk3/audio/_import/` (mimo `spoken` → ABS je nevidí; desktop: `/media/disks/disk3/audio/_import/`),
2. přidat do `transcribe_intro_outro.py` volbu `--library` (teď je `LIBRARY` napevno) – **až doběhne celý běh**,
3. spouštět ze serveru: `ssh milan@192.168.1.10 'cd ~/projects/llm && jobs/intro-outro/transcribe_intro_outro.py --library /media/disks/disk3/audio/_import "Kniha" --out data/import.jsonl'`
   a výsledek stáhnout `scp`.
Nouzově (desktop nedostupný): `server/import/clips.py` + lokální faster-whisper na CPU (docs/IMPORT_POSTUP.md §4).

## Další nápady
- přepis celé knihy → dělení dlouhých souborů na kapitoly (Zaklínač 4 = 2 × 6 h),
- LLM krok nad přepisy: vytažení vypravěče/roku/vydavatele + oprava fonetických chyb („Timpanum“ → Tympanum).
