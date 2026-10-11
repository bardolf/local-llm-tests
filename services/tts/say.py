#!/usr/bin/env python3
"""Namluvení textu přes XTTS v2 (coqui-tts), venv engines/tts.

Použití:
  engines/tts/bin/python services/tts/say.py -o out.wav -s "Ana Florence" "Text k namluvení"
  ... --ref vzorek.wav   # klonování hlasu z ~6–15 s nahrávky místo vestavěného mluvčího
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("TTS_HOME", str(ROOT / "models" / "tts"))
os.environ.setdefault("COQUI_TOS_AGREED", "1")  # CPML – jen nekomerční použití
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")  # RX 6600 (gfx1032)

import torch  # noqa: E402
from TTS.api import TTS  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("text", help="text, nebo '-' pro stdin")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("-s", "--speaker", default="Ana Florence", help="vestavěný mluvčí XTTS")
    p.add_argument("--ref", help="referenční nahrávka pro klonování hlasu")
    p.add_argument("-l", "--lang", default="cs")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--temperature", type=float, default=0.75)
    a = p.parse_args()

    text = sys.stdin.read() if a.text == "-" else a.text
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    voice = {"speaker_wav": a.ref} if a.ref else {"speaker": a.speaker}
    tts.tts_to_file(text=text, language=a.lang, file_path=a.out, speed=a.speed,
                    temperature=a.temperature, split_sentences=True, **voice)
    print(a.out)


if __name__ == "__main__":
    main()
