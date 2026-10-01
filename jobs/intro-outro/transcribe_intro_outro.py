#!/usr/bin/env python3
"""Přepis začátků a konců audioknih → JSONL (pro pozdější úklid metadat přes AI).

Pro každou knihu (= adresář, který přímo obsahuje audio soubory):
  - začátek: z prvního souboru vezme prvních --scan s, VAD najde začátek řeči (přeskočí úvodní
    hudbu) a přepíše --seconds s od něj,
  - konec: z posledního souboru posledních --scan s, VAD najde konec řeči a přepíše --seconds s
    před ním.
Přepis běží na GPU (whisper přes orchestrátor), VAD na CPU. Z knihovny se jen čte.

Použití:
  transcribe_intro_outro.py                                  # celá knihovna, naváže, kde skončil
  transcribe_intro_outro.py --limit 100                      # jen dalších 100 knih
  transcribe_intro_outro.py --rescan                         # znovu projít NAS (přibyly knihy)
  transcribe_intro_outro.py "Agatha Christie/Krysy (1996)"   # konkrétní knihy
  transcribe_intro_outro.py --books-file seznam.txt          # jedna kniha (relativní cesta) na řádek
  transcribe_intro_outro.py --random 5                       # 5 náhodných knih (pro test)

Průběžně se zapisuje data/intro-outro.jsonl (1 kniha = 1 řádek, přežije pád), na konci běhu i po
Ctrl+C se z něj vygeneruje data/intro-outro.json (pole záznamů) – ten se nese na server.
Hotové knihy se přeskočí, knihy s chybou se zkusí znovu.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "clients"))
from localai import LocalAI  # noqa: E402

LIBRARY = Path("/media/disks/disk3/audio/spoken")
VAD_BIN = ROOT / "engines/whisper.cpp/build/bin/whisper-vad-speech-segments"
VAD_MODEL = ROOT / "models/vad/ggml-silero-v6.2.0.bin"
AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".flac", ".wav", ".aac", ".wma"}
SEG_RE = re.compile(r"start = ([\d.]+), end = ([\d.]+)")

# Typické halucinace Whisperu na hudbě/tichu (hlavně z titulků, na kterých se učil).
HALLUCINATIONS = re.compile(
    r"titulky vytvořil|titulky:|johnyx|amara\.org|www\.|děkuji za pozornost|"
    r"sledujte nás|odběr|subtitles by|thanks for watching|titulky pro",
    re.IGNORECASE,
)
MIN_SPEECH = 1.0  # kratší „řeč“ podle VAD bývá šum / úder hudby


def natural_key(p: Path) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(p))]


def audio_files(book: Path) -> list[Path]:
    """Audio soubory knihy včetně podadresářů typu CD1/CD2, přirozeně seřazené."""
    files = [p for p in book.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT]
    return sorted(files, key=lambda p: natural_key(p.relative_to(book)))


def scan_books(root: Path) -> list[Path]:
    """Knihy = adresáře, které přímo obsahují audio. Podadresáře CD1/CD2 se slučují k rodiči."""
    books = set()
    for d, dirs, names in os.walk(root):
        dirs.sort()
        if any(Path(n).suffix.lower() in AUDIO_EXT for n in names):
            d = Path(d)
            if re.fullmatch(r"(cd|disk|disc|část|cast|part)\s*\d+", d.name, re.IGNORECASE):
                d = d.parent
            books.add(d)
    return sorted(books, key=natural_key)


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json", str(path)],
        capture_output=True, text=True,
    ).stdout
    fmt = json.loads(out or "{}").get("format", {})
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()
            if k.lower() in {"title", "artist", "album_artist", "album", "composer", "genre", "date",
                             "comment", "description", "publisher", "copyright", "narrator", "performer"}}
    return {"duration": round(float(fmt.get("duration", 0) or 0), 1), "tags": tags}


def run(cmd: list[str]) -> str:
    """subprocess s čitelnou chybou (poslední řádky stderr), ne jen „exit status 1“."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = " | ".join((p.stderr or p.stdout).strip().splitlines()[-2:])
        raise RuntimeError(f"{Path(cmd[0]).name} selhal ({p.returncode}): {tail}")
    return p.stdout


def to_wav(src: Path, dst: Path, *, start: float | None = None, sseof: float | None = None,
           dur: float | None = None, fmt: str | None = None) -> None:
    cmd = ["ffmpeg", "-loglevel", "error", "-nostdin", "-y"]
    if sseof is not None:
        cmd += ["-sseof", f"-{sseof}"]
    if start is not None:
        cmd += ["-ss", f"{start}"]
    if dur is not None:
        cmd += ["-t", f"{dur}"]
    if fmt:
        cmd += ["-f", fmt]
    cmd += ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)]
    run(cmd)


def extract(f: Path, dst: Path, which: str, scan: float, tmp: Path) -> str:
    """Vystřihne úvodních/závěrečných `scan` s do 16 kHz WAV. Vrací použitou metodu.

    Záložní cesty (zjištěno na knihovně):
    - některá MP3 bez správné hlavičky délky: `-sseof` vrátí prázdný soubor → seek podle ffprobe,
      a když ani to, dekódovat celý soubor a konec vyříznout z WAV (tam je seek spolehlivý),
    - soubory s nečekanou strukturou (např. .mp3 = ID3 + RIFF hlavička): ffmpeg pozná špatný
      kontejner → vynutit formát podle přípony.
    """
    fmt = {".mp3": "mp3", ".m4a": "mp4", ".m4b": "mp4", ".ogg": "ogg", ".flac": "flac"}.get(f.suffix.lower())
    tries: list[tuple[str, dict]] = []
    if which == "start":
        tries = [("start", {"dur": scan}), ("start-f", {"dur": scan, "fmt": fmt})]
    else:
        tries = [("sseof", {"sseof": scan}), ("sseof-f", {"sseof": scan, "fmt": fmt})]
    errors = []
    for name, kw in tries:
        if kw.get("fmt", "x") is None:
            continue
        try:
            to_wav(f, dst, **kw)
            if wav_duration(dst) >= 1:
                return name
            errors.append(f"{name}: prázdný výstup")
        except RuntimeError as e:
            errors.append(f"{name}: {e}")
    if which == "end":
        full = tmp / "full.wav"
        for name, kw in (("full", {}), ("full-f", {"fmt": fmt})):
            if kw.get("fmt", "x") is None:
                continue
            try:
                to_wav(f, full, **kw)
                if wav_duration(full) >= 1:
                    to_wav(full, dst, sseof=scan)
                    full.unlink()
                    return name
                errors.append(f"{name}: prázdný výstup")
            except RuntimeError as e:
                errors.append(f"{name}: {e}")
    raise RuntimeError("nelze dekódovat – " + "; ".join(errors))


def wav_duration(path: Path) -> float:
    return (path.stat().st_size - 44) / 32000  # 16 kHz, mono, s16


def speech(path: Path) -> list[tuple[float, float]]:
    out = run([str(VAD_BIN), "-vm", str(VAD_MODEL), "-f", str(path), "-t", "8", "--no-prints"])
    segs = [(float(a) / 100, float(b) / 100) for a, b in SEG_RE.findall(out)]
    return [s for s in segs if s[1] - s[0] >= MIN_SPEECH]


def transcribe(ai: LocalAI, wav: Path, hint: str | None) -> dict:
    r = ai.transcribe(wav, fmt="verbose_json", language="auto", prompt=hint)
    # Text segmentu si nechává úvodní mezeru – ta značí hranici slova. Segmenty občas začínají
    # uprostřed slova, proto se spojují bez přidané mezery.
    segs = [{"start": round(s["start"], 1), "end": round(s["end"], 1), "text": s["text"]}
            for s in r.get("segments", [])]
    clean = [s for s in segs if s["text"].strip() and not HALLUCINATIONS.search(s["text"])]
    text = re.sub(r"\s+", " ", "".join(s["text"] for s in clean)).strip()
    return {"language": r.get("language"), "text": text, "segments": clean,
            "dropped": [s["text"].strip() for s in segs if s not in clean]}


def do_end(ai: LocalAI, f: Path, tmp: Path, which: str, scan: float, seconds: float,
           hint: str | None) -> dict:
    win = tmp / f"{which}_scan.wav"
    method = extract(f, win, which, scan, tmp)
    segs = speech(win)
    wdur = wav_duration(win)
    if not segs:
        return {"file": f.name, "error": "VAD nenašel řeč", "suspect": True}
    if which == "start":
        a = max(0.0, segs[0][0] - 0.5)
        b = min(wdur, a + seconds)
    else:
        b = min(wdur, segs[-1][1] + 0.5)
        a = max(0.0, b - seconds)
    cut = tmp / f"{which}.wav"
    to_wav(win, cut, start=a, dur=b - a)
    t = transcribe(ai, cut, hint)
    # běžné předčítání ≈ 10–14 znaků/s; s hudbou mezi větami ~4–5. Pod 3 zn/s je přepis neúplný
    # (test: Valenta – řeč přes hudbu Českého rozhlasu = 1.5 zn/s, Tolkien úvod + hudba = 3.9 a správně)
    t["chars_per_s"] = round(len(t["text"]) / max(b - a, 1), 1)
    t["suspect"] = bool(t["dropped"]) or len(t["text"]) < 20 or t["chars_per_s"] < 3
    pos = {"offset": round(a, 1)} if which == "start" else {"offset_from_end": round(wdur - a, 1)}
    return {"file": f.name, **pos, "length": round(b - a, 1), "extract": method, **t}


def process(ai: LocalAI, book: Path, args) -> dict:
    rel = book.relative_to(args.library)
    files = audio_files(book)
    rec = {"book": str(rel), "author": rel.parts[0], "title": book.name, "n_files": len(files)}
    if not files:
        return {**rec, "error": "žádné audio"}
    first, last = files[0], files[-1]
    rec["first_file"] = str(first.relative_to(book))
    rec["last_file"] = str(last.relative_to(book))
    rec["probe_first"] = ffprobe(first)
    hint = None if args.no_hint else f"{rec['author']}, {re.sub(r'\s*\(.*?\)', '', book.name)}."
    with tempfile.TemporaryDirectory(prefix="intro-outro-") as td:
        tmp = Path(td)
        rec["start"] = do_end(ai, first, tmp, "start", args.scan, args.seconds, hint)
        rec["end"] = do_end(ai, last, tmp, "end", args.scan, args.seconds, hint)
    return rec


def book_list(args) -> list[Path]:
    """Seznam knih celé knihovny – poprvé se projde NAS a uloží do --books-cache, pak se jen načte."""
    if args.books_cache.exists() and not args.rescan:
        return [args.library / l for l in args.books_cache.read_text().split("\n") if l.strip()]
    print(f"procházím knihovnu {args.library} (jednorázově, může trvat pár minut)…", file=sys.stderr)
    books = scan_books(args.library)
    args.books_cache.parent.mkdir(parents=True, exist_ok=True)
    args.books_cache.write_text("".join(f"{b.relative_to(args.library)}\n" for b in books))
    print(f"nalezeno {len(books)} knih → {args.books_cache}", file=sys.stderr)
    return books


def load_records(path: Path) -> dict[str, dict]:
    """JSONL → {kniha: poslední záznam}. Pozdější záznam (např. opakovaný po chybě) vyhrává."""
    recs: dict[str, dict] = {}
    if path.exists():
        # jen podle \n – str.splitlines() dělí i podle U+2028, \x1c… které bývají v přepisech/tazích
        # (json.dumps s ensure_ascii=False je nechá v textu) → rozbité řádky by se tiše zahodily
        for line in path.read_text().split("\n"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:  # useknutý poslední řádek po pádu
                continue
            recs[r["book"]] = r
    return recs


def export_json(jsonl: Path, out: Path) -> None:
    recs = sorted(load_records(jsonl).values(), key=lambda r: natural_key(Path(r["book"])))
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(recs, ensure_ascii=False))
    tmp.replace(out)  # atomicky – na server se nikdy nedostane rozepsaný soubor
    n_err = sum(1 for r in recs if r.get("error"))
    print(f"export: {len(recs)} knih ({n_err} s chybou) → {out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("books", nargs="*", help="cesty ke knihám relativně ke knihovně (bez nich = celá knihovna)")
    ap.add_argument("--library", type=Path, default=LIBRARY)
    ap.add_argument("--books-file", type=Path, help="seznam knih (relativní cesty, jedna na řádek)")
    ap.add_argument("--random", type=int, help="N náhodných knih (bez procházení celé knihovny)")
    ap.add_argument("--rescan", action="store_true", help="znovu projít knihovnu (nové knihy)")
    ap.add_argument("--books-cache", type=Path, default=ROOT / "data/books.txt")
    ap.add_argument("--out", type=Path, default=ROOT / "data/intro-outro.jsonl")
    ap.add_argument("--json", type=Path, help="výsledný JSON (výchozí: --out s příponou .json)")
    ap.add_argument("--export-only", action="store_true", help="jen přegenerovat JSON z JSONL")
    ap.add_argument("--workers", type=int, default=2,
                    help="souběžné knihy; GPU je jedna, víc vláken jen překrývá čtení z NASu a VAD (výchozí 2)")
    ap.add_argument("--limit", type=int, help="zpracovat nejvýš N knih a skončit")
    ap.add_argument("--seconds", type=float, default=60, help="délka přepisovaného úseku (s)")
    ap.add_argument("--scan", type=float, default=180, help="v jak dlouhém okně hledat řeč (s)")
    ap.add_argument("--no-hint", action="store_true", help="neposílat Whisperu autora/název jako nápovědu")
    ap.add_argument("--url", default="http://127.0.0.1:8100")
    args = ap.parse_args()
    json_out = args.json or args.out.with_suffix(".json")

    if args.export_only:
        export_json(args.out, json_out)
        return

    books: list[Path] = [b if Path(b).is_absolute() else args.library / b for b in args.books]
    if args.books_file:
        books += [args.library / l.strip() for l in args.books_file.read_text().split("\n") if l.strip()]
    if args.random:
        authors = [d for d in args.library.iterdir() if d.is_dir()]
        while len(books) < args.random and authors:
            cands = scan_books(authors.pop(random.randrange(len(authors))))
            if cands:
                books.append(random.choice(cands))
    if not books:
        books = book_list(args)
    if not args.library.is_dir():
        sys.exit(f"knihovna {args.library} není dostupná (NAS?)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # hotové = bez chyby; knihy s chybou (např. výpadek NASu) se při dalším běhu zkusí znovu
    done = {b for b, r in load_records(args.out).items() if not r.get("error")}
    todo = [b for b in books if str(b.relative_to(args.library)) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} knih ke zpracování ({len(books) - len(todo)} hotových/vynechaných) → {args.out}",
          file=sys.stderr)

    ai = LocalAI(args.url)
    lock = threading.Lock()
    stats = {"n": 0, "t0": time.time(), "errors_in_row": 0}
    stop = threading.Event()

    def work(book: Path) -> None:
        if stop.is_set():
            return
        t0 = time.time()
        try:
            rec = process(ai, book, args)
        except Exception as e:  # noqa: BLE001 – jedna vadná kniha nesmí zastavit dávku
            rec = {"book": str(book.relative_to(args.library)), "error": f"{type(e).__name__}: {e}"}
        rec["took_s"] = round(time.time() - t0, 1)
        rec["at"] = datetime.datetime.now().isoformat(timespec="seconds")
        bad = rec.get("error") or rec.get("start", {}).get("suspect") or rec.get("end", {}).get("suspect")
        with lock:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            stats["n"] += 1
            stats["errors_in_row"] = stats["errors_in_row"] + 1 if rec.get("error") else 0
            if stats["errors_in_row"] >= 10:
                print("10 chyb za sebou – končím (NAS nebo orchestrátor nedostupný?)", file=sys.stderr)
                stop.set()
            el = time.time() - stats["t0"]
            eta = el / stats["n"] * (len(todo) - stats["n"])
            print(f"[{stats['n']}/{len(todo)} ETA {eta / 3600:4.1f} h]{'!' if bad else ' '} "
                  f"{rec['took_s']:5.1f}s  {rec['book']}"
                  f"{'  CHYBA: ' + rec['error'] if rec.get('error') else ''}", file=sys.stderr)

    out = args.out.open("a")
    ex = ThreadPoolExecutor(max(1, args.workers))
    try:
        for f in [ex.submit(work, b) for b in todo]:
            f.result()
    except KeyboardInterrupt:
        print("\nCtrl+C – dokončuji rozpracované knihy (druhé Ctrl+C = okamžitě)…", file=sys.stderr)
        stop.set()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
        out.close()
        export_json(args.out, json_out)


if __name__ == "__main__":
    main()
