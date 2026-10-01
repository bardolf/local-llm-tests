# Klienti

`localai.py` – jeden soubor, jen standardní knihovna Pythonu (3.9+). Zkopírovat na server ke
skriptům audioknihovny.

```python
from localai import LocalAI
ai = LocalAI("http://192.168.1.10:8100")      # nebo env LOCALAI_URL

# 1) přepis začátku s nápovědou jmen z metadat → výrazně lepší jména
tx = ai.transcribe("kniha.mp3", fmt="text", duration=60000,
                   prompt="Andrzej Sapkowski, Zaklínač, Krev elfů, Jan Hyhlík, Tympanum")
# 2) extrakce (používá přesnější qwen9b = "chat-big")
ai.credits_from_transcript(tx)
# → {"autor": "Andrzej Sapkowski", "nazev": "Krev elfů", "vypravec": "Jan Hyhlík",
#    "vydavatel": "nakladatelství Tympanum", "rok": 2020}

ai.normalize_authors(["Nemcova Bozena", "Hrabal B."])   # → Božena Němcová, Bohumil Hrabal
ai.embed(["anotace 1", "anotace 2"])                     # → 2 × 1024 floatů (bge-m3)
ai.chat_json("…", schema)                                # libovolná úloha s vynuceným JSON
ai.unload()                                              # uvolnit GPU
```

Volba modelu: `ai.chat(..., model="chat")` (gemma4b, rychlý) vs. `model="chat-big"` (qwen9b,
přesnější, ~4× pomalejší). Při přepnutí orchestrátor sám vymění modely ve VRAM (pár sekund).

Pozn.: `duration` (ms) a `offset_t` jsou parametry whisper-serveru – přepis jen části souboru.
Celý soubor se ale stejně posílá po síti.
