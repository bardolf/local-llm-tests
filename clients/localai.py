"""Tenký klient pro lokální AI služby (orchestrátor llama-swap) – jen standardní knihovna.

Zkopíruj na server ke skriptům, nebo importuj přímo. Adresa: proměnná LOCALAI_URL
(výchozí http://192.168.1.10:8100).

    from localai import LocalAI
    ai = LocalAI()
    ai.chat("Ahoj")                                   # → str
    ai.chat_json(prompt, schema)                      # → dict (výstup vynucený JSON schématem)
    ai.embed(["text1", "text2"])                      # → list[list[float]]
    ai.transcribe("kniha.mp3", fmt="verbose_json")    # → dict / str
    ai.credits_from_transcript(text)                  # → {"autor", "nazev", "vypravec", "vydavatel", "rok"}
                                                      #   (tip: přepis dělat s prompt="autor, název, vypravěč…" z metadat)
    ai.normalize_authors(["SAPKOWSKI ANDRZEJ", ...])  # → {"SAPKOWSKI ANDRZEJ": "Andrzej Sapkowski", ...}
    img, hdr = ai.upscale("obalka.jpg", model="atd", width=1000)  # → bytes + {"X-Upscale-Model": …}
    ai.translate("A gripping thriller.")              # → "Napínavý thriller." (EN → CS, Hunyuan-MT)
    png = ai.image("Book cover illustration, no text, …")  # → PNG bytes (Z-Image-Turbo, ~65 s)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_URL = os.environ.get("LOCALAI_URL", "http://192.168.1.10:8100")

SYSTEM_LIBRARIAN = ("Jsi pečlivý knihovník audioknih. Odpovídáš česky a vždy jen validním JSON podle zadání. "
                    "Když si nejsi jistý, dej null a nic si nevymýšlej.")


class LocalAI:
    # chat_model    rychlý (gemma4b, ~43 tok/s) – volný text, jednoduché úlohy
    # precise_model přesnější (qwen9b, ~16 tok/s) – extrakce jmen, normalizace; v testu bez chyb
    def __init__(self, url: str = DEFAULT_URL, chat_model: str = "chat", precise_model: str = "chat-big",
                 embed_model: str = "embed", stt_model: str = "whisper", timeout: float = 900):
        self.url = url.rstrip("/")
        self.chat_model, self.precise_model = chat_model, precise_model
        self.embed_model, self.stt_model = embed_model, stt_model
        self.timeout = timeout

    # ---------- nízká úroveň ----------
    def _post_json(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.url + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def load(self, model: str) -> None:
        """Načte model předem (blokuje, dokud není připravený)."""
        urllib.request.urlopen(f"{self.url}/upstream/{model}/health", timeout=self.timeout).read()

    def unload(self, model: str | None = None) -> None:
        path = f"/api/models/unload/{model}" if model else "/api/models/unload"
        urllib.request.urlopen(urllib.request.Request(self.url + path, method="POST"), timeout=60).read()

    def running(self) -> list[dict]:
        with urllib.request.urlopen(self.url + "/running", timeout=10) as r:
            return json.load(r).get("running", [])

    # ---------- chat ----------
    def chat(self, prompt: str, system: str | None = None, model: str | None = None,
             temperature: float = 0.2, max_tokens: int = 1500, **extra: Any) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": model or self.chat_model, "messages": msgs,
                "temperature": temperature, "max_tokens": max_tokens, **extra}
        return self._post_json("/v1/chat/completions", body)["choices"][0]["message"]["content"]

    def chat_json(self, prompt: str, schema: dict, system: str = SYSTEM_LIBRARIAN, **kw: Any) -> dict:
        """Výstup je gramatikou vynucený na dané JSON schéma → vždy parsovatelný."""
        rf = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
        return json.loads(self.chat(prompt, system=system, response_format=rf, **kw))

    # ---------- embeddingy ----------
    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        r = self._post_json("/v1/embeddings", {"model": model or self.embed_model, "input": texts})
        return [d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])]

    # ---------- přepis ----------
    def transcribe(self, path: str | Path, fmt: str = "json", language: str = "cs",
                   prompt: str | None = None, **fields: Any) -> Any:
        """fmt: json | text | srt | vtt | verbose_json. prompt = nápověda (jména postav apod.)."""
        path = Path(path)
        form = {"model": self.stt_model, "response_format": fmt, "language": language, **fields}
        if prompt:
            form["prompt"] = prompt
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in form.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(self.url + "/v1/audio/transcriptions", b"".join(parts),
                                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = r.read().decode()
        return json.loads(body) if fmt in ("json", "verbose_json") else body

    # ---------- překlad ----------
    def translate(self, text: str | list[str], source: str = "en", target: str = "cs",
                  model: str | None = None) -> str | list[str]:
        """Překlad přes službu `translate` (prompt pro překladový model skládá služba).
        model: hunyuan (výchozí, nejlepší) | translategemma (rychlejší, menší) | gemma. Odstavce se zachovají."""
        body = {"source": source, "target": target, **({"model": model} if model else {})}
        body["texts" if isinstance(text, list) else "text"] = text
        r = self._post_json("/upstream/translate/translate", body)
        return r["translations"] if isinstance(text, list) else r["translation"]

    # ---------- generování obrázků ----------
    def image(self, prompt: str, size: str = "1024x1024", model: str = "image") -> bytes:
        """Vygeneruje obrázek (Z-Image-Turbo přes stable-diffusion.cpp, ~65 s pro 1024²). Vrací PNG bytes.
        Text v obrázku umí (i diakritiku), ale může ho zkomolit/zopakovat – zkontrolovat (vision) nebo vsadit dodatečně."""
        body = {"model": model, "prompt": prompt, "size": size, "n": 1, "response_format": "b64_json"}
        r = self._post_json("/v1/images/generations", body)
        return base64.b64decode(r["data"][0]["b64_json"])

    def edit_image(self, path: str | Path, prompt: str, size: int = 768, seed: int | None = None) -> tuple[bytes, dict]:
        """Upraví obrázek podle instrukce (FLUX.2-klein 4B), např. „Turn this photo into a comic book illustration
        of the same person…“ (anglicky). ~50 s / 768 px. Vrací (PNG bytes, hlavičky X-Edit-*)."""
        path = Path(path)
        form = {"prompt": prompt, "size": size, **({"seed": seed} if seed is not None else {})}
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in form.items()]
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(self.url + "/upstream/image-edit/edit", b"".join(parts),
                                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read(), {k: v for k, v in r.headers.items() if k.lower().startswith("x-edit")}

    # ---------- upscale obálek ----------
    def upscale(self, path: str | Path, model: str = "siax", width: int | None = None,
                fmt: str | None = None) -> tuple[bytes, dict]:
        """Zvětší obrázek (služba `upscale` za orchestrátorem). model: siax (rychlý) | atd (drobné písmo) | …
        Vrací (bytes obrázku, hlavičky X-Upscale-*)."""
        path = Path(path)
        form = {"model": model, **({"width": width} if width else {}), **({"format": fmt} if fmt else {})}
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in form.items()]
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(self.url + "/upstream/upscale/upscale", b"".join(parts),
                                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read(), {k: v for k, v in r.headers.items() if k.lower().startswith("x-upscale")}

    # ---------- úlohy pro audioknihovnu ----------
    def credits_from_transcript(self, transcript: str) -> dict:
        schema = {"type": "object", "properties": {
            "autor": {"type": ["string", "null"]}, "nazev": {"type": ["string", "null"]},
            "vypravec": {"type": ["string", "null"]}, "vydavatel": {"type": ["string", "null"]},
            "rok": {"type": ["integer", "null"]}},
            "required": ["autor", "nazev", "vypravec", "vydavatel", "rok"]}
        return self.chat_json(
            "Z přepisu začátku audioknihy vytáhni autora, název knihy, vypravěče a vydavatele.\n"
            "- Přepis je automatický: slova mohou být slepená nebo zkomolená, oprav zjevné chyby.\n"
            "- Vypravěč je uveden po slovesu „čte“ / „čtou“ / „účinkuje“ / „v podání“ – "
            "sloveso není součástí jména.\n"
            "- Název je jen název knihy, bez série a pořadí dílu (ty nepatří do pole nazev).\n\n"
            f'Přepis: "{transcript}"', schema, model=self.precise_model)

    def normalize_authors(self, names: list[str]) -> dict[str, str]:
        schema = {"type": "object", "properties": {"mapovani": {"type": "array", "items": {
            "type": "object", "properties": {"vstup": {"type": "string"}, "normalizovane": {"type": "string"}},
            "required": ["vstup", "normalizovane"]}}}, "required": ["mapovani"]}
        r = self.chat_json(
            'Normalizuj tato jména autorů do tvaru "Jméno Příjmení". '
            "Vždy použij správnou původní diakritiku i tehdy, když ve vstupu chybí "
            "(česká, slovenská, polská jména mají háčky a čárky). Stejné osoby sjednoť na jeden tvar.\n\n" + json.dumps(names, ensure_ascii=False), schema,
            model=self.precise_model)
        return {m["vstup"]: m["normalizovane"] for m in r["mapovani"]}


if __name__ == "__main__":
    import sys
    ai = LocalAI(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
    print(ai.running())
