# Měření (RX 6600 XT 8 GB, Vulkan/RADV, Mesa 26.2.3)

Baseline: bez našich modelů je obsazeno **~1.2–1.3 GB VRAM** (desktop). Měřeno z
`/sys/class/drm/card1/device/mem_info_vram_used` (`bin/ai status`).

## VRAM podle služby (přírůstek nad baseline)

| služba | VRAM | poznámka |
|---|---|---|
| whisper turbo-q8 | ~0.8 GB | váhy 874 MB + compute ~155 MB |
| bge-m3 Q8_0 | ~0.6 GB | -c 8192 -ub 8192 |
| gemma4b (E4B Q4_0) | ~2.8 GB | c=16384, KV q8_0; per-layer embeddingy zůstávají v RAM |
| qwen4b (Q4_K_M) | ~2.8 GB | c=16384, KV q8_0 |
| qwen9b (Q4_K_M) | ~5.0 GB | c=16384, KV q8_0 |

Kombinace (celkem včetně baseline): gemma4b + bge-m3 + whisper = **5.44 GB**,
qwen9b + bge-m3 = **6.85 GB**. qwen9b + whisper + embed by bylo ~7.7 GB → v matici zakázáno.

## Whisper large-v3-turbo q8_0

| vstup | konfigurace | čas | × realtime |
|---|---|---|---|
| jfk.wav 11 s | cli, cold | 2.9 s | – |
| espeak CZ 12.9 min | server, VAD | 109 s | **7.1×** |
| espeak CZ 3 min | cli, bez VAD, t4/t8 | 18.0 s | 10× |
| espeak CZ 3 min | cli, VAD | 23.8–31.5 s | 6–7.5× |
| espeak CZ 3 min | server, VAD | 24.4 s | 7.4× |

`whisper-bench`: encode 1989 ms / okno 30 s, decode 7.4 ms/token, load 0.5 s.

Odhad: 6h audiokniha ≈ 50 min (s VAD) / ≈ 36 min (bez VAD).

⚠ **whisper-cli s `--vad` a `-nt` (bez časových značek) halucinuje** – celý výstup
„Titulky vytvořil JohnyX.“ dokola. S časovými značkami (a přes server) OK.

## Real-ESRGAN x4plus

200×200 → 800×800: 1.5 s (vč. načtení). S `OMP_WAIT_POLICY=passive` (jinak 20 s CPU zbytečně).

Modely (ncnn/Vulkan, 1–4 s/obálka): nový výchozí 4x_NMKD-Siax_200k. Velké transformery přes PyTorch ROCm
(DRCT-L/HAT-L/DAT2/ATD): 8–19 s/obálka, VRAM ≤ 1.6 GB, DRCT-L nejlepší na drobné písmo.
Detail: services/upscale/README.md.

## VAD (Silero, CPU)

60s nahrávka: 0.4 s.

## Chat LLM

### Rychlost (llama-bench, Vulkan, fa=1)

| model | pp512 tok/s | tg128 tok/s | načtení |
|---|---|---|---|
| **Gemma-4-E4B Q4_0** | 856 | **49.5** | <1 s (cache) |
| Qwen3.5-4B Q4_K_M | 783 | 18.8 | 2.4 s |
| Qwen3.5-9B Q4_K_M | 371 | 15.9 | 3.4 s |

Qwen3.5 (hybrid Gated DeltaNet) je na Vulkanu/RDNA2 brzděný kopírováním rekurentního stavu:
`GGML_VK_PERF_LOGGER=1` → z 28.9 ms/token je 7.9 ms `CPY` a 7.7 ms `GET_ROWS` (~13 GB/s).
4B a 9B mají proto skoro stejnou rychlost. Vynucení vysokých taktů GPU nepomáhá.

### Kvalita (`bench/chat_eval.py`, výsledky `bench/results/chat-20261001-1655.md`)

Reasoning vypnutý, JSON schema, temperature 0.2. Hodnoceno ručně:

| úloha | gemma4b | qwen4b | qwen9b |
|---|---|---|---|
| credits ze zkomoleného přepisu | vydavatel ✓, jména nechal zkomolená | vymyslel „Michal“ | vymyslel název ✗ |
| normalizace autorů | 8/9 („Bozena“) | 9/9 | 9/9 |
| kódy souborů → kapitoly | ✓ | ✓ | ✗ přečísloval |
| série a díl (znalost) | většinou null | halucinace | halucinace |
| volná čeština (anotace) | ✓ | ✗ vymyšlený děj | ✓ |
| čas úlohy | 2.4–8 s | 4.4–18 s | 5.4–22 s |

**Se zpřesněnými prompty (clients/localai.py) a přepisem s nápovědou jmen:**
- qwen9b: credits **úplně správně** (Andrzej Sapkowski / Krev elfů / Jan Hyhlík / Tympanum / 2020),
  normalizace **6/6** včetně „Hrabal B.“ → „Bohumil Hrabal“.
- gemma4b: „Čtejan Hyhlík“ (neodlepí sloveso), „Bozena Němcová“, „B. Hrabal“.

Závěr: `chat` = gemma4b (rychlý, nejméně halucinuje ve volném textu), na přesnou extrakci
a normalizaci `chat-big` = qwen9b. Znalost sérií/dílů malé modely **nemají** – brát z externí
databáze (např. databazeknih), LLM jen na párování.

### Paralelní dotazy (gemma4b, -np 8, 200 tok odpovědi)

| souběžně | celkem tok/s | dotazů/min |
|---|---|---|
| 1 | 46 | 18 |
| 2 | 68 | 22 |
| 4 | **92** | **40** |
| 8 | 95 | 38 |

→ chat servery mají `-np 4` (gemma4b/qwen4b c=32768 → 8k na slot, qwen9b c=16384 → 4k na slot).
VRAM s -np 4: qwen9b + bge-m3 = 6.95 GB, gemma4b + bge-m3 + whisper = 5.83 GB (baseline 1.22).
Whisper paralelně nepomáhá (viz jobs/intro-outro/README.md).

### Pozor na reasoning

Qwen3.5 bez `--reasoning off` na jednoduchou otázku vygeneroval 5169 tokenů „přemýšlení“
(4 min 37 s). Výchozí v `services/chat/run.sh` je proto off.
