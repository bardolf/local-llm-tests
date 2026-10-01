#!/bin/sh
# Stáhne z desktopu výsledky úlohy intro-outro (kód je v gitu – desktop/jobs/intro-outro).
set -e
cd "$(dirname "$0")"
H=milan@192.168.1.10
mkdir -p ../data/transcripts
for f in intro-outro.jsonl intro-outro.json; do
  scp -q -o BatchMode=yes "$H:projects/audiobooksprocessing/desktop/data/$f" ../data/transcripts/ 2>/dev/null && echo "staženo: data/transcripts/$f" || echo "na desktopu zatím není: $f"
done
wc -l ../data/transcripts/intro-outro.jsonl 2>/dev/null || true
