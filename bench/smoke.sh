#!/usr/bin/env bash
# Rychlý test všech služeb (po aktualizaci enginů / změně configu).
# Předpoklad: orchestrátor běží na AI_URL (výchozí http://127.0.0.1:8100).
#   bench/smoke.sh            všechno
#   bench/smoke.sh cli        jen CLI nástroje (bez orchestrátoru)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
A="$ROOT/bench/assets"
AI="$ROOT/bin/ai"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0
ok()  { printf '  \e[32mOK\e[0m   %s\n' "$*"; }
bad() { printf '  \e[31mFAIL\e[0m %s\n' "$*"; fail=1; }
t()   { local s=$SECONDS; "$@"; echo $((SECONDS - s)); }

echo "== CLI"
out=$("$ROOT/services/vad/chapters.py" "$A/cs_3parts_gap4s.m4a" 2>&1)
[[ "$out" == *'"cut_hms": "0:00:20"'* ]] && ok "vad: hranice v 0:00:20" || bad "vad: $out"

out=$("$ROOT/services/fingerprint/compare.py" --offset 5 --length 40 "$A/fp_a_192k.mp3" "$A/fp_a_48k_shift.m4a" "$A/fp_c_other.mp3" 2>&1)
grep -q 'STEJNÁ.*fp_a_192k.mp3.*fp_a_48k_shift' <<<"$out" && ! grep -q 'STEJNÁ.*fp_c_other' <<<"$out" \
  && ok "fingerprint: stejná/jiná rozlišeno" || bad "fingerprint: $out"

"$ROOT/services/upscale/upscale.sh" "$A/cover_200.jpg" "$TMP/big.jpg" >/dev/null 2>&1
wh=$(ffprobe -v error -show_entries stream=width -of csv=p=0 "$TMP/big.jpg" 2>/dev/null)
[[ "$wh" == 800 ]] && ok "upscale: 200 → 800 px" || bad "upscale: šířka '$wh'"

[[ "${1:-}" == cli ]] && exit $fail

echo "== Orchestrátor"
"$AI" models >/dev/null && ok "orchestrátor odpovídá" || { bad "orchestrátor neběží"; exit 1; }

out=$("$AI" stt "$A/cs_intro.mp3" 2>&1)
[[ "$out" == *"Kapitola první"* ]] && ok "whisper: přepis obsahuje 'Kapitola první'" || bad "whisper: $out"

out=$("$AI" embed "kniha" "book" 2>&1 | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(len(d), len(d[0]["embedding"]))' 2>&1)
[[ "$out" == "2 1024" ]] && ok "embed: 2 × 1024" || bad "embed: $out"

for m in ${SMOKE_CHAT:-qwen4b}; do
  out=$("$AI" chat "$m" 'Odpověz jedním slovem: hlavní město Česka?' 2>&1)
  [[ "$out" == *Praha* ]] && ok "chat $m: Praha" || bad "chat $m: $out"
done

"$AI" status
exit $fail
