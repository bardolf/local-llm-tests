#!/usr/bin/env python3
"""Srovnání překladových modelů EN → CS.

  bench/translate_eval.py URL STYL [model]
  STYL = translategemma | hunyuan | generic (prompt podle doporučení autorů modelu)

Výsledky se tisknou; kvalitu je potřeba posoudit ručně (bench/results/translate-*.md).
"""
import json
import sys
import time
import urllib.request

TEXTS = {
    "anotace": ("A retired detective is drawn back into one last case when a young woman disappears from a quiet "
                "seaside town. As old secrets resurface, he must confront the mistakes that ended his career – and "
                "decide how far he is willing to go to find the truth. A gripping, atmospheric thriller about guilt, "
                "memory and redemption."),
    "metadata": "Narrated by Jim Dale. Unabridged. Book 3 of the Inspector Morse series. Running time: 11 hours 42 minutes.",
    "literatura": ("To Sherlock Holmes she is always the woman. I have seldom heard him mention her under any other "
                   "name. In his eyes she eclipses and predominates the whole of her sex. It was not that he felt any "
                   "emotion akin to love for Irene Adler. All emotions, and that one particularly, were abhorrent to "
                   "his cold, precise but admirably balanced mind."),
    "dialog": "\"You've got to be kidding me,\" she said, rolling her eyes. \"We're not doing this again. Not after last time.\"",
}

PROMPTS = {
    # model card google/translategemma-*: doporučené znění instrukce
    "translategemma": ("You are a professional English (en) to Czech (cs) translator. Your goal is to accurately convey "
                       "the meaning and nuances of the original English text while adhering to Czech grammar, "
                       "vocabulary, and cultural sensitivities.\nProduce only the Czech translation, without any "
                       "additional explanations or commentary. Please translate the following English text into "
                       "Czech:\n\n\n{text}"),
    # model card tencent/Hunyuan-MT-7B (páry bez čínštiny)
    "hunyuan": "Translate the following segment into Czech, without additional explanation.\n\n{text}",
    "generic": "Přelož následující text z angličtiny do češtiny. Vrať jen překlad, nic dalšího.\n\n{text}",
}
PARAMS = {
    "translategemma": {"temperature": 0.1},
    "hunyuan": {"temperature": 0.7, "top_k": 20, "top_p": 0.6, "repeat_penalty": 1.05},
    "generic": {"temperature": 0.1},
}


def translate(url: str, style: str, text: str, model: str = "x") -> tuple[str, float, dict]:
    body = {"model": model, "max_tokens": 600, **PARAMS[style],
            "messages": [{"role": "user", "content": PROMPTS[style].format(text=text)}]}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=600))
    return r["choices"][0]["message"]["content"].strip(), time.time() - t0, r.get("timings", {})


def main() -> None:
    url, style = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "x"
    for name, text in TEXTS.items():
        out, dt, tm = translate(url, style, text, model)
        tps = tm.get("predicted_per_second")
        print(f"### {name}  ({dt:.1f} s{f', {tps:.0f} tok/s' if tps else ''})\n{out}\n")


if __name__ == "__main__":
    main()
