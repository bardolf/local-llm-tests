#!/usr/bin/env python3
"""Popis a kontrola obálek všech knih vision modelem → JSONL (pro pozdější úklid obálek na serveru).

Pro každou knihu (seznam z data/books.txt – stejný jako intro-outro) vezme `cover.jpg`, pošle ho
vision modelu (přes orchestrátor) spolu s očekávaným autorem a názvem (z cesty ke složce) a uloží:
přečtený text, autora/název z obálky, popis, typ obrázku, verdikt shody, jistotu a důvod.
Navíc vlastní kontrola nezávislá na modelu: textová shoda přečteného textu s autorem/názvem.

Idempotentní: klíč záznamu = (kniha, model, md5 obálky). Hotové se přeskočí; vyměněná/upscalovaná
obálka (jiné md5) se zpracuje znovu. Ctrl+C dokončí rozpracované a zapíše JSON. Z knihovny jen čte.

  describe_covers.py                                  # krok 2: vision-fast (Gemma) přes všechny
  describe_covers.py --model vision --only-suspect    # krok 3: Qwen jen nad podezřelými z kroku 2
  describe_covers.py --random 50 --out data/covers-pilot.jsonl     # pilot
  describe_covers.py "Agatha Christie/Krysy (1996)"   # konkrétní knihy
  describe_covers.py --export-only                    # jen přegenerovat data/covers.json
  describe_covers.py --report                         # souhrn: kolik podezřelých a proč

Výstup: data/covers.jsonl (průběžně) + data/covers.json (pole, na konci běhu). Záznam obsahuje odpověď modelu
beze změny: `vision` (popis, přečtený text, verdikt…) a `raw` (přesný text odpovědi).
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import io
import json
import random
import re
import sys
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path("/media/disks/disk3/audio/spoken")
COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg")
SEND_MAX_SIDE = 1024          # vision enkodér obrázek stejně zmenší; menší upload a méně tokenů

SCHEMA = {"type": "object", "properties": {
    "text_na_obalce": {"type": "string"},
    "autor_na_obalce": {"type": ["string", "null"]},
    "nazev_na_obalce": {"type": ["string", "null"]},
    "popis": {"type": "string"},
    "typ": {"type": "string", "enum": ["obalka_audioknihy", "obalka_knihy", "fotka_autora", "zastupny_obrazek",
                                        "jiny_obrazek"]},
    "sedi_autor": {"type": "boolean"},
    "sedi_nazev": {"type": "boolean"},
    "jistota": {"type": "string", "enum": ["vysoka", "stredni", "nizka"]},
    "duvod": {"type": "string"}},
    "required": ["text_na_obalce", "autor_na_obalce", "nazev_na_obalce", "popis", "typ", "sedi_autor",
                 "sedi_nazev", "jistota", "duvod"]}

PROMPT = """Kontroluješ obálku audioknihy v domácí knihovně.
Očekávaná kniha: autor „{autor}“, název „{nazev}“{serie}.

1. text_na_obalce: přepiš přesně všechen čitelný text na obrázku (včetně vydavatele, „čte …“, série).
2. autor_na_obalce, nazev_na_obalce: jak jsou na obálce (null, když tam nejsou).
3. popis: 2–4 věty česky – co obrázek zobrazuje (motiv, styl, barvy, kompozice).
4. typ: obalka_audioknihy | obalka_knihy | fotka_autora | zastupny_obrazek („image not available“, logo, prázdné) | jiny_obrazek.
5. sedi_autor, sedi_nazev: odpovídá obálka očekávanému autorovi / názvu? (Jiné pořadí jména, diakritika, velká písmena
   nebo podtitul nevadí. Když text na obálce chybí, posuď podle motivu a dej nízkou jistotu.)
6. jistota: vysoka | stredni | nizka.
7. duvod: jedna věta proč.
Vrať JSON."""


# ---------- pomocné ----------
def natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def expected(book: str) -> dict:
    """Autor a název z cesty: Autor/[Série/]Vol N - Název (rok) {Vypravěč}."""
    parts = book.split("/")
    title = parts[-1]
    title = re.sub(r"\s*\{.*?\}", "", title)
    title = re.sub(r"\s*\((?:\d{4}|v\d+)\)", "", title)
    title = re.sub(r"^Vol\.?\s*\d+\s*-\s*", "", title, flags=re.I).strip()
    serie = parts[1] if len(parts) >= 3 else None
    return {"autor": parts[0], "nazev": title, "serie": serie}


def text_match(exp: dict, ocr: str) -> dict:
    """Nezávislá kontrola: kolik slov autora / názvu je v přečteném textu (0–1)."""
    o = norm(ocr)
    owords = set(o.split())

    def score(s: str | None) -> float:
        words = [w for w in norm(s or "").split() if len(w) > 2]
        if not words:
            return 1.0
        hits = sum(1 for w in words if w in owords or any(SequenceMatcher(None, w, x).ratio() > 0.8 for x in owords))
        return round(hits / len(words), 2)
    return {"autor": score(exp["autor"]), "nazev": score(exp["nazev"])}


def find_cover(d: Path) -> Path | None:
    for n in COVER_NAMES:
        if (d / n).is_file():
            return d / n
    return None


def is_suspect(r: dict) -> bool:
    v = r.get("vision") or {}
    if r.get("error") or not v:
        return True
    return (not v.get("sedi_autor") or not v.get("sedi_nazev") or v.get("jistota") == "nizka"
            or v.get("typ") not in ("obalka_audioknihy", "obalka_knihy"))


def load_records(path: Path) -> dict[tuple, dict]:
    recs: dict[tuple, dict] = {}
    if path.exists():
        for line in path.read_text().split("\n"):   # ne splitlines() – U+2028 v textech
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            recs[(r["book"], r["model"], r.get("md5"))] = r
    return recs


def latest_per_book(recs: dict[tuple, dict], model: str | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for (book, m, _), r in recs.items():
        if model and m != model:
            continue
        if book not in out or r.get("at", "") > out[book].get("at", ""):
            out[book] = r
    return out


def export_json(jsonl: Path, out: Path) -> None:
    recs = sorted(load_records(jsonl).values(), key=lambda r: (natural_key(r["book"]), r["model"]))
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(recs, ensure_ascii=False))
    tmp.replace(out)
    print(f"export: {len(recs)} záznamů → {out}", file=sys.stderr)


# ---------- jádro ----------
def describe(url: str, model: str, book: str, cover: Path) -> dict:
    raw = cover.read_bytes()
    md5 = hashlib.md5(raw).hexdigest()
    img = Image.open(io.BytesIO(raw))
    w, h = img.size
    img = img.convert("RGB")
    if max(w, h) > SEND_MAX_SIDE:
        k = SEND_MAX_SIDE / max(w, h)
        img = img.resize((round(w * k), round(h * k)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    exp = expected(book)
    serie = f", série „{exp['serie']}“" if exp["serie"] else ""
    body = {"model": model, "temperature": 0.1, "max_tokens": 900,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}},
                {"type": "text", "text": PROMPT.format(autor=exp["autor"], nazev=exp["nazev"], serie=serie)}]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "cover", "schema": SCHEMA}}}
    t0 = time.time()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=900))
    content = resp["choices"][0]["message"]["content"]
    v = json.loads(content)
    tm = resp.get("timings", {})
    # vision = odpověď modelu (rozparsovaný JSON, popis atd. beze změny), raw = přesně text, jak ho model vrátil
    return {"cover": cover.name, "md5": md5, "size": [w, h], "bytes": len(raw), "expected": exp, "vision": v,
            "raw": content,
            "text_match": text_match(exp, v.get("text_na_obalce", "")),
            "vision_s": round(time.time() - t0, 1), "gen_tokens": tm.get("predicted_n")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("books", nargs="*", help="cesty ke knihám relativně ke knihovně (bez nich = všechny z books.txt)")
    ap.add_argument("--library", type=Path, default=LIBRARY)
    ap.add_argument("--books-cache", type=Path, default=ROOT / "data/books.txt",
                    help="seznam knih (vytváří intro-outro; obnova: transcribe_intro_outro.py --rescan)")
    ap.add_argument("--model", default="vision-fast", help="vision-fast (Gemma, rychlá) | vision (Qwen 9B, přesná)")
    ap.add_argument("--only-suspect", action="store_true",
                    help="jen knihy, které jiný model (výchozí vision-fast) označil jako podezřelé")
    ap.add_argument("--suspect-from", default="vision-fast", help="model, jehož výsledky určují podezřelé")
    ap.add_argument("--random", type=int, help="N náhodných knih (pilot)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=2, help="souběžné požadavky (gemma má 2 sloty, qwen 1)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/covers.jsonl")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--url", default="http://127.0.0.1:8100")
    args = ap.parse_args()
    json_out = args.out.with_suffix(".json")

    if args.export_only:
        return export_json(args.out, json_out)
    if args.report:
        return report(args)

    if args.books:
        books = list(args.books)
    else:
        books = [l for l in args.books_cache.read_text().split("\n") if l.strip()]
    if args.random:
        books = random.Random(args.seed).sample(books, min(args.random, len(books)))
    recs = load_records(args.out)
    if args.only_suspect:
        prev = latest_per_book(recs, args.suspect_from)
        books = [b for b in books if b in prev and is_suspect(prev[b])]
    if not args.library.is_dir():
        sys.exit(f"knihovna {args.library} není dostupná (NAS?)")

    # hotovo = záznam bez chyby pro (kniha, model, md5 aktuální obálky); md5 se počítá až při zpracování,
    # takže tady stačí kniha+model s aktuální velikostí souboru (levný stat místo čtení obálky přes síť)
    done = {}
    for (b, m, md5), r in recs.items():
        if m == args.model and not r.get("error"):
            done[b] = r
    todo = []
    for b in books:
        c = find_cover(args.library / b)
        r = done.get(b)
        if r and c and r.get("cover") == c.name and r.get("bytes") == c.stat().st_size:
            continue
        if r and not c and r.get("cover") is None:
            continue
        todo.append(b)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} obálek ke zpracování modelem {args.model} ({len(books) - len(todo)} hotových) → {args.out}",
          file=sys.stderr)

    lock = threading.Lock()
    stop = threading.Event()
    st = {"n": 0, "t0": time.time(), "err_row": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out = args.out.open("a")

    def work(book: str) -> None:
        if stop.is_set():
            return
        t0 = time.time()
        cover = find_cover(args.library / book)
        rec = {"book": book, "model": args.model}
        try:
            if cover is None:
                rec.update({"cover": None, "md5": None, "note": "bez obálky"})
            else:
                rec.update(describe(args.url, args.model, book, cover))
        except Exception as e:  # noqa: BLE001 – jedna vadná obálka nesmí zastavit dávku
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["took_s"] = round(time.time() - t0, 1)
        rec["suspect"] = is_suspect(rec) if cover else True
        rec["at"] = datetime.datetime.now().isoformat(timespec="seconds")
        with lock:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            st["n"] += 1
            st["err_row"] = st["err_row"] + 1 if rec.get("error") else 0
            if st["err_row"] >= 10:
                print("10 chyb za sebou – končím (orchestrátor / NAS?)", file=sys.stderr)
                stop.set()
            el = time.time() - st["t0"]
            eta = el / st["n"] * (len(todo) - st["n"])
            v = rec.get("vision") or {}
            tag = "CHYBA " + rec["error"][:80] if rec.get("error") else (
                rec.get("note") or f"{v.get('typ', '?')[:14]:14s} a={int(bool(v.get('sedi_autor')))} "
                                   f"n={int(bool(v.get('sedi_nazev')))} {v.get('jistota', '?')[:4]}")
            print(f"[{st['n']}/{len(todo)} ETA {eta / 3600:4.1f} h]{'!' if rec['suspect'] else ' '} "
                  f"{rec['took_s']:5.1f}s  {tag}  {book}", file=sys.stderr)

    ex = ThreadPoolExecutor(max(1, args.workers))
    try:
        for f in [ex.submit(work, b) for b in todo]:
            f.result()
    except KeyboardInterrupt:
        print("\nCtrl+C – dokončuji rozpracované (druhé Ctrl+C = okamžitě)…", file=sys.stderr)
        stop.set()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
        out.close()
        export_json(args.out, json_out)


def report(args) -> None:
    recs = load_records(args.out)
    for model in sorted({m for (_, m, _) in recs}):
        latest = latest_per_book(recs, model)
        vals = list(latest.values())
        sus = [r for r in vals if r.get("suspect")]
        ts = [r["vision_s"] for r in vals if r.get("vision_s")]
        print(f"== {model}: {len(vals)} knih, podezřelých {len(sus)}"
              + (f", průměr {sum(ts) / len(ts):.1f} s/obálka" if ts else ""))
        why: dict[str, int] = {}
        for r in sus:
            v = r.get("vision") or {}
            k = ("chyba" if r.get("error") else "bez obálky" if r.get("cover") is None else
                 f"typ={v.get('typ')}" if v.get("typ") not in ("obalka_audioknihy", "obalka_knihy") else
                 "nesedí autor" if not v.get("sedi_autor") else "nesedí název" if not v.get("sedi_nazev") else
                 "nízká jistota")
            why[k] = why.get(k, 0) + 1
        for k, n in sorted(why.items(), key=lambda x: -x[1]):
            print(f"   {n:4d}  {k}")


if __name__ == "__main__":
    main()
