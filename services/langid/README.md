# langid – rozpoznání jazyka audio stopy (filmy)

Služba [`server.py`](server.py) (model `langid` v orchestrátoru, sama GPU nedrží): v každém klipu najde řeč (Silero VAD),
na úsecích ~30 s s nejvíc řečí nechá Whisper určit jazyk (rozdělení pravděpodobností přes 99 jazyků), výsledky
zprůměruje (váženě množstvím řeči) a rozhodne. Čeština × slovenština se při rozdílu < 0.3 dorovná podle písmen
v přepisu (ě ř ů × ä ľ ĺ ŕ ô).

Proč Whisper a ne specializovaný model (VoxLingua107, MMS-LID): na běžné filmové jazyky je stejně dobrý, už běží,
a na audioknihách (4 200 úseků) se s kontrolou podle písmen rozešel jen 3× (sporné případy – nářečí).

## Volání (server, jen u stop, kde si není jistý)

Server vystřihne z dané audio stopy 3–5 klipů po 30 s z různých míst (začátek bývá hudba/titulky):

```bash
N=1   # index audio stopy (0:a:N = N-tá audio stopa)
for t in 600 1800 3000; do
  ffmpeg -loglevel error -ss $t -t 30 -i film.mkv -map 0:a:$N -vn -ac 1 -ar 16000 klip_$t.wav
done
curl -s http://192.168.1.10:8100/upstream/langid/detect -F file=@klip_600.wav -F file=@klip_1800.wav -F file=@klip_3000.wav
```

Odpověď:

```json
{"language": "cs", "iso639_1": "cs", "iso639_2": "cze", "iso639_2t": "ces", "confidence": 0.997,
 "uncertain": false, "reason": null, "note": null, "probabilities": {"cs": 0.997},
 "votes": {"cs": 3}, "samples": [{"file": "klip_600.wav", "start": 0.0, "speech_s": 25.8, "lang": "cs", "prob": 0.998,
 "text": "…"}], "speech_s": 76.2, "ms": 6700}
```

- `iso639_2` = kód pro Matrosku (`mkvpropedit film.mkv --edit track:a2 --set language=cze`), `iso639_2t` = terminologický.
- `uncertain: true` + `reason`: jistota < 0.6, úseky se neshodují (např. cizojazyčná scéna), nebo < 8 s řeči.
- Bez řeči (jen hudba): `language: null`, `reason: "v klipech není řeč"`.
- Python: `LocalAI(url).detect_language(["k1.wav", "k2.wav"])`.

## Test (2026-10-03, 3 klipy × 30 s)

| stopa | výsledek | jistota | čas |
|---|---|---|---|
| čeština – audiokniha (Saturnin) | cs / cze | 0.997 | 6.7 s |
| čeština – rozhlasová hra s hudbou (Spejbl) | cs / cze | 0.964 | 4.8 s |
| slovenština (Balzac) | sk / slo | 0.993 | 5.9 s |
| angličtina (Atwood) | en / eng | 1.0 | 4.8 s |
| němčina (syntetický hlas) | de / ger | 1.0 | 1.5 s |
| jen hudba / tón | null, nejisté „v klipech není řeč“ | – | – |
| 2× čeština + 1× angličtina | cs, **nejisté** „úseky se neshodují {cs: 2, en: 1}“ | 0.649 | – |

Z NASu: 1 klip slovenštiny → sk 0.995 za 1.8 s.
