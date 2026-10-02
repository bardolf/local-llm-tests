#!/usr/bin/env python3
"""Test: umí vision LLM zkontrolovat obálku audioknihy? (přečíst text, popsat, ověřit shodu s knihou)

  bench/cover_check.py URL obalka.jpg "Autor" "Název" [obalka2.jpg "Autor" "Název" …]
  URL = llama-server s --mmproj (např. http://127.0.0.1:8297) nebo orchestrátor (model v BENCH_MODEL)
"""
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request

SCHEMA = {"type": "object", "properties": {
    "text_na_obalce": {"type": "string"},
    "autor_na_obalce": {"type": ["string", "null"]},
    "nazev_na_obalce": {"type": ["string", "null"]},
    "popis": {"type": "string"},
    "je_obalka_knihy": {"type": "boolean"},
    "sedi_s_knihou": {"type": "boolean"},
    "duvod": {"type": "string"}},
    "required": ["text_na_obalce", "autor_na_obalce", "nazev_na_obalce", "popis", "je_obalka_knihy",
                 "sedi_s_knihou", "duvod"]}

PROMPT = """Kontroluješ obálku audioknihy. Očekávaná kniha: autor „{autor}“, název „{nazev}“.
1. Přepiš přesně všechen čitelný text na obrázku.
2. Urči autora a název, jak jsou na obálce (null, když tam nejsou).
3. Popiš obrázek jednou až dvěma větami česky.
4. Je to obálka knihy/audioknihy (ne fotka autora, plakát, screenshot)?
5. Odpovídá obálka očekávané knize (autor i název)?
Vrať JSON."""


def check(url: str, img: str, autor: str, nazev: str) -> tuple[dict, float]:
    b64 = base64.b64encode(open(img, "rb").read()).decode()
    mime = mimetypes.guess_type(img)[0] or "image/jpeg"
    body = {"model": os.environ.get("BENCH_MODEL", "x"), "temperature": 0.1, "max_tokens": 800,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": PROMPT.format(autor=autor, nazev=nazev)}]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "cover", "schema": SCHEMA}}}
    t0 = time.time()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=600))
    return json.loads(r["choices"][0]["message"]["content"]), time.time() - t0


def main() -> None:
    url, rest = sys.argv[1], sys.argv[2:]
    for i in range(0, len(rest), 3):
        img, autor, nazev = rest[i:i + 3]
        res, dt = check(url, img, autor, nazev)
        print(f"=== {os.path.basename(img)}  (očekáváno: {autor} – {nazev})  {dt:.1f} s")
        print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
