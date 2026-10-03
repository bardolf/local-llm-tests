# Plán a architektura

## Cíl

Několik malých modelů dostupných přes HTTP v LAN pro skripty (hlavně audioknihovna).
Nemusí běžet všechny naráz – 8 GB VRAM na to nestačí. Orchestrátor spustí, co je
potřeba, a po chvíli nečinnosti to zase uvolní.

## Stav (2026-10-01)

| Služba | Stav | Engine | Model |
|---|---|---|---|
| `chat` | ✅ běží přes Vulkan | llama-server | `chat`=Gemma-4-E4B, `chat-big`=Qwen3.5-9B (viz BENCHMARKS) |
| `embed` | ✅ | llama-server --embedding | bge-m3 Q8_0 (+ Qwen3-Embedding-0.6B) |
| `whisper` | ✅ | whisper-server | large-v3-turbo q8_0 + Silero VAD |
| `upscale` | ✅ | realesrgan-ncnn-vulkan | realesrgan-x4plus |
| `vad` | ✅ CLI | whisper-vad-speech-segments | Silero v6.2.0 |
| `fingerprint` | ✅ CLI | fpcalc | – |
| orchestrátor | ✅ systemd --user služba (běží, enabled; linger ne) | llama-swap v261 | port 8100 |

Vše otestováno jen na **syntetických datech** (espeak-ng, ukázkový obrázek) – na stroji nejsou
audioknihy. Další krok: reálná data z NASu.

## Architektura

```
 NAS / server (192.168.1.11?)                       tento stroj (192.168.1.10, RX 6600 XT)
 ───────────────────────────                        ─────────────────────────────────────────
 skripty audioknihovny ── HTTP :8100 ──► llama-swap ─┬─► chat/run.sh    (llama-server)  :8201+
   clients/localai.py                     (matrix   ├─► embed/run.sh   (llama-server)
                                           router,  └─► whisper/run.sh (whisper-server)
                                           TTL)
                                                     CLI (spouští se přímo / přes ssh):
                                                       upscale.sh, chapters.py, compare.py
```

- Serverové služby: llama-swap podle pole `model` spustí backend, matice říká, co se vejde
  současně, TTL uvolní nečinné. Backendy poslouchají jen na 127.0.0.1.
- CLI nástroje nejsou servery – volají se přímo (přes ssh, nebo běží na NASu: VAD a fpcalc
  GPU nepotřebují, klidně můžou běžet na NASu samotném).

## Rozhodnutí

- **Nativní binárky + systemd --user**, ne kontejnery: jednodušší přístup k GPU, buildy z gitu
  s ccache se aktualizují za pár minut.
- **llama-swap** místo vlastního orchestrátoru: hotové, umí přesně „půjč si GPU na chvíli“,
  matrix router, TTL, web UI, OpenAI API včetně audio/embeddings.
- **Reasoning vypnutý** u chat modelů (úklidové úlohy nepotřebují úvahy, Qwen3.5 jinak
  generuje tisíce tokenů).
- **JSON schema** v requestech (gramatika v llama-serveru) → výstup vždy parsovatelný.
- Whisper **q8_0** (ne f16): menší a na Vulkanu/RDNA2 i rychlejší.

## Otevřené otázky (pro Milana)

1. ✅ Volá se z NASu 192.168.1.11 – port 8100 otevřen jen pro něj (2026-10-02).
2. **Běh po bootu bez přihlášení?** Služba je nainstalovaná a enabled; pro start bez
   přihlášení chybí `sudo loginctl enable-linger milan`.
3. **lc0 sdílí GPU** – má mít přednost? Pak před partií uvolnit modely (`bin/ai unload`),
   případně hook v lc0 service.
4. Výchozí `chat` = gemma4b, přesná extrakce `chat-big` = qwen9b – sedí to? (BENCHMARKS)
   Na Qwen3.5 brzdí Vulkan kernel; větší Gemma 4 12B (6.7 GB) se do 8 GB s desktopem nevejde.
5. ✅ Knihovna zpřístupněna (/media/disks/disk3/audio/spoken), job `jobs/intro-outro` otestován na 5 knihách.

## Rozpracované úkoly (TODO)

- [ ] **covers – dokončit kontrolu obálek** (domluveno 2026-10-02):
  1. ✅ chyby opraveny (2026-10-02, 0 chyb, 644 podezřelých),
  2. ✅ Qwen 9B nad 644 podezřelými hotovo (2026-10-02): 616 potvrzeno, 28 v pořádku, 0 chyb,
     hlavně ověřit kategorii „nesedí autor“ (128 – podezření na plané poplachy),
  3. ✅ commit `desktop/data/covers.jsonl` → **na řadě server**: kontaktní list podezřelých, oprava obálek.
- [x] překlad EN → CS: služba `translate` (Hunyuan-MT výchozí), 2026-10-02.
- [x] generování obrázků: Z-Image-Turbo přes stable-diffusion.cpp, model `image` (2026-10-02).
  Další krok (nápad): náhradní ilustrace pro knihy bez obálky / s fotkou autora (covers.jsonl), nápis vsadit dodatečně.

## Nápady dál

- Pipeline „nová kniha“: fpcalc (duplicita?) → whisper prvních 60 s → chat extrakce
  autor/vypravěč/vydavatel → embed anotace → upscale obálky když < 500 px.
- Reranker (bge-reranker-v2-m3) pro lepší vyhledávání – llama-swap umí `/v1/rerank`.
- Sledovat llama.cpp kvůli pomalému Qwen3.5 na Vulkanu (CPY/GET_ROWS rekurentního stavu).
