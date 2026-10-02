#!/usr/bin/env python3
"""HTTP služba pro překlad – spouští ji orchestrátor jako model `translate`.

Klient nemusí znát prompt překladového modelu: služba ho složí sama a zavolá model přes orchestrátor.
Dlouhý text se překládá po odstavcích (prázdný řádek = hranice), odstavce se zachovají.

  curl -s http://192.168.1.10:8100/upstream/translate/translate -H 'Content-Type: application/json' \\
       -d '{"text": "A gripping thriller.", "source": "en", "target": "cs"}'

Požadavek (JSON): text (str) nebo texts (list[str]); source (výchozí "en"), target (výchozí "cs"),
                  model (volitelně: translategemma | hunyuan | gemma – výchozí DEFAULT_MODEL)
Odpověď: {"translation": str} nebo {"translations": [..]}, + "model", "ms"
GET /health, GET /models
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ORCH = os.environ.get("ORCH_URL", "http://127.0.0.1:8100")

LANG = {"en": "English", "cs": "Czech", "sk": "Slovak", "de": "German", "fr": "French", "es": "Spanish",
        "it": "Italian", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian", "hu": "Hungarian", "pt": "Portuguese",
        "nl": "Dutch", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish", "ja": "Japanese",
        "zh": "Chinese", "ko": "Korean"}
CS_NAMES = {"cs": "češtiny", "en": "angličtiny", "sk": "slovenštiny", "de": "němčiny", "pl": "polštiny"}

# alias → (model v orchestrátoru, styl promptu, parametry vzorkování dle model card)
MODELS = {
    "translategemma": ("translategemma", "translategemma", {"temperature": 0.1}),
    "hunyuan":        ("hunyuan-mt", "hunyuan", {"temperature": 0.7, "top_k": 20, "top_p": 0.6, "repeat_penalty": 1.05}),
    "gemma":          ("chat", "generic", {"temperature": 0.1}),
}
DEFAULT_MODEL = os.environ.get("TRANSLATE_MODEL", "hunyuan")   # srovnání 2026-10-02: nejlepší idiomy a literatura
MAX_PARALLEL = 4


def prompt(style: str, text: str, src: str, tgt: str) -> str:
    s, t = LANG.get(src, src), LANG.get(tgt, tgt)
    if style == "translategemma":   # doporučené znění z model card google/translategemma
        return (f"You are a professional {s} ({src}) to {t} ({tgt}) translator. Your goal is to accurately convey "
                f"the meaning and nuances of the original {s} text while adhering to {t} grammar, vocabulary, and "
                f"cultural sensitivities.\nProduce only the {t} translation, without any additional explanations or "
                f"commentary. Please translate the following {s} text into {t}:\n\n\n{text}")
    if style == "hunyuan":          # model card tencent/Hunyuan-MT-7B (páry bez čínštiny)
        return f"Translate the following segment into {t}, without additional explanation.\n\n{text}"
    return (f"Přelož následující text z {CS_NAMES.get(src, s)} do {CS_NAMES.get(tgt, t)}. "
            f"Vrať jen překlad, nic dalšího.\n\n{text}")


def call(model_id: str, style: str, params: dict, text: str, src: str, tgt: str) -> str:
    body = {"model": model_id, "max_tokens": max(256, len(text)), **params,
            "messages": [{"role": "user", "content": prompt(style, text, src, tgt)}]}
    req = urllib.request.Request(ORCH + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.load(r)["choices"][0]["message"]["content"].strip()
    return re.sub(r"^(překlad|translation)\s*:\s*", "", out, flags=re.I)


def translate(text: str, alias: str, src: str, tgt: str) -> str:
    model_id, style, params = MODELS[alias]
    paras = re.split(r"(\n\s*\n)", text)          # zachovat oddělovače odstavců
    chunks = [p for p in paras[::2]]
    seps = paras[1::2]
    with ThreadPoolExecutor(MAX_PARALLEL) as ex:
        done = list(ex.map(lambda p: call(model_id, style, params, p, src, tgt) if p.strip() else p, chunks))
    out = []
    for i, part in enumerate(done):
        out.append(part)
        if i < len(seps):
            out.append(seps[i])
    return "".join(out)


class Handler(BaseHTTPRequestHandler):
    server_version = "translate/1"

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        p = self.path.split("?")[0].rstrip("/")
        if p.endswith("/health"):
            return self._json(200, {"status": "ok"})
        if p.endswith("/models"):
            return self._json(200, {"default": DEFAULT_MODEL, "models": {k: v[0] for k, v in MODELS.items()}})
        self._json(404, {"error": "POST /translate, GET /health, GET /models"})

    def do_POST(self) -> None:
        if not self.path.split("?")[0].rstrip("/").endswith("/translate"):
            return self._json(404, {"error": "POST /translate"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "očekávám JSON {\"text\": …}"})
        alias = (req.get("model") or DEFAULT_MODEL).lower()
        if alias not in MODELS:
            return self._json(400, {"error": f"neznámý model {alias!r}", "models": list(MODELS)})
        src, tgt = req.get("source", "en"), req.get("target", "cs")
        t0 = time.time()
        try:
            if isinstance(req.get("texts"), list):
                res = {"translations": [translate(t, alias, src, tgt) for t in req["texts"]]}
            elif isinstance(req.get("text"), str):
                res = {"translation": translate(req["text"], alias, src, tgt)}
            else:
                return self._json(400, {"error": "chybí text (str) nebo texts (list)"})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        res.update({"model": alias, "source": src, "target": tgt, "ms": round((time.time() - t0) * 1000)})
        self._json(200, res)

    def log_message(self, fmt, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8105)
    a = ap.parse_args()
    print(f"translate server na http://{a.host}:{a.port} (výchozí model {DEFAULT_MODEL})", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
