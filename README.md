# Desktop – lokální AI služby na GPU

`ssh milan@192.168.1.10` (hostname **desktopium**, Fedora 44/sway, **Radeon RX 6600 XT 8 GB**, 24 vláken,
46 GB RAM). Bývá uspaný – probudit přes desktop-on-off.

Malé lokální modely jako podpora pro audioknihovnu: přepis řeči, úklid metadat přes LLM,
embeddingy, zvětšení obálek, dělení na kapitoly, otisky nahrávek. Všechno přes **Vulkan**
(Mesa RADV), ROCm není potřeba.

Na desktopu je tohle repo naklonované v **`~/projects/audiobooksprocessing`** a projekt běží přímo
z jeho `desktop/` (služba, config, příkazy ze serveru – vše s cestou `~/projects/audiobooksprocessing/desktop`).
Mimo git (`.gitignore`) jsou buildy `engines/` (~17 GB vč. PyTorch ROCm), modely `models/` (~17 GB)
a výstupy `data/`; postavit znovu: `docs/SETUP.md`. Před prací `git pull` (do repa commituje i server session).

Dřív se projekt jmenoval `~/projects/llm`; to je teď jen dočasný symlink pro zpětnou kompatibilitu a
počítá se s jeho smazáním. Venv `engines/torch-sr` má ve skriptech (`bin/pip`…) starou cestu → volat
přes `engines/torch-sr/bin/python -m pip`, `bin/python` funguje odkudkoli.

## Co je k dispozici

| služba | model | k čemu | kde |
|---|---|---|---|
| **whisper** | Whisper large-v3-turbo q8_0 + Silero VAD | přepis řeči (~7× realtime) | [services/whisper](services/whisper/) |
| **chat** | Gemma 4 E4B (`chat`, ~43 tok/s) | rychlý chat, volný text | [services/chat](services/chat/) |
| **chat-big** | Qwen3.5 9B (`chat-big`, ~16 tok/s) | přesná extrakce a normalizace jmen | [services/chat](services/chat/) |
| **embed** | bge-m3 (1024 dim) | sémantické hledání, duplicity podle obsahu | [services/embed](services/embed/) |
| upscale | 4x_NMKD-Siax_200k (+ 9 dalších) | zvětšení malých obálek (1–4 s) | [services/upscale](services/upscale/) |
| vad | Silero VAD (CPU) | hranice kapitol podle ticha | [services/vad](services/vad/) |
| fingerprint | Chromaprint fpcalc (CPU) | stejná nahrávka v jiné verzi | [services/fingerprint](services/fingerprint/) |

Serverové služby (whisper, chat, embed) spouští **orchestrátor llama-swap** na portu **8100** podle pole
`model` v requestu; co se nevejde do VRAM, vystřídá, nečinné po 10–15 min uvolní
([orchestrator/](orchestrator/)). Backendy poslouchají jen na `127.0.0.1`; port **8100 je ve firewallu
otevřený jen pro NAS 192.168.1.11** → ze serveru `http://192.168.1.10:8100` (OpenAI API).

### Volání ze serveru

```bash
curl -s http://192.168.1.10:8100/health                       # desktop vzhůru? (jinak probudit desktop-on-off)
curl -s http://192.168.1.10:8100/v1/audio/transcriptions \
  -F model=whisper -F file=@klip.mp3 -F language=cs \
  -F prompt="Autor, Název, Vypravěč" -F response_format=verbose_json   # text | json | srt | vtt
```

- `language=auto` pro neznámý jazyk (slovenské knihy); `prompt` = nápověda jmen, výrazně zlepší přepis jmen.
- Posílat krátké klipy (např. `server/import/clips.py`), ne celé knihy. Formát libovolný (server převádí ffmpegem).
- Chat: `POST /v1/chat/completions` s `model=chat` (Gemma 4, rychlý) / `chat-big` (Qwen3.5 9B, přesnější extrakce),
  JSON výstup přes `response_format: {"type":"json_schema",…}`. Embeddingy: `POST /v1/embeddings`, `model=embed`.
- Python klient bez závislostí: [clients/localai.py](clients/localai.py) – `LocalAI("http://192.168.1.10:8100")`.
- První požadavek po pauze o 1–2 s pomalejší (načtení modelu); nečinné modely se po 10–15 min uvolní.

```bash
cd ~/projects/audiobooksprocessing/desktop
bin/ai status                      # co běží, kolik VRAM
bin/ai chat "Kdo napsal Babičku?"  # chat (gemma4b)
bin/ai stt kniha.mp3 srt           # přepis
bin/ai embed "text"                # embedding
bin/ai unload                      # uvolnit GPU (sdílí se s lc0 – šachy z NASu)
bench/smoke.sh                     # test všeho
```

Klient pro skripty: [clients/localai.py](clients/localai.py) (jen standardní knihovna Pythonu).

## Knihovna

CIFS z NASu: **`/media/disks/disk3/audio/spoken`** (= serverové `/media/disk3/audio/spoken`), autofs,
uid/gid milan. Úlohy z ní **jen čtou**.

## Úloha intro-outro

[`jobs/intro-outro/`](jobs/intro-outro/) – pro každou knihu (adresář s audiem, CD1/CD2 sloučeny) VAD najde
první/poslední řeč (přeskočí hudbu), přepíše ~60 s začátku a konce (jazyk auto, nápověda „Autor, Název“),
přidá ID3 tagy 1. souboru (`probe_first`), odfiltruje halucinace, označí `suspect`.

- Výstup na desktopu `desktop/data/intro-outro.jsonl` (průběžně) a `intro-outro.json` (na konci běhu
  / po Ctrl+C). Klíč `book` = cesta relativně ke kořeni knihovny. Formát: `jobs/intro-outro/README.md`.
- Navazuje (hotové přeskočí, chybné zkusí znovu). ~5 s/kniha ve 2 vláknech; 2254 knih ≈ 3–4 h.
  **Běh celé knihovny spuštěn 2026-10-01.**
- **`desktop/data/intro-outro.jsonl` je v gitu** (jediný soubor z `data/`, viz `.gitignore`) → na serveru stačí
  `git pull`. `intro-outro.json` lze kdykoli vygenerovat `transcribe_intro_outro.py --export-only`.
  Alternativně `./sync.sh` → `../data/transcripts/` (bez gitu, přímo z desktopu).

### Nové knihy – přepis je potřeba VYTVOŘIT

Hromadný běh pokrývá jen knihy, které už v knihovně jsou. Pro nové knihy (import):
1. zdroje importu dávat na NAS do `/media/disk3/audio/_import/` (mimo `spoken` → ABS je nevidí; desktop:
   `/media/disks/disk3/audio/_import/`),
2. spouštět ze serveru (volba `--library` už existuje):
   `ssh milan@192.168.1.10 'cd ~/projects/audiobooksprocessing/desktop && jobs/intro-outro/transcribe_intro_outro.py --library /media/disks/disk3/audio/_import "Kniha" --out data/import.jsonl'`
   a výsledek stáhnout `scp` (`data/import.json`).

Nouzově (desktop nedostupný): `server/import/clips.py` + lokální faster-whisper na CPU (docs/IMPORT_POSTUP.md §4).

## Dokumentace

- [docs/PLAN.md](docs/PLAN.md) – architektura, rozhodnutí, otevřené otázky
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) – rychlosti, VRAM, kvalita chat modelů, paralelizace
- [docs/LOG.md](docs/LOG.md) – deník (co, kdy, proč)
- [docs/SETUP.md](docs/SETUP.md) – postavení od nuly (balíky, buildy, modely)

## Zjištění, která se hodí vědět

- Qwen3.5 je na Vulkanu/RDNA2 pomalý (kopírování rekurentního stavu) → výchozí chat je Gemma 4.
- Malé LLM **neznají série a pořadí dílů** (halucinují) – brát z databazeknih, LLM jen na párování/opravy.
- Whisperu výrazně pomáhá nápověda jmen (`prompt`); bez ní komolí jména („Chichlík“).
- Prvních ~30 s bývá hudba → Whisper halucinuje „Titulky vytvořil JohnyX“; proto VAD.
- LLM paralelně: 4 souběžné dotazy = 2× propustnost; whisper paralelně nezrychlí (GPU vytížená).
- Upscale: drobné ~10px písmo neobnoví spolehlivě žádný model – lepší dohledat větší obálku.

## Další nápady

- LLM krok nad přepisy: vytažení vypravěče/roku/vydavatele + oprava fonetických chyb („Timpanum“ → Tympanum).
- přepis celé knihy → dělení dlouhých souborů na kapitoly (Zaklínač 4 = 2 × 6 h).
