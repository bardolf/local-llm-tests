#!/bin/sh
# Stáhne z desktopu aktuální verzi úlohy intro-outro (snapshot) a její výsledky.
set -e
cd "$(dirname "$0")"
H=milan@192.168.1.10
J=projects/llm/jobs/intro-outro
scp -q -o BatchMode=yes "$H:$J/transcribe_intro_outro.py" "$H:$J/README.md" intro-outro/
mkdir -p ../data/transcripts
for f in intro-outro.jsonl intro-outro.json; do
  scp -q -o BatchMode=yes "$H:projects/llm/data/$f" ../data/transcripts/ 2>/dev/null && echo "staženo: data/transcripts/$f" || echo "na desktopu zatím není: $f"
done
wc -l ../data/transcripts/intro-outro.jsonl 2>/dev/null || true
