# intro-outro – přepis začátků a konců audioknih

Cíl: ke každé knize uložit přepis ~60 s **začátku** (ohlášení: vydavatel, autor, název, „čte…“)
a ~60 s **konce** (často „Zde končí…“, „Účinkovali…“, „Vydalo…“) + ID3 tagy. AI z toho později
vytáhne a opraví metadata (např. přepis „Timpanum“ → Tympanum, „Chichlík“ → Hyhlík).

Z knihovny (`/media/disks/disk3/audio/spoken`, CIFS z NASu) se **jen čte**.
Přepis běží na **Radeonu** (whisper-server přes Vulkan, orchestrátor ho spustí sám), VAD na CPU.

## Jak to funguje

1. Kniha = adresář, který přímo obsahuje audio (podadresáře `CD1`, `CD2` se slučují).
2. Začátek: první soubor → prvních 180 s → Silero VAD najde první řeč (≥ 1 s, tím se přeskočí
   úvodní hudba) → 60 s od ní → Whisper (`language=auto`, nápověda „Autor, Název“).
3. Konec: poslední soubor → posledních 180 s → konec poslední řeči → 60 s před ním → Whisper.
4. Odfiltrují se známé halucinace („Titulky vytvořil JohnyX“…).
5. `suspect: true`, když se něco zahodilo, text je krátký, nebo < 3 znaky/s.

## Použití (celá knihovna)

```bash
cd ~/projects/llm
jobs/intro-outro/transcribe_intro_outro.py              # spustit / navázat
#   Ctrl+C → dokončí rozpracované knihy, zapíše data/intro-outro.json a skončí
jobs/intro-outro/transcribe_intro_outro.py              # znovu = pokračuje, kde skončil
scp data/intro-outro.json nas:…                  # výsledek na server
```

- **První spuštění** projde NAS a uloží seznam knih do `data/books.txt` (pár minut). Další běhy
  ho jen načtou. Přibyly knihy → `--rescan`.
- `data/intro-outro.jsonl` se zapisuje průběžně (1 kniha = 1 řádek, přežije pád i výpadek proudu).
- `data/intro-outro.json` (pole záznamů, seřazené podle cesty) se vygeneruje na konci každého běhu
  i po Ctrl+C; zapisuje se atomicky. Ručně: `--export-only`.
- Hotové knihy se přeskočí, knihy **s chybou se zkusí znovu**. 10 chyb za sebou → konec
  (spadlý NAS / orchestrátor).
- Orchestrátor musí běžet (`bin/ai status`); whisper si nastartuje sám.

Další volby:

```bash
jobs/intro-outro/transcribe_intro_outro.py --limit 200                 # jen dalších 200 knih
jobs/intro-outro/transcribe_intro_outro.py "Agatha Christie/Krysy (1996)"   # konkrétní knihy
jobs/intro-outro/transcribe_intro_outro.py --books-file seznam.txt --out data/x.jsonl
jobs/intro-outro/transcribe_intro_outro.py --random 5 --out data/test.jsonl
jobs/intro-outro/transcribe_intro_outro.py --workers 1                  # sériově
```

## Paralelizace

GPU je jedna a whisper-server zpracovává požadavky po jednom. Měřeno (4 × 60 s řeči):
1 instance sériově 35.4 s, 4 paralelní dotazy na 1 instanci 35.3 s, 2 instance 32.6 s (−8 %
za 2× VRAM – nevyplatí se). Vyplatí se jen překrýt čtení z NASu + ffmpeg + VAD (~1 s/kniha)
s prací GPU → `--workers 2` (výchozí).

## Formát výstupu (JSONL, 1 kniha = 1 řádek)

```json
{"book": "J. R. R. Tolkien/Pán prstenů/Vol 1 - …", "author": "J. R. R. Tolkien", "title": "Vol 1 - …",
 "n_files": 1, "first_file": "…m4b", "last_file": "…m4b",
 "probe_first": {"duration": 61234.5, "tags": {"composer": "Aleš Procházka", "album": "…", …}},
 "start": {"file": "…", "offset": 10.2, "length": 60.0, "language": "czech",
           "text": "Vydavatelství Timpanum uvádí audioknihu Společenstvo Prstenu. …",
           "segments": [{"start": 0.0, "end": 4.1, "text": " …"}], "dropped": [],
           "chars_per_s": 3.9, "suspect": false},
 "end":   {"file": "…", "offset_from_end": 60.8, …},
 "took_s": 6.0, "at": "2026-10-01T17:40:12"}
```

`segments[].start/end` jsou relativní k vystřiženému úseku (absolutně: + `offset`).

## Test na 5 náhodných knihách (2026-10-01)

Seznam testovacích knih: `jobs/intro-outro/test5.txt` (výstupy testů smazány 2026-10-01).

| kniha | začátek | konec |
|---|---|---|
| García Márquez – Na paměť mým smutným courám | řeč od 30 s (před tím hudba – dřív halucinace) ✓ | ✓ |
| Balzac – Rozmarné poviedky | `slovak` ✓ | ✓ |
| Pacovská – Sedmý smysl 10 | „Desátá kniha v sérii Sedmý smysl…“ ✓ | ✓ |
| Tolkien – Společenstvo Prstenu | „Vydavatelství Timpanum… Čte Aleš Procházka“ ✓ | „Zde končí první část…“ ✓ |
| Valenta – Na dně bazénu… | ✗ útržky (řeč přes hudbu ČRo), 1.5 zn/s → suspect | upoutávka ČRo |

Rychlost: **~6 s na knihu** (2 × 60 s přepisu + čtení ze sítě). Celá knihovna (~1000 autorů,
odhadem 3–4 tisíce knih) ≈ 5–7 hodin.

## Postřehy

- ID3 tagy jsou cenný zdroj: v `composer` bývá vypravěč (Kudla, Mistrík, Procházka), v `comment`
  „Ète: Margit Vinklárková“ = rozbité kódování „Čte:“ (cp1250 čtené jako latin1). Názvy souborů
  mají místy taky rozbité kódování („TerezЯin talent pro dobrВ konc“).
- Nápověda pro Whisper („Autor, Název“) pomáhá s názvem, vydavatele ale nezná → „Timpanum“.
  Opravu nechat na AI kroku (může mít seznam známých vydavatelů a vypravěčů).
- ffmpeg u MP3 při skoku na konec vypíše „Header missing“ – neškodné.
- Suspect knihy půjde později přepsat s delším oknem (`--seconds 120`) do zvláštního souboru.
