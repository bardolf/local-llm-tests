# vad – dělení dlouhých nahrávek na kapitoly podle ticha

- Silero VAD v6.2.0 (`models/vad/ggml-silero-v6.2.0.bin`, 0.9 MB) přes
  `whisper-vad-speech-segments` z whisper.cpp. Běží na CPU.
- `chapters.py` převede vstup (libovolný formát) na 16 kHz FLAC, najde řečové úseky a vrátí
  pauzy delší než `--min-gap` jako kandidáty na hranice kapitol. Řez je uprostřed pauzy.

```bash
./chapters.py "Čas opovržení 1.m4b"                 # JSON, pauzy ≥ 2 s
./chapters.py kniha.m4b --top 25                     # 25 nejdelších pauz (víš-li počet kapitol)
./chapters.py kniha.m4b --min-gap 3 --ffmetadata > ch.txt
ffmpeg -i kniha.m4b -i ch.txt -map 0 -map_metadata 1 -map_chapters 1 -c copy kniha_s_kapitolami.m4b
```

Test: syntetická nahrávka (řeč – 4 s ticho – řeč – 1 s ticho – řeč, 60 s) → přesně jedna
hranice v 0:00:20; běh 0.4 s.

## Kombinace s přepisem

Hranice podle ticha + krátký přepis prvních ~10 s po každé hranici přes whisper → pokud začíná
„Kapitola…“, je to jistá hranice a máme rovnou název. (TODO skript, až budou reálná data.)
