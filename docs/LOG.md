# Deník

## 2026-10-01

- Průzkum stroje: RX 6600 XT 8 GB, RADV (Mesa 26.2.3), Vulkan 1.4 funguje (`vulkaninfo`).
  Kromě GPU je vidět i `llvmpipe` (CPU Vulkan) – při spouštění vybírat zařízení 0 (RADV).
- Doinstalováno: `glslc glslang glslang-devel libcurl-devel openssl-devel chromaprint-tools ccache`
  (glslc je nutný pro Vulkan build ggml).
- Naklonováno do `engines/`: llama.cpp `42d9581` (2026-10-01), whisper.cpp `6e4ab85` (2026-09-28).
- Build llama.cpp s `-DGGML_VULKAN=ON`: první pokus spadl na chybějícím `SPIRV-Headers` →
  doinstalováno `spirv-headers-devel spirv-tools-devel`. Pak OK (ggml 0.25.3, llama 0.5.0-dev).
  `llama-server --list-devices` → `Vulkan0: AMD Radeon RX 6600 XT (RADV NAVI23) (8192 MiB, 7709 MiB free)`.
- Orchestrátor: stažen **llama-swap v261** (2026-10-01) → `engines/llama-swap/llama-swap`.
- Real-ESRGAN: `realesrgan-ncnn-vulkan-20220424-ubuntu.zip` → `engines/realesrgan/` (binárka + modely
  x4plus, x4plus-anime, animevideov3). Na Fedoře běží bez dalších knihoven.
  - Test: 200×200 → 800×800, model `realesrgan-x4plus`, `-g 0` (RADV) = **1.6 s**.
    První běh trvá ~30 s (kompilace pipeline), pak cache.
- Výběr modelů (stav HF k 2026-10-01):
  - chat: `unsloth/Qwen3.5-9B-GGUF` Q4_K_M (5.68 GB) – hlavní kandidát
  - chat malý: `unsloth/Qwen3.5-4B-GGUF` Q4_K_M (2.74 GB) – vejde se vedle Whisperu
  - chat alt.: `ggml-org/gemma-4-E4B-it-GGUF` Q4_0 (4.59 GB) – porovnat češtinu
  - (gemma-4-12b Q4_0 má 6.7 GB – na 8 GB moc těsné, zatím ne)
  - embed: `ggml-org/bge-m3-Q8_0-GGUF` (635 MB), alt. `Qwen/Qwen3-Embedding-0.6B` Q8_0 (639 MB)
  - whisper: `ggml-large-v3-turbo-q8_0.bin` (874 MB) + plná f16 (1.6 GB) pro porovnání
  - VAD: `ggml-silero-v6.2.0.bin` (whisper.cpp má VAD vestavěný)
- Stahování přes `bin/fetch-models.sh` (~10 MB/s, celkem ~17 GB).
- Build whisper.cpp s Vulkanem (`-DGGML_VULKAN=ON -DWHISPER_FFMPEG=OFF`) – OK napoprvé
  (whisper 1.9.4; obsahuje i `parakeet-cli` a `whisper-vad-speech-segments`).
  - jfk.wav: správný přepis, 2.9 s celkem (cold). Model turbo-q8 = 874 MB ve VRAM.
  - Čeština: testovací vzorek z `espeak-ng -v cs` (doinstalováno; robotický hlas) – přepis
    čitelný, chyby odpovídají špatné výslovnosti espeaku. **Na stroji nejsou žádné audioknihy**
    (find přes celý disk) → reálný test až s daty ze serveru/NASu.
  - whisper-server: `--inference-path /v1/audio/transcriptions --convert --vad` → bere mp3/m4a
    rovnou, výstupy json/text/srt/vtt fungují.
- **Zjištění: tenhle stroj už sdílí GPU** – `lc0.socket` (port 3457) a `stockfish.socket` (3456),
  systemd socket activation, „chess relay z NASu“; firewall povoluje jen z **192.168.1.11** (NAS).
  lc0 při hledání bere VRAM (síť modelu). → při plánování VRAM počítat s rezervou.
  Pravděpodobně i audioknihovna je na NASu 192.168.1.11.
- Baseline VRAM bez našich modelů: **~1.2–1.3 GB obsazeno** (desktop). Pro modely tedy ~6.7 GB.
- Real-ESRGAN: ncnn bez `OMP_WAIT_POLICY=passive` spálí ~20 s CPU (aktivní čekání 13 vláken)
  na 1.5 s práce. S passive 1.6 s CPU, stejná rychlost. Nastaveno v `services/upscale/upscale.sh`.
- Napsány služby: `services/{chat,embed,whisper}/run.sh` (servery), `services/upscale/upscale.sh`,
  `services/vad/chapters.py`, `services/fingerprint/compare.py` (CLI). Všechny CLI otestovány
  na syntetických datech (viz README v adresářích).
- Orchestrátor: `orchestrator/config.yaml` (llama-swap, matrix router), port **8100**,
  backendy 8201+ jen na 127.0.0.1. Helper `bin/ai` (status/load/unload/chat/embed/stt/logs).
  - Ověřeno: `ai stt` → llama-swap nastartuje whisper (~1 s), přepis OK; whisper ≈ **0.8 GB VRAM**.
- Whisper rychlost: 12.9 min syntetické CZ řeči za 109 s (server, VAD) = ~7× realtime.
  Encoder 2.0 s / 30s okno (q8_0); f16 je **pomalejší** (2.7 s) → zůstává q8_0.
  Bez VAD ~30 % rychlejší. Přidán přepínač `WHISPER_VAD=0`.
- ⚠ whisper-cli `--vad` + `-nt` → celý výstup halucinace „Titulky vytvořil JohnyX.“. Server OK.
- Whisper `prompt` s jmény (autor, postavy, vypravěč, vydavatel) výrazně zlepší přepis jmen.
- `--no-mmap` v aktuálním llama.cpp neexistuje (embed server padal „invalid argument“) → odstraněno.
- Embeddingy bge-m3 přes orchestrátor OK: 1024 dim; „Krev elfů“ CZ↔EN 0.78, nesouvisející 0.29.
- **Chat – první test Qwen3.5-4B: 4.5 min na jednu větu** – model „přemýšlel“ 5169 tokenů.
  → `--reasoning off` jako výchozí v `services/chat/run.sh` (LLM_REASONING=on zapne). Pak 4.7 s.
- **llama-bench (Vulkan, fa=1):**
  | model | pp512 | tg128 |
  |---|---|---|
  | Qwen3.5-4B Q4_K_M | 783 | 18.8 |
  | Gemma-4-E4B Q4_0 | 856 | **49.5** |
  | Qwen3.5-9B Q4_K_M | 371 | 15.9 |
  Qwen3.5 je na Vulkanu/RDNA2 pomalý: `GGML_VK_PERF_LOGGER=1` ukázal, že z 28.9 ms/token jde
  15.6 ms na `CPY` + `GET_ROWS` rekurentního stavu (Gated DeltaNet vrstvy) při ~13 GB/s.
  Graph splits = 2 (nic neběží na CPU), vynucení vysokých taktů GPU nepomohlo (18.95).
  → upstream problém llama.cpp Vulkan backendu; sledovat novější buildy.
- Chat eval (bench/results/chat-20261001-1655.md): gemma4b nejrychlejší a nejméně halucinuje;
  Qwen modely si vymýšlejí série. → alias `chat` = gemma4b, `chat-big` = qwen9b.
- VRAM: gemma4b 2.8 GB, qwen4b 2.8, qwen9b 5.0; gemma+embed+whisper = 5.44 GB celkem;
  qwen9b+embed = 6.85 GB. Matice v config.yaml odpovídá.
- Zpřesněné prompty v `clients/localai.py` (vypravěč po „čte“, diakritika vždy, název bez série)
  + Whisper `prompt` s jmény → qwen9b extrakce bez chyb. Klient používá na extrakci `chat-big`.
- Orchestrátor nainstalován jako **systemd --user služba** `llama-swap.service` (enabled, běží),
  `-listen 0.0.0.0:8100 -watch-config`. **Firewall neotevřen, linger nezapnut** – čeká na Milana.
- `bench/smoke.sh`: 7/7 OK (vad, fingerprint, upscale, orchestrátor, whisper, embed, chat).
- Knihovna: `/media/disks/disk3/audio/spoken` (CIFS z NASu 192.168.1.11, autofs), struktura
  `Autor/Kniha (rok)/soubory`, u sérií `Autor/Série/Vol N - …/`. ~1023 autorů. Jen čtení.
- Test 30 s z 5 náhodných knih: 4/5 OK; Márquez = prvních 30 s hudba → „Titulky vytvořil JohnyX“.
  Slovenská kniha s vynucenou `cs` komolí, s `auto` správně `slovak`.
- Nový job `jobs/ends/transcribe_ends.py`: začátek a konec knihy (VAD najde řeč, 60 s, Whisper
  auto jazyk + nápověda „Autor, Název“), ID3 tagy, JSONL s navazováním. Test 5 knih: ~6 s/kniha,
  výsledek `data/ends-test5b.jsonl`. Opraveno spojování segmentů (mezery uprostřed slov).
  Detail: `jobs/ends/README.md`.
- Job `ends` pro celou knihovnu: bez argumentů = celá knihovna, cache seznamu `data/books.txt`
  (`--rescan`), navazování (knihy s chybou znovu), `--workers 2`, Ctrl+C dokončí rozpracované
  a vždy zapíše `data/ends.json` (atomicky). Otestováno: přerušení po 9 s → 2 knihy, znovu → zbylé 2.
  Celou knihovnu jsem **nepouštěl** – spouští Milan ručně (žádný systemd).
- Paralelizace: whisper ne (GPU vytížená; 2 instance −8 %), LLM ano: gemma4b 1→4 souběžné
  dotazy 46 → 92 tok/s. Chat servery přepnuty na `-np 4` (gemma/qwen4b c=32k, qwen9b c=16k).
- Pozn.: v zsh `for m in $var` nerozděluje slova → falešný dojem, že se modely nenačítají.
- Smazány testovací výstupy v `data/` (ends-test5*, test-resume.*). `data/` je prázdný, čeká na ostrý běh.
- Job přejmenován `jobs/ends/` → **`jobs/intro-outro/`**, skript `transcribe_intro_outro.py`, výstup `data/intro-outro.jsonl` / `.json` (starší záznamy výše používají původní název).
- Upscale: test 3 reálných malých obálek (~/tmp/obalky), pak srovnání 10 modelů přes upscayl-ncnn
  (Vulkan, 1–3.6 s/obálka). x4plus vymýšlí síťovinu v rytinách a kostrbaté drobné písmo;
  nejvěrnější **4x_NMKD-Siax_200k** (+ remacri-4x, 4xLSDIRplusC) → nový výchozí v upscale.sh.
  ~10px písmo neobnoví žádný model (GAN dokresluje „čte“ → „čto“).
- ffmpeg 8: `drawtext=fontfile=…` hlásí „Either text… must be provided“; bez fontfile (fontconfig) OK.
- **Git:** projekt je v repu `git@github.com:bardolf/audiobooksprocessing.git` (soukromé) ve složce
  `desktop/` (commit b6bf22c). Klon na desktopu: `~/projects/audiobooksprocessing`. Pracovní kopie
  zatím zůstává `~/projects/llm` (běží v ní přepis knihovny) → změny se kopírují rsyncem do klonu
  (bez engines/, models/, data/). Snapshot intro-outro od server session přesunut do
  `desktop/jobs/intro-outro/`, `desktop/sync.sh` stahuje už jen výsledky. README sloučeno.
  TODO po doběhnutí běhu: sjednotit (~/projects/llm → symlink na klon/desktop).
- intro-outro běh celé knihovny: 9 chyb. 7 opraveno ve skriptu (MP3 bez hlavičky délky → -sseof
  prázdný → záložní plné dekódování; .mp3 s RIFF uvnitř → vynucený formát). 2 jsou vady knihovny:
  Banková (šifrované/DRM soubory), Ivan Binar (8.3 mangled jméno přes CIFS). Detail jobs/intro-outro/README.md.
- Upscale velkými modely (HAT-L, DAT2, DRCT-L, ATD přes PyTorch ROCm) připraveno
  (`services/upscale/upscale_torch.py`, venv `engines/torch-sr`), **čeká na doběhnutí přepisu** (GPU).
- intro-outro dokončeno 21:47: 2254 knih, 12 chyb, 306 suspect. Z 12 chyb opravuje nová verze 9;
  3 jsou nečitelné (Banková – šifrované; Ivan Binar a Dvořáčková – Kyselé jablko – 8.3 mangled jména přes CIFS).
  Export JSON vynechával 2 knihy kvůli `splitlines()` a U+2028 v textu → opraveno, JSON má 2254.
- PyTorch 2.14.1+rocm7.2 na RX 6600 funguje (HSA_OVERRIDE_GFX_VERSION=10.3.0, /dev/kfd 0666).
  Nutné torchvision z rocm indexu (z PyPI → „torchvision::nms does not exist“).
  Velké SR modely: 8–19 s/obálka, VRAM ≤ 1.6 GB. DRCT-L jediný napsal drobné „čte“ správně.
- Oprava závěru (Milan si všiml): na „Hamerský“ je nejlepší **ATD**, DRCT-L tam dělá tmavé fleky.
  Celkově na drobné písmo doporučeno ATD (4xNomosWebPhoto_atd), ne DRCT-L.
- **Sjednocení:** pracovní kopie = git klon `~/projects/audiobooksprocessing`, `~/projects/llm` je
  symlink na `…/desktop`. `engines/`, `models/`, `data/` přesunuty do `desktop/` (mv, okamžité) a
  přidány do `.gitignore`. Orchestrátor restartován (unit je symlink přes ~/projects/llm), smoke 7/7 OK,
  torch-sr venv OK (má absolutní cesty přes ~/projects/llm → symlink nerušit). Konec rsync kopírování.
- **Příprava na zrušení symlinku ~/projects/llm:** llama.cpp a whisper.cpp přestavěny s
  `-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON` (RUNPATH `$ORIGIN`, dřív absolutní cesta přes symlink; ~40 s
  na engine díky ccache, `CCACHE_BASEDIR`). systemd unit, config.yaml, install.sh (`pwd -P`), sync.sh,
  README, IMPORT_POSTUP.md → cesta `~/projects/audiobooksprocessing/desktop`. Paměť Claude Code
  zkopírována do `~/.claude/projects/-home-milan-projects-audiobooksprocessing/memory/`.
  Ověřeno s odsunutým symlinkem: smoke 7/7, torch-sr (GPU), intro-outro export OK. Symlink zatím vrácen;
  smazat lze `rm ~/projects/llm` (venv torch-sr: volat `bin/python -m pip`, ne `bin/pip`).
- Symlink `~/projects/llm` smazán; projekt běží jen z `~/projects/audiobooksprocessing/desktop`.
- `desktop/data/intro-outro.jsonl` (2254 knih, 12 chyb – opakovaný běh zatím nespuštěn) přidán do gitu; `.gitignore`: `data/` → `**/data/*` + výjimka pro tento soubor.
- intro-outro opakovaný běh: 10/12 OK; server mezitím opravil knihovnu → nová volba `--prune` odebrala 4 zastaralé cesty, přepsány 2 přejmenované knihy. **2252 knih, 0 chyb.** Ranní běh byl pomalý (~40 s/kniha, asi uspané disky NASu); pak opět ~8 s. whisper po přestavbě: encode 474 ms (dřív 1989).
- **Firewall:** port 8100 otevřen pro NAS 192.168.1.11 (rich rule, permanentní). Ověřeno z NASu: /health 200, přepis klipu přes /v1/audio/transcriptions OK. README: sekce „Volání ze serveru“.
- **Upscale jako HTTP služba** přes orchestrátor (`/upstream/upscale/upscale`, model `upscale`, TTL 5 min): `services/upscale/server.py` (stdlib HTTP + PIL, ncnn i torch modely, hlavičky X-Upscale-*). Ověřeno lokálně i z NASu; klient `localai.upscale()`, `bin/ai upscale`, smoke 8/8.
- **Vision:** k Gemmě a Qwen 9B doplněn mmproj → modely `vision` (Qwen, přesné OCR, 20–40 s, běží sám) a `vision-fast` (Gemma, ~17 s). Kontrola obálek `bench/cover_check.py`: obě 4/4 včetně podvržené obálky, Qwen bez chyb v OCR. **Upscale `min_side`** (kratší strana, obálky 1000 px). IMPORT_POSTUP: min_side=1000, výjimka z max 1400 px, vision kontrola, vždy stahovat popis. Pozn.: během testů běžela serverová dávka upscale – moje `unload` jí přerušilo 1 požadavek (502); příště před unload zkontrolovat `/logs/stream/http`.
- **covers:** skript `jobs/covers/describe_covers.py` (idempotentní, klíč kniha+model+md5, raw odpověď modelu). Pilot 50 obálek: Gemma ~6 s/obálka efektivně (2 vlákna), Qwen 24 s; shoda 50/50, všech 14 podezřelých ručně potvrzeno jako špatné (fotky autorů, cizí obálky, obrázky ČRo 1040×584). Celá knihovna Gemmou ~4 h. `desktop/data/covers.jsonl` výjimka v .gitignore.
- **chat-long** (Gemma, 1 slot, 64k kontext; VRAM 4.9 GB celkem) a **`bin/ai talk`** (konverzace s historií, streaming, /reset /model /save /tokens). Ověřeno: 3 kola, model si pamatuje 1. dotaz. Web chat: `/upstream/<model>/`.
- covers běh celé knihovny (vision-fast): 2252 obálek za ~4 h (14:03–18:06), 653 podezřelých (205 fotka autora, 153 zástupný obrázek, 128 nesedí autor, 113 bez obálky, 26 nesedí název, 15 jiný obrázek, 13 chyb). `desktop/data/covers.jsonl` v gitu.
- **Překlad:** služba `translate` (`/upstream/translate/translate`, JSON, prompt skládá služba, odstavce paralelně) + modely `hunyuan-mt` (výchozí) a `translategemma` (`--no-jinja --chat-template gemma`). Srovnání: Hunyuan nejlepší (idiomy, literatura), TranslateGemma rychlejší, ale selhává na idiomech a přidává slova; obecná Gemma nevhodná. Ověřeno z NASu. Klient `translate()`, `bin/ai translate`, smoke.
- **Generování obrázků:** stable-diffusion.cpp (Vulkan) + Z-Image-Turbo Q4_K, model `image` v orchestrátoru (`/v1/images/generations`). 1024² ~65 s, VRAM špička 5.9 GB (offload). Text umí i s diakritikou, ale zopakoval slovo; „no text“ nerespektuje (rok z promptu vykreslil), „cover“ → mockup s rámečkem. Ověřeno z NASu. `bin/ai image`, `localai.image()`.
- **Úprava obrázků (image-edit):** FLUX.2-klein 4B přes sd-cli (fotka jako referenční obrázek), služba `edit_server.py`, `/upstream/image-edit/edit`. Fotka → komiks/akvarel výborně, osoba zachovaná; 768 px ~50 s, 512 ~25 s; ověřeno z NASu. ⚠ img2img se Z-Image shodil výpočetní kanál GPU (device lost, ring reset), SD pak ~6× pomalejší až do restartu PC. Z-Image vzorkuje ~55 s nezávisle na rozlišení (i bez offloadu).
- covers: 13 chyb = useknutý JSON (model se v text_na_obalce zacyklil, Bible apod., limit 900 tokenů). Oprava: maxLength ve schématu (gramatika), max_tokens 1600, repeat_penalty 1.1, surová odpověď do záznamu při chybě; export bere nejnovější záznam (kniha, model). Retry: 0 chyb, 644 podezřelých.
- covers krok 3 hotový (2026-10-02 23:42): Qwen 9B nad 644 podezřelými, 0 chyb, ~48 s/obálka (pomaleji než pilot – delší odpovědi). Potvrdil 616 podezřelých, 28 uznal za v pořádku. Qwen: 141 jiný obrázek, 133 fotka autora, 113 bez obálky, 100 nesedí autor (Gemma 129), 95 zástupný obrázek, 34 nesedí název.
- **langid:** služba rozpoznání jazyka audio stopy (filmy) – VAD + Whisper (language_probabilities, vážený průměr přes úseky) + cs/sk dorovnání podle písmen; ISO 639-1/2 (Matroska „cze“). Test: cs/sk/en/de správně (0.96–1.0), hudba → bez řeči, směs cs+en → nejisté. Ověřeno z NASu. Na audioknihách Whisper vs. písmena: 3 rozpory z 4 200 úseků.
