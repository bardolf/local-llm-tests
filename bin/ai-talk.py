#!/usr/bin/env python3
"""Konverzace s modelem v terminálu – drží historii, odpověď se vypisuje průběžně.

  bin/ai talk                 # model chat-long (Gemma, 64k kontext)
  bin/ai talk chat-big        # jiný model (chat, chat-big, vision-fast, …)
  bin/ai talk chat-long -s "Jsi stručný knihovník."   # systémový prompt

Příkazy:  /reset  nová konverzace   /model X  přepnout model (historie zůstane)
          /save soubor.md  uložit konverzaci   /tokens  velikost kontextu   /exit (nebo Ctrl+D)
Víceřádkový vstup: řádek jen s \"\"\" začne a ukončí blok.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

try:
    import readline  # noqa: F401 – šipky a historie vstupu
except ImportError:
    pass

URL = os.environ.get("AI_URL", "http://127.0.0.1:8100")


def stream(model: str, messages: list[dict]) -> tuple[str, dict]:
    body = {"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True},
            "temperature": 0.7}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    text, usage = [], {}
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            usage = chunk.get("usage") or usage
            for ch in chunk.get("choices", []):
                piece = (ch.get("delta") or {}).get("content")
                if piece:
                    text.append(piece)
                    sys.stdout.write(piece)
                    sys.stdout.flush()
    print()
    return "".join(text), usage


def read_input() -> str | None:
    try:
        line = input("\033[1;34mty>\033[0m ")
    except EOFError:
        return None
    if line.strip() != '"""':
        return line
    lines = []
    while True:
        try:
            l = input("... ")
        except EOFError:
            break
        if l.strip() == '"""':
            break
        lines.append(l)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", nargs="?", default="chat-long")
    ap.add_argument("-s", "--system", help="systémový prompt")
    a = ap.parse_args()
    model = a.model
    base = [{"role": "system", "content": a.system}] if a.system else []
    messages = list(base)
    last_usage: dict = {}
    print(f"model {model} – /reset /model X /save f.md /tokens /exit")
    while True:
        q = read_input()
        if q is None or q.strip() in ("/exit", "/quit"):
            print()
            return
        if not q.strip():
            continue
        if q.strip() == "/reset":
            messages = list(base)
            print("(nová konverzace)")
            continue
        if q.startswith("/model"):
            model = q.split(maxsplit=1)[1].strip() if len(q.split()) > 1 else model
            print(f"(model {model})")
            continue
        if q.startswith("/save"):
            path = q.split(maxsplit=1)[1].strip() if len(q.split()) > 1 else "konverzace.md"
            with open(path, "w") as f:
                for m in messages:
                    f.write(f"## {m['role']}\n\n{m['content']}\n\n")
            print(f"(uloženo {path})")
            continue
        if q.strip() == "/tokens":
            print(f"(poslední dotaz: {last_usage.get('prompt_tokens', '?')} tokenů kontextu, "
                  f"odpověď {last_usage.get('completion_tokens', '?')})")
            continue
        messages.append({"role": "user", "content": q})
        sys.stdout.write("\033[1;32mai>\033[0m ")
        try:
            answer, last_usage = stream(model, messages)
        except KeyboardInterrupt:
            print("\n(přerušeno)")
            messages.pop()
            continue
        except Exception as e:  # noqa: BLE001
            print(f"\n(chyba: {e})")
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
