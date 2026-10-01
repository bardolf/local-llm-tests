# Služby (podprojekty)

Každá služba je samostatný adresář se skriptem, který jde pustit ručně. Orchestrátor
(`orchestrator/`) volá serverové služby stejnými skripty a předá jim port.

| Adresář | Typ | Engine | GPU | Spuštění ručně |
|---|---|---|---|---|
| [chat/](chat/) | HTTP server | llama-server | ano | `chat/run.sh qwen9b 8101` |
| [embed/](embed/) | HTTP server | llama-server --embedding | ano | `embed/run.sh bge-m3 8102` |
| [whisper/](whisper/) | HTTP server | whisper-server | ano | `whisper/run.sh turbo-q8 8103` |
| [upscale/](upscale/) | CLI | realesrgan-ncnn-vulkan | ano | `upscale/upscale.sh in.jpg out.jpg 800` |
| [vad/](vad/) | CLI | whisper-vad-speech-segments (Silero) | ne | `vad/chapters.py kniha.m4b` |
| [fingerprint/](fingerprint/) | CLI | fpcalc (Chromaprint) | ne | `fingerprint/compare.py a.mp3 b.m4b` |

`common.sh` – společné cesty; `HOST` (výchozí 127.0.0.1) určuje, kde server poslouchá.

## Ruční spuštění bez orchestrátoru

```bash
HOST=0.0.0.0 services/chat/run.sh qwen9b 8101      # poslouchat i v LAN (pozor na firewall)
services/chat/run.sh qwen4b                          # jen lokálně, port 8101
LLM_EXTRA_ARGS="-c 32768" services/chat/run.sh qwen9b   # extra parametry pro llama-server
```

## Rychlé testy

```bash
# chat
curl -s localhost:8101/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "messages":[{"role":"user","content":"Ahoj, kdo jsi?"}]}' | jq -r .choices[0].message.content

# embeddingy
curl -s localhost:8102/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"input":["Zaklínač Geralt","Witcher Geralt"]}' | jq '.data[].embedding|length'

# přepis (libovolný formát díky --convert)
curl -s localhost:8103/v1/audio/transcriptions -F file=@ukazka.mp3 -F response_format=json
#   response_format: json | text | srt | vtt | verbose_json ; language=cs je výchozí
```
