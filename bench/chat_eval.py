#!/usr/bin/env python3
"""Porovnání chat modelů na úlohách z audioknihovny (přes orchestrátor).

  bench/chat_eval.py qwen9b qwen4b gemma4b        → výsledky do bench/results/chat-<datum>.md

Každá úloha chce JSON podle schématu (llama-server vynutí gramatikou), měří se čas
a rychlost generování. Hodnocení správnosti je zatím ruční – viz výstupní MD.
"""
import datetime
import json
import sys
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8100"
OUT = Path(__file__).parent / "results"

SYSTEM = ("Jsi pečlivý knihovník audioknih. Odpovídáš česky a vždy jen validním JSON podle zadání. "
          "Když si nejsi jistý, dej null a nic si nevymýšlej.")

TASKS = [
    {
        "id": "credits",
        "desc": "Vytáhnout vypravěče a vydavatele z přepisu začátku audioknihy",
        "prompt": """Z přepisu začátku audioknihy (z automatického přepisu řeči, může obsahovat chyby)
vytáhni autora, název, vypravěče (kdo čte) a vydavatele. Oprav zjevné chyby přepisu jmen.

Přepis: "Andrnej Sapkovsky, naklínač, kniha treky, kremelfu. Čtejan Chichlík. Vydalo nakladatelství tympanum v roce 2020. Kapitola první."
""",
        "schema": {"type": "object", "properties": {
            "autor": {"type": ["string", "null"]}, "nazev": {"type": ["string", "null"]},
            "vypravec": {"type": ["string", "null"]}, "vydavatel": {"type": ["string", "null"]},
            "rok": {"type": ["integer", "null"]}},
            "required": ["autor", "nazev", "vypravec", "vydavatel", "rok"]},
        "expect": "Andrzej Sapkowski / Krev elfů / Jan Hyhlík / Tympanum / 2020",
    },
    {
        "id": "authors",
        "desc": "Normalizace jmen autorů",
        "prompt": """Normalizuj tato jména autorů do tvaru "Jméno Příjmení" s českou/původní diakritikou.
Stejné osoby sjednoť na jeden tvar.

["SAPKOWSKI ANDRZEJ", "Sapkowski, A.", "Andrzej Sapkovski", "Nemcova Bozena", "B. Němcová", "Pratchett, Terry", "T.Pratchett", "Čapek K.", "karel capek"]
""",
        "schema": {"type": "object", "properties": {"mapovani": {"type": "array", "items": {
            "type": "object", "properties": {"vstup": {"type": "string"}, "normalizovane": {"type": "string"}},
            "required": ["vstup", "normalizovane"]}}}, "required": ["mapovani"]},
        "expect": "Andrzej Sapkowski ×3, Božena Němcová ×2, Terry Pratchett ×2, Karel Čapek ×2",
    },
    {
        "id": "chapters",
        "desc": "Z kódů souborů udělat názvy kapitol",
        "prompt": """Audiokniha "Zaklínač: Čas opovržení" má soubory pojmenované kódy. Navrhni čitelné
názvy kapitol (česky, např. "Kapitola 3"; prolog/epilog pojmenuj tak). Pořadí zachovej.
Formát kódu: <zkratka>_<slovo z názvu>_<číslo kapitoly>_<číslo části>.

["WD_Cas_00_01", "WD_Cas_01_01", "WD_Cas_01_02", "WD_Cas_02_01", "WD_Cas_09_07", "WD_Cas_10_01"]
""",
        "schema": {"type": "object", "properties": {"kapitoly": {"type": "array", "items": {
            "type": "object", "properties": {"kod": {"type": "string"}, "nazev": {"type": "string"}},
            "required": ["kod", "nazev"]}}}, "required": ["kapitoly"]},
        "expect": "00 → Prolog; 01_01 → Kapitola 1 (část 1); 09_07 → Kapitola 9 (část 7) …",
    },
    {
        "id": "series",
        "desc": "Navrhnout sérii a pořadí dílu (znalost)",
        "prompt": """Ke každé knize urči sérii (český název) a pořadí dílu v sérii. Když nevíš, null.

["Andrzej Sapkowski – Krev elfů", "Andrzej Sapkowski – Křest ohněm", "Terry Pratchett – Barva kouzel", "Jo Nesbø – Žízeň", "Karel Čapek – Krakatit"]
""",
        "schema": {"type": "object", "properties": {"knihy": {"type": "array", "items": {
            "type": "object", "properties": {"kniha": {"type": "string"}, "serie": {"type": ["string", "null"]},
                                             "dil": {"type": ["integer", "null"]}},
            "required": ["kniha", "serie", "dil"]}}}, "required": ["knihy"]},
        "expect": "Zaklínač 3 (sága 1), Zaklínač 5 (sága 3), Úžasná Zeměplocha 1, Harry Hole 11, Krakatit null",
    },
    {
        "id": "free_cz",
        "desc": "Volná čeština – krátká anotace",
        "prompt": """Napiš dvouvětou anotaci audioknihy "Babička" od Boženy Němcové pro katalog.
Vrať JSON {"anotace": "..."}.""",
        "schema": {"type": "object", "properties": {"anotace": {"type": "string"}}, "required": ["anotace"]},
        "expect": "gramaticky správná čeština, bez halucinací",
    },
]


def call(model: str, task: dict) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task["prompt"]}],
        "temperature": 0.2,
        "max_tokens": 1500,
        "response_format": {"type": "json_schema", "json_schema": {"name": task["id"], "schema": task["schema"]}},
    }
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    dt = time.time() - t0
    tm = r.get("timings", {})
    return {"wall": dt, "content": r["choices"][0]["message"]["content"],
            "prompt_tps": tm.get("prompt_per_second"), "gen_tps": tm.get("predicted_per_second"),
            "gen_tokens": tm.get("predicted_n")}


def main() -> None:
    models = sys.argv[1:] or ["qwen9b"]
    OUT.mkdir(exist_ok=True)
    out = OUT / f"chat-{datetime.datetime.now():%Y%m%d-%H%M}.md"
    lines = [f"# Chat eval {datetime.datetime.now():%Y-%m-%d %H:%M}", ""]
    summary = []
    for m in models:
        print(f"== {m}: načítám…", file=sys.stderr)
        t0 = time.time()
        urllib.request.urlopen(f"{URL}/upstream/{m}/health", timeout=600).read()
        load = time.time() - t0
        lines += [f"## {m}", "", f"Načtení modelu: {load:.1f} s", ""]
        for t in TASKS:
            print(f"   {t['id']}…", file=sys.stderr)
            try:
                r = call(m, t)
            except Exception as e:  # noqa: BLE001 – chceme pokračovat s dalšími úlohami
                lines += [f"### {t['id']} – CHYBA", "", f"`{e}`", ""]
                continue
            try:
                pretty = json.dumps(json.loads(r["content"]), ensure_ascii=False, indent=1)
            except json.JSONDecodeError:
                pretty = r["content"]
            gen = f"{r['gen_tps']:.1f}" if r["gen_tps"] else "?"
            pp = f"{r['prompt_tps']:.0f}" if r["prompt_tps"] else "?"
            lines += [f"### {t['id']} – {t['desc']}", "",
                      f"{r['wall']:.1f} s · gen {gen} tok/s ({r['gen_tokens']} tok) · prompt {pp} tok/s", "",
                      f"Očekáváno: {t['expect']}", "", "```json", pretty, "```", ""]
            summary.append((m, t["id"], r["wall"], r["gen_tps"]))
    lines += ["## Souhrn", "", "| model | úloha | čas s | gen tok/s |", "|---|---|---|---|"]
    lines += [f"| {m} | {t} | {w:.1f} | {g or 0:.1f} |" for m, t, w, g in summary]
    out.write_text("\n".join(lines) + "\n")
    print(out)


if __name__ == "__main__":
    main()
