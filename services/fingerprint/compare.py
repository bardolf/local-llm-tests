#!/usr/bin/env python3
"""Akustický otisk (Chromaprint/fpcalc) – pozná stejnou nahrávku v jiném formátu/bitrate.

Použití:
  compare.py a.mp3 b.m4b                 # podobnost dvou souborů (0..1) + verdikt
  compare.py a.mp3 b.m4b c.mp3 ...       # všechny dvojice
  compare.py --json a.mp3                # surový otisk (pro uložení do DB a pozdější porovnání)

Porovnává úsek od --offset (výchozí 60 s, ať se přeskočí znělka/ohlášení) o délce --length
(výchozí 120 s). Hledá nejlepší posun ±--max-shift s (různé verze mívají jiné ticho na začátku).
Podobnost ≥ 0.85 = stejná nahrávka, 0.72–0.85 = asi stejná (jiný mastering/střih),
< 0.72 = jiná. Pozor: díky hledání nejlepšího posunu dávají i různé nahrávky ~0.60
(test: stejný hlas, jiný text = 0.60; stejná nahrávka 192k mp3 vs. 48k aac s posunem 1.5 s = 0.97).
"""
import argparse
import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# fpcalc: 1 položka otisku ≈ 0.1238 s
ITEM_SEC = 4096 / 11025 / 3


def fingerprint(path: Path, offset: float, length: float) -> list[int]:
    # fpcalc neumí začít od offsetu → vystřihneme úsek ffmpegem
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-ss", str(offset), "-t", str(length), "-i", str(path),
             "-vn", "-ac", "1", "-ar", "11025", tmp.name],
            check=True,
        )
        out = subprocess.run(["fpcalc", "-raw", "-json", "-length", str(int(length)), tmp.name],
                             capture_output=True, text=True, check=True).stdout
    return json.loads(out)["fingerprint"]


def similarity(a: list[int], b: list[int], max_shift: int) -> tuple[float, int]:
    best, best_shift = 0.0, 0
    for shift in range(-max_shift, max_shift + 1):
        pairs = [(a[i], b[i + shift]) for i in range(len(a)) if 0 <= i + shift < len(b)]
        if len(pairs) < 50:
            continue
        bits = sum(bin((x ^ y) & 0xFFFFFFFF).count("1") for x, y in pairs)
        sim = 1 - bits / (32 * len(pairs))
        if sim > best:
            best, best_shift = sim, shift
    return best, best_shift


def verdict(s: float) -> str:
    return "STEJNÁ" if s >= 0.85 else "asi stejná" if s >= 0.72 else "jiná"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="+")
    ap.add_argument("--offset", type=float, default=60.0)
    ap.add_argument("--length", type=float, default=120.0)
    ap.add_argument("--max-shift", type=float, default=10.0, help="max. posun v sekundách")
    ap.add_argument("--json", action="store_true", help="jen vypsat otisky jako JSON")
    args = ap.parse_args()

    fps = {f: fingerprint(f, args.offset, args.length) for f in args.files}
    if args.json:
        json.dump({str(f): fp for f, fp in fps.items()}, sys.stdout)
        print()
        return
    if len(args.files) < 2:
        ap.error("pro porovnání jsou potřeba aspoň 2 soubory")
    shift_items = int(args.max_shift / ITEM_SEC)
    for a, b in itertools.combinations(args.files, 2):
        s, sh = similarity(fps[a], fps[b], shift_items)
        print(f"{s:.3f}  {verdict(s):10s}  posun {sh * ITEM_SEC:+.1f}s  {a}  ↔  {b}")


if __name__ == "__main__":
    main()
