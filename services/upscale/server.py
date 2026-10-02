#!/usr/bin/env python3
"""HTTP služba pro upscale obálek – spouští ji orchestrátor (llama-swap) jako model `upscale`.

Ze serveru (přes orchestrátor, port 8100):
  curl -s http://192.168.1.10:8100/upstream/upscale/upscale \\
       -F file=@obalka.jpg -F model=siax -F width=1000 -D - -o velka.jpg

Formulář (multipart/form-data):
  file    (povinné) jpg/png/webp
  model   siax (výchozí, rychlý ~2–4 s) | atd (drobné písmo, ~10–20 s) | remacri | lsdir | x4plus |
          drct | hat | dat2 – viz MODELS níže
  width   cílová šířka v px (volitelně). Obrázek se zvětší 4× a pak lanczos zmenší na `width`.
          Když je vstup už aspoň tak široký, AI se přeskočí a jen se zmenší/vrátí (model „none“).
  min_side cílová velikost KRATŠÍ strany v px (volitelně, místo width; obálky: min_side=1000).
          Když je kratší strana už aspoň tolik, vrátí se obrázek beze změny rozměru (model „none“).
  format  jpg | png (výchozí: stejný jako vstup)
  quality kvalita JPEG 1–100 (výchozí 92)

Odpověď: přímo obrázek; hlavičky X-Upscale-Model, X-Upscale-Time-Ms, X-Upscale-Input, X-Upscale-Output.
Chyba: JSON {"error": "..."} s kódem 400/413/500.

GET /health – pro orchestrátor. GET /models – seznam modelů.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")   # RX 6600 (gfx1032) pro ROCm
os.environ.setdefault("OMP_WAIT_POLICY", "passive")           # ncnn jinak pálí CPU naprázdno

from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSCAYL = ROOT / "engines/upscayl"
ESRGAN = ROOT / "engines/realesrgan"
TORCH_MODELS = ROOT / "models/upscale"

# alias → (engine, soubor/jméno modelu). ncnn = Vulkan (rychlé), torch = PyTorch ROCm (velké transformery)
MODELS = {
    "siax":    ("ncnn", UPSCAYL / "upscayl-bin", UPSCAYL / "models", "4x_NMKD-Siax_200k"),
    "remacri": ("ncnn", UPSCAYL / "upscayl-bin", UPSCAYL / "models", "remacri-4x"),
    "lsdir":   ("ncnn", UPSCAYL / "upscayl-bin", UPSCAYL / "models", "4xLSDIRplusC"),
    "x4plus":  ("ncnn", ESRGAN / "realesrgan-ncnn-vulkan", ESRGAN / "models", "realesrgan-x4plus"),
    "atd":     ("torch", TORCH_MODELS / "4xNomosWebPhoto_atd.safetensors"),
    "drct":    ("torch", TORCH_MODELS / "4xRealWebPhoto_v4_drct-l.pth"),
    "hat":     ("torch", TORCH_MODELS / "4xNomos8kSCHAT-L.safetensors"),
    "dat2":    ("torch", TORCH_MODELS / "4xBHI_dat2_real.safetensors"),
}
DEFAULT_MODEL = "siax"
MAX_INPUT_SIDE = 2048          # 4× z 2048 px = 8192 px – víc už nedává smysl a hrozí OOM
MAX_UPLOAD = 40 * 1024 * 1024

GPU_LOCK = threading.Lock()    # GPU je jedna – požadavky po jednom
_torch_cache: dict[str, object] = {}


def upscale_ncnn(img: Image.Image, spec) -> Image.Image:
    _, binary, mdir, name = spec
    with tempfile.TemporaryDirectory(prefix="upscale-") as td:
        src, dst = Path(td) / "in.png", Path(td) / "out.png"
        img.save(src)
        p = subprocess.run([str(binary), "-i", str(src), "-o", str(dst), "-n", name, "-s", "4", "-g", "0",
                            "-m", str(mdir)], capture_output=True, text=True)
        if p.returncode != 0 or not dst.exists():
            raise RuntimeError(f"ncnn selhal: {(p.stderr or p.stdout).strip().splitlines()[-1:]}")
        out = Image.open(dst)
        out.load()
        return out


def upscale_torch(img: Image.Image, spec) -> Image.Image:
    import numpy as np
    import torch
    from spandrel import ModelLoader
    sys.path.insert(0, str(HERE))
    from upscale_torch import upscale as tiled

    path = spec[1]
    if str(path) not in _torch_cache:
        _torch_cache.clear()                          # drží se jen jeden velký model naráz
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        desc = ModelLoader().load_from_file(str(path))
        _torch_cache[str(path)] = (desc, desc.model.eval().to(dev), dev)
    desc, model, dev = _torch_cache[str(path)]
    arr = np.asarray(img, dtype=np.float32) / 255.0
    t = torch.from_numpy(arr).permute(2, 0, 1)[None].to(dev)
    out = tiled(model, t, desc.scale, tile=192, overlap=16)
    res = (out[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.uint8)
    del t, out
    if dev.type == "cuda":
        torch.cuda.empty_cache()   # vrátit mezivýsledky do VRAM poolu; drží se jen váhy modelu
    return Image.fromarray(res)


def process(data: bytes, model: str, width: int | None, fmt: str | None, quality: int,
            min_side: int | None = None) -> tuple[bytes, dict]:
    t0 = time.time()
    img = Image.open(io.BytesIO(data))
    in_fmt = (img.format or "PNG").upper()
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_INPUT_SIDE:
        raise ValueError(413, f"vstup {w}×{h} je větší než {MAX_INPUT_SIDE} px – to není malá obálka")
    used = model

    def fit(im: Image.Image) -> Image.Image:
        """Zmenšit/zvětšit lanczosem na cílovou šířku nebo kratší stranu."""
        if min_side:
            k = min_side / min(im.size)
        elif width:
            k = width / im.width
        else:
            return im
        size = (round(im.width * k), round(im.height * k))
        return im if size == im.size else im.resize(size, Image.LANCZOS)

    if (min_side and min(w, h) >= min_side) or (not min_side and width and w >= width):
        out = img if min_side else fit(img)   # už dost velký → bez AI (min_side: rozměr nechat)
        used = "none"
    else:
        spec = MODELS[model]
        with GPU_LOCK:
            out = upscale_ncnn(img, spec) if spec[0] == "ncnn" else upscale_torch(img, spec)
        out = fit(out)
    fmt = (fmt or ("jpg" if in_fmt in ("JPEG", "JPG") else "png")).lower()
    buf = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        out.save(buf, "JPEG", quality=quality, optimize=True)
        ctype = "image/jpeg"
    else:
        out.save(buf, "PNG", optimize=True)
        ctype = "image/png"
    meta = {"X-Upscale-Model": used, "X-Upscale-Time-Ms": str(round((time.time() - t0) * 1000)),
            "X-Upscale-Input": f"{w}x{h}", "X-Upscale-Output": f"{out.width}x{out.height}", "Content-Type": ctype}
    return buf.getvalue(), meta


def parse_multipart(ctype: str, body: bytes) -> dict[str, tuple[bytes, str | None]]:
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    fields = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            fields[name] = (part.get_payload(decode=True) or b"", part.get_filename())
    return fields


class Handler(BaseHTTPRequestHandler):
    server_version = "upscale/1"

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path.endswith("/health"):
            self._json(200, {"status": "ok"})
        elif path.endswith("/models"):
            self._json(200, {"default": DEFAULT_MODEL,
                             "models": {k: (v[3] if v[0] == "ncnn" else v[1].name) for k, v in MODELS.items()}})
        else:
            self._json(404, {"error": "POST /upscale, GET /health, GET /models"})

    def do_POST(self) -> None:
        if not self.path.split("?")[0].rstrip("/").endswith("/upscale"):
            return self._json(404, {"error": "POST /upscale"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD:
                return self._json(413, {"error": f"soubor větší než {MAX_UPLOAD // 2**20} MB"})
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                return self._json(400, {"error": "očekávám multipart/form-data s polem file"})
            f = parse_multipart(ctype, self.rfile.read(length))
            if "file" not in f or not f["file"][0]:
                return self._json(400, {"error": "chybí pole file"})
            model = (f.get("model", (b"",))[0].decode().strip().lower() or DEFAULT_MODEL)
            if model not in MODELS:
                return self._json(400, {"error": f"neznámý model {model!r}", "models": list(MODELS)})
            width = f.get("width", (b"",))[0].decode().strip()
            width = int(width) if width else None
            fmt = f.get("format", (b"",))[0].decode().strip() or None
            quality = int(f.get("quality", (b"92",))[0].decode().strip() or 92)
            ms = f.get("min_side", (b"",))[0].decode().strip()
            data, meta = process(f["file"][0], model, width, fmt, quality, int(ms) if ms else None)
        except ValueError as e:
            code, msg = e.args if len(e.args) == 2 and isinstance(e.args[0], int) else (400, str(e))
            return self._json(code, {"error": msg})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self.send_response(200)
        for k, v in meta.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        sys.stderr.write(f"{meta['X-Upscale-Model']} {meta['X-Upscale-Input']} → {meta['X-Upscale-Output']} "
                         f"{meta['X-Upscale-Time-Ms']} ms\n")

    def log_message(self, fmt, *args) -> None:  # stručný access log
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8104)
    a = ap.parse_args()
    print(f"upscale server na http://{a.host}:{a.port}", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
