#!/usr/bin/env python3
"""Rozpoznání jazyka zvukové stopy (filmy) – služba `langid` v orchestrátoru.

Server pošle 1–N krátkých klipů z jedné audio stopy (ideálně z různých míst filmu); služba v každém najde řeč (VAD),
na úsecích řeči nechá Whisper určit jazyk (rozdělení pravděpodobností), výsledky zprůměruje a rozhodne.
Čeština × slovenština se při malém rozdílu dorovná podle písmen v přepisu (ě ř ů × ä ľ ĺ ŕ ô).

  curl -s http://192.168.1.10:8100/upstream/langid/detect -F file=@k1.wav -F file=@k2.wav -F file=@k3.wav

Odpověď (JSON): language (whisper název), iso639_1 ("cs"), iso639_2 ("cze" – Matroska/B), iso639_2t ("ces"),
confidence (0–1), uncertain (bool + reason), probabilities (top 5), samples (jazyk a text každého úseku),
speech_s, ms.  GET /health
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from collections import defaultdict
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = os.environ.get("ORCH_URL", "http://127.0.0.1:8100")
VAD_BIN = ROOT / "engines/whisper.cpp/build/bin/whisper-vad-speech-segments"
VAD_MODEL = ROOT / "models/vad/ggml-silero-v6.2.0.bin"
SEG_RE = re.compile(r"start = ([\d.]+), end = ([\d.]+)")
WINDOW_S = 30          # Whisper určuje jazyk z prvních 30 s vstupu
MAX_WINDOWS_PER_CLIP = 3
MIN_SPEECH_S = 8       # méně řeči celkem → uncertain

# whisper kód → (ISO 639-2/B jako v Matrosce, ISO 639-2/T)
ISO2 = {"cs": ("cze", "ces"), "sk": ("slo", "slk"), "en": ("eng", "eng"), "de": ("ger", "deu"), "fr": ("fre", "fra"),
        "es": ("spa", "spa"), "it": ("ita", "ita"), "pl": ("pol", "pol"), "ru": ("rus", "rus"), "uk": ("ukr", "ukr"),
        "hu": ("hun", "hun"), "pt": ("por", "por"), "nl": ("dut", "nld"), "sv": ("swe", "swe"), "da": ("dan", "dan"),
        "no": ("nor", "nor"), "fi": ("fin", "fin"), "ja": ("jpn", "jpn"), "zh": ("chi", "zho"), "ko": ("kor", "kor"),
        "hr": ("hrv", "hrv"), "sr": ("srp", "srp"), "sl": ("slv", "slv"), "bg": ("bul", "bul"), "ro": ("rum", "ron"),
        "el": ("gre", "ell"), "tr": ("tur", "tur"), "he": ("heb", "heb"), "ar": ("ara", "ara"), "hi": ("hin", "hin"),
        "la": ("lat", "lat")}
CZ_CHARS, SK_CHARS = set("ěřůĚŘŮ"), set("äľĺŕôÄĽĹŔÔ")


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name}: {(p.stderr or p.stdout).strip().splitlines()[-1:]}")
    return p.stdout


def speech_windows(wav: Path) -> list[tuple[float, float]]:
    """Úseky ~30 s s co nejvíc řeči (podle VAD), max MAX_WINDOWS_PER_CLIP, rovnoměrně přes klip."""
    out = run([str(VAD_BIN), "-vm", str(VAD_MODEL), "-f", str(wav), "-t", "4", "--no-prints"])
    segs = [(float(a) / 100, float(b) / 100) for a, b in SEG_RE.findall(out)]
    segs = [s for s in segs if s[1] - s[0] >= 0.8]
    if not segs:
        return []
    # okna začínají na začátcích řečových úseků; skóre = kolik řeči okno pokryje
    cands = []
    for s, _ in segs:
        cover = sum(max(0.0, min(e, s + WINDOW_S) - max(a, s)) for a, e in segs)
        cands.append((cover, s))
    cands.sort(reverse=True)
    chosen: list[tuple[float, float]] = []
    for cover, s in cands:
        if all(abs(s - c[0]) >= WINDOW_S for c in chosen):
            chosen.append((s, cover))
        if len(chosen) >= MAX_WINDOWS_PER_CLIP:
            break
    return sorted((s, cover) for s, cover in chosen)


def whisper_lang(wav: Path) -> dict:
    boundary = uuid.uuid4().hex
    fields = {"model": "whisper", "language": "auto", "response_format": "verbose_json"}
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="w.wav"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + wav.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(ORCH + "/v1/audio/transcriptions", b"".join(parts),
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def detect(clips: list[tuple[str, bytes]]) -> dict:
    t0 = time.time()
    samples, probs_sum, weight_sum, speech_total = [], defaultdict(float), 0.0, 0.0
    with tempfile.TemporaryDirectory(prefix="langid-") as td:
        td = Path(td)
        for i, (name, data) in enumerate(clips):
            src, wav = td / f"in{i}", td / f"c{i}.wav"
            src.write_bytes(data)
            run(["ffmpeg", "-loglevel", "error", "-nostdin", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
            for start, cover in speech_windows(wav):
                win = td / f"w{i}_{int(start)}.wav"
                run(["ffmpeg", "-loglevel", "error", "-nostdin", "-y", "-ss", str(start), "-t", str(WINDOW_S),
                     "-i", str(wav), str(win)])
                r = whisper_lang(win)
                lp = r.get("language_probabilities") or {}
                text = re.sub(r"\s+", " ", r.get("text", "")).strip()
                w = max(cover, 1.0)                      # vážit množstvím řeči v okně
                for k, v in lp.items():
                    probs_sum[k] += v * w
                weight_sum += w
                speech_total += cover
                top = max(lp, key=lp.get) if lp else None
                samples.append({"file": name, "start": round(start, 1), "speech_s": round(cover, 1),
                                "lang": top, "prob": round(lp.get(top, 0), 3) if top else None, "text": text[:160]})
    if not weight_sum:
        return {"language": None, "iso639_1": None, "iso639_2": None, "iso639_2t": None, "confidence": 0.0,
                "uncertain": True, "reason": "v klipech není řeč", "note": None, "probabilities": {}, "votes": {},
                "samples": [], "speech_s": 0, "ms": round((time.time() - t0) * 1000)}
    probs = {k: v / weight_sum for k, v in probs_sum.items()}
    ranked = sorted(probs.items(), key=lambda x: -x[1])
    lang, conf = ranked[0]
    note = None
    # čeština × slovenština: blízké jazyky → při malém rozdílu rozhodnou písmena v přepisu
    if lang in ("cs", "sk") and len(ranked) > 1 and ranked[1][0] in ("cs", "sk") and conf - ranked[1][1] < 0.3:
        txt = " ".join(s["text"] for s in samples)
        cz, sk = sum(c in CZ_CHARS for c in txt), sum(c in SK_CHARS for c in txt)
        if cz >= 2 * max(sk, 1):
            lang, note = "cs", f"cs/sk dorovnáno podle písmen (ěřů {cz} × äľĺŕô {sk})"
        elif sk >= 2 * max(cz, 1):
            lang, note = "sk", f"cs/sk dorovnáno podle písmen (ěřů {cz} × äľĺŕô {sk})"
        conf = probs.get(lang, conf)
    votes = defaultdict(int)
    for s in samples:
        votes[s["lang"]] += 1
    reasons = []
    if conf < 0.6:
        reasons.append(f"nízká jistota {conf:.2f}")
    if len(votes) > 1:
        reasons.append(f"úseky se neshodují {dict(votes)}")
    if speech_total < MIN_SPEECH_S:
        reasons.append(f"málo řeči ({speech_total:.0f} s)")
    iso2 = ISO2.get(lang, (None, None))
    return {"language": lang, "iso639_1": lang, "iso639_2": iso2[0], "iso639_2t": iso2[1],
            "confidence": round(conf, 3), "uncertain": bool(reasons), "reason": "; ".join(reasons) or None,
            "note": note, "probabilities": {k: round(v, 3) for k, v in ranked[:5]}, "votes": dict(votes),
            "samples": samples, "speech_s": round(speech_total, 1), "ms": round((time.time() - t0) * 1000)}


def parse_files(ctype: str, body: bytes) -> list[tuple[str, bytes]]:
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    return [(p.get_filename() or f"klip{i}", p.get_payload(decode=True) or b"")
            for i, p in enumerate(msg.iter_parts()) if p.get_param("name", header="content-disposition") == "file"]


class Handler(BaseHTTPRequestHandler):
    server_version = "langid/1"

    def _json(self, code: int, obj) -> None:
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:
        if self.path.split("?")[0].rstrip("/").endswith("/health"):
            return self._json(200, {"status": "ok"})
        self._json(404, {"error": "POST /detect (multipart file, i opakovaně), GET /health"})

    def do_POST(self) -> None:
        if not self.path.split("?")[0].rstrip("/").endswith("/detect"):
            return self._json(404, {"error": "POST /detect"})
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            return self._json(400, {"error": "očekávám multipart/form-data s polem file (může být víckrát)"})
        clips = [c for c in parse_files(ctype, self.rfile.read(int(self.headers.get("Content-Length", 0)))) if c[1]]
        if not clips:
            return self._json(400, {"error": "chybí pole file"})
        try:
            res = detect(clips)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self._json(200, res)

    def log_message(self, fmt, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8108)
    a = ap.parse_args()
    print(f"langid server na http://{a.host}:{a.port}", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
