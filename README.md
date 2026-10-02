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
| chat-long | Gemma 4 E4B, 1 slot, 64k kontext | dlouhé konverzace (`bin/ai talk`, web chat) | [services/chat](services/chat/) |
| **chat-big** | Qwen3.5 9B (`chat-big`, ~16 tok/s) | přesná extrakce a normalizace jmen | [services/chat](services/chat/) |
| **embed** | bge-m3 (1024 dim) | sémantické hledání, duplicity podle obsahu | [services/embed](services/embed/) |
| **translate** | Hunyuan-MT 7B / TranslateGemma 4B | překlad EN → CS (služba skládá prompt) | [services/translate](services/translate/) |
| **image** | Z-Image-Turbo (stable-diffusion.cpp) | generování obrázků, ~65 s / 1024² | [services/image](services/image/) |
| **vision** | Qwen3.5 9B / Gemma 4 E4B + mmproj | popis a čtení textu z obrázku (kontrola obálek) | [services/chat](services/chat/) |
| **upscale** | Siax (rychlý) / ATD (drobné písmo) + další | zvětšení malých obálek, HTTP i CLI | [services/upscale](services/upscale/) |
| vad | Silero VAD (CPU) | hranice kapitol podle ticha | [services/vad](services/vad/) |
| fingerprint | Chromaprint fpcalc (CPU) | stejná nahrávka v jiné verzi | [services/fingerprint](services/fingerprint/) |

Serverové služby (whisper, chat, embed, upscale) spouští **orchestrátor llama-swap** na portu **8100** podle pole
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
- **Upscale obálek:** `POST /upstream/upscale/upscale`, multipart `file` (jpg/png), volitelně `model`
  (`siax` výchozí ~3 s | `atd` drobné písmo ~8–16 s | `remacri`, `lsdir`, `x4plus`, `drct`, `hat`, `dat2`),
  `width` (cílová šířka; 4× AI a pak zmenšení) **nebo `min_side`** (cílová kratší strana – obálky: `min_side=1000`),
  `format` (jpg|png, výchozí jako vstup), `quality`.
  Odpověď = přímo obrázek, hlavičky `X-Upscale-Model`, `X-Upscale-Time-Ms`, `X-Upscale-Input`, `X-Upscale-Output`.
  Když je vstup už aspoň `width` široký, AI se přeskočí (`X-Upscale-Model: none`). Chyby: JSON `{"error": …}`.
  ```bash
  curl -s http://192.168.1.10:8100/upstream/upscale/upscale -F file=@cover.jpg -F model=atd -F width=1000 \
       -D hlavicky.txt -o cover_big.jpg
  ```
  `GET /upstream/upscale/models` – seznam modelů.
- **Vision (popis/kontrola obrázku, např. obálky):** `POST /v1/chat/completions`, `model=vision` (Qwen3.5 9B –
  přesné OCR i popis, ~20–40 s, ~6.5 GB → běží sám) nebo `vision-fast` (Gemma 4 E4B, ~17 s, drobné chyby v OCR).
  Obrázek jako `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,…"}}` v `content`. Vzor kontroly obálky
  proti očekávanému autorovi/názvu (JSON schema): [bench/cover_check.py](bench/cover_check.py).
- **Překlad:** `POST /upstream/translate/translate` s JSON `{"text": "…", "source": "en", "target": "cs"}`
  (nebo `"texts": [...]`, volitelně `"model": "hunyuan" | "translategemma"`) → `{"translation": "…", "model", "ms"}`.
  Výchozí Hunyuan-MT 7B (nejlepší kvalita), odstavce se zachovají. Detail: [services/translate](services/translate/).
- **Generování obrázků:** `POST /v1/images/generations` s `{"model": "image", "prompt": "…", "size": "1024x1024",
  "response_format": "b64_json"}` → PNG v base64; ~65 s. Text v obrázku umí i s diakritikou, ale může ho zopakovat/zkomolit
  → kontrolovat; nepsat do promptu slova, která nemají být vidět; místo „cover“ psát „full-bleed illustration“.
  Detail: [services/image](services/image/).
- **Konverzace:** server si historii nepamatuje – klient posílá celou historii v `messages`. Web chat s historií:
  `http://127.0.0.1:8100/upstream/chat-long/` (na desktopu; jiný model = jiný název v cestě), terminál: `bin/ai talk`.
  Kontext: `chat` 8k tokenů na konverzaci (4 sloty), `chat-long` 64k. Pozor: malé modely mají slabé znalosti
  o konkrétních knihách (Gemma o Saturninovi tvrdila „sci-fi“) – na práci s dodaným textem OK, na fakta ne.
- Python klient bez závislostí: [clients/localai.py](clients/localai.py) – `LocalAI("http://192.168.1.10:8100")`
  (`transcribe`, `chat`, `chat_json`, `embed`, `upscale`).
- První požadavek po pauze o 1–2 s pomalejší (načtení modelu); nečinné modely se po 10–15 min uvolní.

```bash
cd ~/projects/audiobooksprocessing/desktop
bin/ai status                      # co běží, kolik VRAM
bin/ai chat "Kdo napsal Babičku?"  # jednorázový dotaz (gemma4b)
bin/ai talk                        # konverzace s historií (chat-long: Gemma, 64k kontext); /reset /model /save
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
