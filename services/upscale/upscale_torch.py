#!/usr/bin/env python3
"""Upscale velkými transformerovými SR modely (HAT, DAT, DRCT, ATD…) přes PyTorch + ROCm.

Na rozdíl od upscale.sh (ncnn/Vulkan, ESRGAN modely) tyhle architektury ncnn neumí, takže
běží v PyTorch. RX 6600 (gfx1032) ROCm oficiálně nepodporuje → HSA_OVERRIDE_GFX_VERSION=10.3.0
(gfx1030 kernely fungují). Bez GPU spadne na CPU (pomalé, ale funguje).

  engines/torch-sr/bin/python services/upscale/upscale_torch.py -m models/upscale/X.safetensors in.jpg out.png
  … --tile 192 --overlap 16 --half

Načítání modelů: spandrel (pozná architekturu ze state dictu).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from spandrel import ModelLoader  # noqa: E402


def upscale(model, img: torch.Tensor, scale: int, tile: int, overlap: int) -> torch.Tensor:
    """img: 1×3×H×W v [0,1]. Zpracování po dlaždicích s překryvem, výsledek se skládá
    váženě (lineární prolínání v překryvu), aby nebyly vidět švy."""
    _, c, h, w = img.shape
    out = torch.zeros(1, c, h * scale, w * scale, device=img.device, dtype=torch.float32)
    weight = torch.zeros_like(out)
    step = tile - overlap
    ys = list(range(0, max(h - tile, 0) + 1, step)) or [0]
    xs = list(range(0, max(w - tile, 0) + 1, step)) or [0]
    if ys[-1] + tile < h:
        ys.append(h - tile)
    if xs[-1] + tile < w:
        xs.append(w - tile)
    for y in ys:
        for x in xs:
            y1, x1 = min(y + tile, h), min(x + tile, w)
            patch = img[:, :, y:y1, x:x1]
            with torch.inference_mode():
                res = model(patch).float()
            ph, pw = res.shape[2], res.shape[3]
            # váha: 1 uprostřed, lineárně k nule do kraje překryvu
            ramp = overlap * scale
            wy = torch.ones(ph, device=img.device)
            wx = torch.ones(pw, device=img.device)
            if ramp:
                r = torch.linspace(0, 1, ramp + 2, device=img.device)[1:-1]
                if y > 0:
                    wy[:ramp] = r
                if y1 < h:
                    wy[-ramp:] = r.flip(0)
                if x > 0:
                    wx[:ramp] = r
                if x1 < w:
                    wx[-ramp:] = r.flip(0)
            wgt = (wy[:, None] * wx[None, :])[None, None]
            out[:, :, y * scale:y * scale + ph, x * scale:x * scale + pw] += res * wgt
            weight[:, :, y * scale:y * scale + ph, x * scale:x * scale + pw] += wgt
    return out / weight.clamp_min(1e-8)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("-m", "--model", required=True)
    ap.add_argument("--tile", type=int, default=192, help="velikost dlaždice ve vstupních px (menší = méně VRAM)")
    ap.add_argument("--overlap", type=int, default=16)
    ap.add_argument("--half", action="store_true", help="fp16 (méně VRAM, rychlejší; některé modely dají NaN)")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()

    dev = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    desc = loaded = ModelLoader().load_from_file(args.model)
    model = loaded.model.eval().to(dev)
    dtype = torch.float16 if args.half and dev.type == "cuda" else torch.float32
    model = model.to(dtype)

    arr = np.asarray(Image.open(args.input).convert("RGB"), dtype=np.float32) / 255.0
    img = torch.from_numpy(arr).permute(2, 0, 1)[None].to(dev, dtype)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    t0 = time.time()
    out = upscale(model, img, desc.scale, args.tile, args.overlap)
    if dev.type == "cuda":
        torch.cuda.synchronize()
    dt = time.time() - t0
    res = (out[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.uint8)
    Image.fromarray(res).save(args.output)
    peak = torch.cuda.max_memory_allocated() / 2**30 if dev.type == "cuda" else 0
    name = getattr(desc.architecture, "name", type(desc.architecture).__name__)
    params = sum(p.numel() for p in model.parameters()) / 1e6
    print(f"{os.path.basename(args.model)}: {name} {params:.1f}M param, {dev.type}"
          f"{' ' + torch.cuda.get_device_name() if dev.type == 'cuda' else ''}, {dtype}, "
          f"{arr.shape[1]}×{arr.shape[0]} → {res.shape[1]}×{res.shape[0]} za {dt:.1f} s, "
          f"VRAM špička {peak:.2f} GB", file=sys.stderr)


if __name__ == "__main__":
    main()
