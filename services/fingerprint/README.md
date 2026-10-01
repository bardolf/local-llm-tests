# fingerprint – poznání stejné nahrávky v různých verzích

- Chromaprint `fpcalc` (balík `chromaprint-tools`), CPU.
- `compare.py` vystřihne úsek (výchozí od 60 s, délka 120 s), spočítá surový otisk a porovná
  dvojice souborů s hledáním nejlepšího časového posunu (±10 s).

```bash
./compare.py "Žízeň.mp3" "Žízeň.m4b"
./compare.py john_96k/*.mp3 john_128k/*.mp3     # všechny dvojice
./compare.py --json kniha.m4b > otisk.json      # uložit otisk pro pozdější porovnání
```

Prahy: **≥ 0.85 stejná**, 0.72–0.85 asi stejná (jiný mastering/střih), < 0.72 jiná.

Test (syntetické audio z espeak-ng):
- stejná nahrávka 192k MP3 vs. 48k AAC posunutá o 1.5 s → **0.969**, posun nalezen +1.5 s
- stejný hlas, jiný text → 0.60 (to je „šum“ díky hledání posunu)

Pro velkou knihovnu: uložit otisky (`--json`) do DB a porovnávat jen kandidáty se
stejnou/podobnou délkou – porovnání všech se všemi je O(n²).
