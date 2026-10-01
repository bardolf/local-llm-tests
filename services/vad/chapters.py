#!/usr/bin/env python3
"""Najde dlouhé pauzy v nahrávce (Silero VAD) → kandidáti na hranice kapitol.

Použití:
  chapters.py kniha.m4b                      # JSON se seznamem pauz ≥ 2 s
  chapters.py kniha.mp3 --min-gap 3.5        # jen pauzy ≥ 3.5 s
  chapters.py kniha.m4b --ffmetadata > ch.txt   # kapitoly pro ffmpeg -i ch.txt -map_metadata 1
  chapters.py kniha.m4b --top 40             # 40 nejdelších pauz (když víš, kolik kapitol čekat)

Libovolný vstupní formát se nejdřív převede ffmpegem na 16 kHz mono FLAC (dočasně).
VAD běží na CPU (stačí; 6 h nahrávky ≈ desítky sekund).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VAD_BIN = ROOT / "engines/whisper.cpp/build/bin/whisper-vad-speech-segments"
VAD_MODEL = ROOT / "models/vad/ggml-silero-v6.2.0.bin"
SEG_RE = re.compile(r"start = ([\d.]+), end = ([\d.]+)")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def speech_segments(path: Path, threads: int, min_silence_ms: int) -> list[tuple[float, float]]:
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR", "/var/tmp")) as tmp:
        flac = Path(tmp) / "a.flac"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(flac)],
            check=True,
        )
        out = subprocess.run(
            [str(VAD_BIN), "-vm", str(VAD_MODEL), "-f", str(flac), "-t", str(threads),
             "-vsd", str(min_silence_ms), "--no-prints"],
            capture_output=True, text=True, check=True,
        ).stdout
    # výstup je v setinách sekundy
    return [(float(a) / 100, float(b) / 100) for a, b in SEG_RE.findall(out)]


def gaps(segs: list[tuple[float, float]], total: float) -> list[dict]:
    res, prev_end = [], 0.0
    for start, end in segs:
        if start > prev_end:
            res.append({"start": round(prev_end, 2), "end": round(start, 2), "dur": round(start - prev_end, 2)})
        prev_end = end
    if total > prev_end:
        res.append({"start": round(prev_end, 2), "end": round(total, 2), "dur": round(total - prev_end, 2)})
    return res


def fmt(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--min-gap", type=float, default=2.0, help="minimální délka pauzy v s (výchozí 2.0)")
    ap.add_argument("--top", type=int, help="vrátit jen N nejdelších pauz")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--ffmetadata", action="store_true", help="výstup jako ;FFMETADATA1 kapitoly")
    args = ap.parse_args()

    total = probe_duration(args.file)
    segs = speech_segments(args.file, args.threads, int(args.min_gap * 1000 * 0.5))
    # okrajové ticho (začátek/konec souboru) není hranice kapitoly
    cands = [g for g in gaps(segs, total) if g["dur"] >= args.min_gap and 0 < g["start"] and g["end"] < total]
    if args.top:
        cands = sorted(sorted(cands, key=lambda g: -g["dur"])[: args.top], key=lambda g: g["start"])
    # řez dáváme doprostřed pauzy
    for g in cands:
        g["cut"] = round((g["start"] + g["end"]) / 2, 2)
        g["cut_hms"] = fmt(g["cut"])

    if args.ffmetadata:
        cuts = [0.0] + [g["cut"] for g in cands] + [total]
        print(";FFMETADATA1")
        for i, (a, b) in enumerate(zip(cuts, cuts[1:]), 1):
            print(f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(a * 1000)}\nEND={int(b * 1000)}\ntitle=Kapitola {i}")
    else:
        json.dump({"file": str(args.file), "duration": round(total, 2), "speech_segments": len(segs),
                   "gaps": cands}, sys.stdout, ensure_ascii=False, indent=2)
        print()


if __name__ == "__main__":
    main()
