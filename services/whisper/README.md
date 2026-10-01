# whisper – přepis řeči

- Engine: `whisper.cpp` → `whisper-server`, build s `-DGGML_VULKAN=ON`
- Model: `ggml-large-v3-turbo-q8_0.bin` (874 MB VRAM pro váhy). Plná f16 verze `turbo` jako alternativa.
- VAD: Silero v6.2.0 zapnutý (`--vad`) – přeskočí ticho, méně halucinací („Titulky vytvořil…“).
- `--convert`: server sám převádí mp3/m4b/opus/... přes ffmpeg na 16 kHz WAV.
- Výchozí jazyk `cs`; dá se přepsat v requestu (`-F language=auto`).

## API

```bash
curl -s localhost:8103/v1/audio/transcriptions \
  -F file=@kapitola01.mp3 -F response_format=verbose_json      # s časy segmentů
```

Přes orchestrátor stejně, jen port orchestrátoru a navíc `-F model=whisper`.

Další parametry formuláře (whisper-server): `temperature`, `prompt` (počáteční kontext –
hodí se dát jména postav, např. `-F prompt="Geralt, Ciri, Yennefer, Marigold"`), `translate`,
`no_timestamps`, `offset_t`, `duration`.

## Naměřeno

- jfk.wav (11 s, EN): 2.9 s celkem včetně načtení modelu, encode 1.9 s (cold).
- český vzorek z espeak-ng (18 s) přes HTTP: 2.2 s. Čeština OK; chyby jen tam, kde espeak
  špatně vyslovuje (syntetický robotický hlas). Reálné audioknihy otestovat.
- **`prompt` nápověda výrazně pomáhá se jmény**: bez ní „naklínač… Čtejan Chichlík… Timpanum“,
  s `prompt="Sapkowski, Zaklínač, Hyhlík, Tympanum"` → „Zaklínač… Hyhlík… Tympanum“ správně.
  → při přepisu znát autora/sérii (z metadat) a poslat je jako prompt.
- Benchmark rychlosti na dlouhé nahrávce: TODO (chybí reálné audio na tomto stroji).

## Nápady na použití

- Zjištění vypravěče/vydavatele: přepsat jen prvních ~60 s (`-F duration=60000`) a výstup
  poslat do chat modelu s promptem na extrakci.
- Titulky / plný přepis knihy: `response_format=srt`, dávkově po kapitolách.
