# translate – překlad (EN → CS a další jazyky)

Služba [`server.py`](server.py) (model `translate` v orchestrátoru, sama GPU nepoužívá) skládá prompt
podle doporučení autorů překladového modelu a volá ho přes orchestrátor. Dlouhý text překládá po odstavcích
(paralelně, 4 sloty), odstavce zachová.

```bash
curl -s http://192.168.1.10:8100/upstream/translate/translate -H 'Content-Type: application/json' \
     -d '{"text": "A gripping thriller.", "source": "en", "target": "cs"}'
# → {"translation": "…", "model": "hunyuan", "source": "en", "target": "cs", "ms": 845}
```

- `text` (str) nebo `texts` (list) – dávka; `source`/`target` – kódy jazyků (výchozí en → cs);
  `model`: **`hunyuan`** (výchozí) | `translategemma` | `gemma`.
- Lokálně: `bin/ai translate "text" [model]`, `echo text | bin/ai translate -`; Python `LocalAI(...).translate(...)`.

## Modely (srovnání 2026-10-02, `bench/results/translate-20261002.md`)

| model | rychlost | VRAM | kvalita |
|---|---|---|---|
| **Hunyuan-MT 7B** Q4_K_M (Tencent, WMT25) | 42 tok/s, anotace ~6 s | ~5.4 GB | nejlepší: idiomy („obrátila oči v sloup“), literatura („obdivuhodně vyváženou mysl“); drobné gramatické chyby v anotaci |
| TranslateGemma 4B Q6_K (Google) | 56 tok/s, anotace ~4.6 s | ~3.2 GB | dobré na běžný text, **selhává na idiomech** („You've got to be kidding me“ → „Musíte mě špatně pochopit“), občas si přidá slovo („Book two…“ → „Koupit druhou knihu…“) |
| Gemma 4 E4B (obecná) | 60 tok/s | – | nevhodná: zkomoleniny, azbuka v textu, obrácený smysl |

TranslateGemma má vestavěnou jinja šablonu se strukturovaným contentem → spouští se s `--no-jinja --chat-template gemma`
(`services/chat/run.sh`); instrukci skládá služba.

Výstup je vždy dobré u důležitých textů (anotace do ABS) zkontrolovat – oba modely dělají drobné chyby v pádech.
