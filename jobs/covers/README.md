# covers – popis a kontrola obálek vision modelem

Ke každé knize (seznam `data/books.txt`, stejný jako intro-outro) vezme `cover.jpg`, pošle ho vision modelu
přes orchestrátor spolu s očekávaným autorem a názvem (z cesty `Autor/[Série/][Vol N - ]Název (rok) {Vypravěč}`)
a uloží odpověď modelu beze změny. Z knihovny se jen čte, GPU běží na desktopu.

## Postup

```bash
cd ~/projects/audiobooksprocessing/desktop
jobs/covers/describe_covers.py                                  # krok 2: vision-fast (Gemma) přes všechny
jobs/covers/describe_covers.py --model vision --only-suspect    # krok 3: Qwen 9B jen nad podezřelými z kroku 2
jobs/covers/describe_covers.py --report                         # souhrn: kolik podezřelých a proč
```

- **Idempotentní:** klíč záznamu = kniha + model + md5 obálky. Hotové se přeskočí; když se obálka změní
  (výměna, upscale – jiná velikost souboru), zpracuje se znovu. Ctrl+C dokončí rozpracované, zapíše JSON;
  další spuštění pokračuje. 10 chyb za sebou → konec (orchestrátor/NAS).
- Kroky 2 a 3 se neperou: každý model má vlastní záznamy; `--only-suspect` čte výsledky `vision-fast`.
- Během běhu je GPU obsazená vision modelem (Gemma ~4 GB, Qwen ~6.5 GB – sám). Whisper a upscale se vejdou
  vedle Gemmy, `chat-big` ne.

## Výstup

`data/covers.jsonl` (v gitu) – 1 řádek = 1 kniha × model; `data/covers.json` (pole, generuje se na konci běhu).

```json
{"book": "Agatha Christie/Krysy (1996)", "model": "vision-fast",
 "cover": "cover.jpg", "md5": "…", "size": [500, 500], "bytes": 48213,
 "expected": {"autor": "Agatha Christie", "nazev": "Krysy", "serie": null},
 "vision": {"text_na_obalce": "AGATHA CHRISTIE\nKrysy", "autor_na_obalce": "AGATHA CHRISTIE", "nazev_na_obalce": "Krysy",
            "popis": "Obálka je minimalistická a tmavá…", "typ": "obalka_knihy",
            "sedi_autor": true, "sedi_nazev": true, "jistota": "vysoka", "duvod": "…"},
 "raw": "{… přesný text odpovědi modelu …}",
 "text_match": {"autor": 1.0, "nazev": 1.0},
 "suspect": false, "vision_s": 13.4, "gen_tokens": 210, "took_s": 13.5, "at": "2026-10-02T13:40:12"}
```

- `vision` = odpověď modelu (popis, přečtený text, verdikt) beze změny; `raw` = přesný text odpovědi.
- `text_match` = nezávislá kontrola: podíl slov autora/názvu nalezených v přečteném textu (0–1).
- `suspect` = nesedí autor nebo název, nízká jistota, typ není obálka knihy, chyba, nebo obálka chybí.
- Bez obálky: záznam s `"cover": null, "note": "bez obálky"`.

## Pilot (50 náhodných knih)

`jobs/covers/describe_covers.py --random 50 --out data/covers-pilot.jsonl` (+ totéž s `--model vision`), 2026-10-02.

| model | čas | podezřelých |
|---|---|---|
| vision-fast (Gemma), 2 vlákna | 12.9 s/obálka, **efektivně ~6 s** (50 za 5 min) | 17/50 |
| vision (Qwen 9B), 1 vlákno | 24.3 s/obálka | 17/50 – **stejné knihy** |

- **Shoda Gemma × Qwen 50/50** v tom, co je podezřelé (liší se jen typ: fotka_autora × zastupny_obrazek).
- Ruční kontrola kontaktního listu: všech 14 podezřelých s obálkou je opravdu špatně – fotka autora (Balabán,
  Grusková, Tokarczuková), obálka jiné knihy (Verne → „Mrazivé léto“, Bradbury → „Kaleidoskop“, Andorová → portrét
  E. A. Poea), ilustrační obrázky Českého rozhlasu 1040×584 (Joyce, Orwell, Szabłowski, Rais, Opolský), fotky
  z představení Spejbla a Hurvínka (3×); + 3 knihy bez obálky. 6 náhodných „v pořádku“ = opravdu správné obálky.
- Odhad celé knihovny (~2250): **Gemma ~4 h**; Qwen přes všechno ~15 h; Qwen jen nad podezřelými (~1/3) ~5 h.
- Doporučení: krok 2 (Gemma) přes noc stačí na verdikt; krok 3 (Qwen) volitelný – přesnější OCR/popis podezřelých.
