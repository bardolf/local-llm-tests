# Orchestrátor (llama-swap)

[llama-swap](https://github.com/mostlygeek/llama-swap) v261 – jedna Go binárka, OpenAI-kompatibilní
proxy na **portu 8100**. Podle pole `model` v requestu spustí příslušný backend
(`services/*/run.sh`), co se nevejde, vypne, a nečinné modely po TTL uvolní.

Scénář „pusť mi tenhle model, chvíli se budu ptát, pak jiný“ funguje sám od sebe:
první request na `chat` (gemma4b) ho nastartuje (pár sekund), další jdou hned, po 10 min klidu se uvolní.
Request na jiný model, který se do VRAM nevejde spolu s ním, ho vystřídá.

## Modely (ID pro pole `model`)

| ID | alias | co | TTL |
|---|---|---|---|
| `gemma4b` | `chat` | Gemma 4 E4B Q4_0 – výchozí, ~43 tok/s | 10 min |
| `qwen9b` | `chat-big` | Qwen3.5 9B Q4_K_M – přesnější extrakce, ~16 tok/s | 10 min |
| `gemma4b-long` | `chat-long` | Gemma 4 E4B, 1 slot, 64k kontext – dlouhé konverzace | 15 min |
| `qwen4b` | | Qwen3.5 4B Q4_K_M – jen pro srovnání | 10 min |
| `bge-m3` | `embed` | embeddingy 1024 dim | 15 min |
| `qwen3-emb` | | embeddingy 1024 dim (alternativa) | 15 min |
| `whisper` | `whisper-1` | přepis řeči | 15 min |
| `qwen9b-vision` | `vision` | Qwen3.5 9B + mmproj – popis/OCR obrázků, běží sám (~6.5 GB) | 5 min |
| `gemma4b-vision` | `vision-fast` | Gemma 4 E4B + mmproj – rychlejší, méně přesné OCR | 5 min |
| `translate` | | služba překladu (CPU) – volat `/upstream/translate/translate` | 15 min |
| `hunyuan-mt` | | Hunyuan-MT 7B – výchozí překladový model (~5.4 GB) | 10 min |
| `translategemma` | | TranslateGemma 4B – rychlejší/menší překlad | 10 min |
| `upscale` | | upscale obálek, HTTP služba `services/upscale/server.py` – volat `/upstream/upscale/upscale` | 5 min |

## Co může běžet současně (matrix router)

```
big_chat:   qwen9b & (bge-m3 | qwen3-emb)
small_chat: (qwen4b | gemma4b) & (bge-m3 | qwen3-emb) & whisper & upscale
audio:      whisper & (bge-m3 | qwen3-emb) & upscale
vision:     qwen9b-vision                      (sám)
vision_fast: gemma4b-vision & (bge-m3 | qwen3-emb) & upscale
```

Tj. velký chat vyhodí whisper; malý chat, embed a whisper koexistují. Čísla VRAM:
[docs/BENCHMARKS.md](../docs/BENCHMARKS.md).

## Ovládání

```bash
bin/ai status              # co běží + VRAM
bin/ai load qwen9b         # předehřát
bin/ai unload              # uvolnit vše (např. před upscalem nebo když NAS chce lc0)
bin/ai chat "dotaz"
bin/ai stt kniha.mp3 srt
bin/ai logs qwen9b
```

Web UI: http://127.0.0.1:8100/ui (playground, logy, ruční load/unload).

HTTP API (pro skripty na serveru):

```
POST /v1/chat/completions        {"model":"chat", "messages":[…]}
POST /v1/embeddings              {"model":"embed", "input":["…"]}
POST /v1/audio/transcriptions    multipart: model=whisper, file=@…, response_format=…
GET  /running                    co běží
POST /api/models/unload[/<id>]   uvolnit
GET  /upstream/<id>/health       načíst model (blokuje do připravenosti)
```

## Instalace jako služba

**Stav: nainstalováno a běží** (`systemctl --user status llama-swap`), linger zatím vypnutý.

```bash
orchestrator/install.sh            # ~/.config/systemd/user/llama-swap.service → symlink
journalctl --user -u llama-swap -f
sudo loginctl enable-linger milan  # aby běžel po bootu i bez přihlášení
```

`-watch-config`: změna `config.yaml` se načte sama bez restartu.

## Přístup ze sítě

Služba poslouchá na `0.0.0.0:8100`; firewalld (zóna public) pouští port **jen z NASu 192.168.1.11**
(od 2026-10-02, stejně jako lc0/stockfish), odjinud zavřeno. API klíč není.

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.11" port port="8100" protocol="tcp" accept'
sudo firewall-cmd --reload
sudo firewall-cmd --list-rich-rules           # kontrola
```

Ověřeno z NASu: `/health` 200, přepis klipu přes `/v1/audio/transcriptions` OK.

## Sdílení GPU s lc0

Na stroji běží `lc0.socket` (šachy z NASu) – každá aktivní partie si nahraje síť do VRAM.
Když je načtený `qwen9b` (~6+ GB), lc0 se nemusí vejít. Zatím ručně `bin/ai unload`;
možné řešení do budoucna: `ExecStartPre=` v lc0 service, který zavolá unload.
