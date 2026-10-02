#!/usr/bin/env python3
"""Úprava obrázku podle instrukce (FLUX.2-klein 4B, stable-diffusion.cpp) – model `image-edit` v orchestrátoru.

  curl -s http://192.168.1.10:8100/upstream/image-edit/edit \\
       -F file=@foto.jpg -F prompt="Turn this photo into a comic book illustration of the same person …" \\
       -D hlavicky.txt -o komiks.png

Formulář (multipart): file (povinné), prompt (povinné, anglicky), size (delší strana, výchozí 768, max 1024),
                      steps (výchozí 4), seed (výchozí náhodný)
Odpověď: PNG; hlavičky X-Edit-Time-Ms, X-Edit-Size. Chyba: JSON {"error": …}.

Každý požadavek spustí sd-cli (fotka jako referenční obrázek -r; ověřená cesta). Hlídání: krok > 40 s →
proces se ukončí (dlouhé GPU operace jinak vedou k resetu výpočetního kanálu – viz services/image/README.md).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SD_CLI = ROOT / "engines/stable-diffusion.cpp/build/bin/sd-cli"
M = ROOT / "models/image"
MAX_STEP_S = 40
GPU_LOCK = threading.Lock()


def parse_multipart(ctype: str, body: bytes) -> dict[str, bytes]:
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    return {p.get_param("name", header="content-disposition"): (p.get_payload(decode=True) or b"")
            for p in msg.iter_parts() if p.get_param("name", header="content-disposition")}


def edit(data: bytes, prompt: str, size: int, steps: int, seed: int) -> tuple[bytes, dict]:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    k = size / max(w, h)
    W, H = max(256, round(w * k / 16) * 16), max(256, round(h * k / 16) * 16)   # násobky 16
    with tempfile.TemporaryDirectory(prefix="image-edit-") as td:
        src, out, log = Path(td) / "in.png", Path(td) / "out.png", Path(td) / "sd.log"
        img.save(src)
        cmd = [str(SD_CLI), "--diffusion-model", str(M / "flux-2-klein-4b-Q8_0.gguf"),
               "--llm", str(M / "Qwen3-4B-Q4_K_M.gguf"), "--vae", str(M / "flux2_full_encoder_small_decoder.safetensors"),
               "-r", str(src), "-p", prompt, "--cfg-scale", "1.0", "--sampling-method", "euler", "--steps", str(steps),
               "--backend", "te=cpu", "--diffusion-fa", "-W", str(W), "-H", str(H), "-s", str(seed), "-o", str(out)]
        t0 = time.time()
        with open(log, "w") as lf:
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env={**os.environ, "GGML_VK_VISIBLE_DEVICES": "0"})
            killed = None
            while p.poll() is None:
                steps_s = re.findall(r"([\d.]+)s/it", log.read_text(errors="replace"))
                if steps_s and float(steps_s[-1]) > MAX_STEP_S:
                    p.kill()
                    killed = steps_s[-1]
                time.sleep(1)
        if killed:
            raise RuntimeError(f"krok trval {killed} s (> {MAX_STEP_S} s) – ukončeno kvůli ochraně GPU")
        if p.returncode != 0 or not out.exists():
            tail = " | ".join(log.read_text(errors="replace").strip().splitlines()[-3:])
            raise RuntimeError(f"sd-cli selhal ({p.returncode}): {tail}")
        png = out.read_bytes()
    return png, {"X-Edit-Time-Ms": str(round((time.time() - t0) * 1000)), "X-Edit-Size": f"{W}x{H}",
                 "X-Edit-Seed": str(seed), "Content-Type": "image/png"}


class Handler(BaseHTTPRequestHandler):
    server_version = "image-edit/1"

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
        self._json(404, {"error": "POST /edit (multipart file, prompt), GET /health"})

    def do_POST(self) -> None:
        if not self.path.split("?")[0].rstrip("/").endswith("/edit"):
            return self._json(404, {"error": "POST /edit"})
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            return self._json(400, {"error": "očekávám multipart/form-data s poli file a prompt"})
        f = parse_multipart(ctype, self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if not f.get("file") or not f.get("prompt"):
            return self._json(400, {"error": "chybí pole file nebo prompt"})
        try:
            size = min(1024, int(f.get("size", b"768") or 768))
            steps = int(f.get("steps", b"4") or 4)
            seed = int(f.get("seed", b"") or random.randrange(2**31))
            with GPU_LOCK:
                png, meta = edit(f["file"], f["prompt"].decode(), size, steps, seed)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self.send_response(200)
        for k, v in meta.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)

    def log_message(self, fmt, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8107)
    a = ap.parse_args()
    print(f"image-edit server na http://{a.host}:{a.port}", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
