#!/usr/bin/env bash
# Nainstaluje a spustí orchestrátor jako systemd --user službu.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.config/systemd/user
ln -sf "$HERE/llama-swap.service" ~/.config/systemd/user/llama-swap.service
systemctl --user daemon-reload
systemctl --user enable --now llama-swap.service
systemctl --user --no-pager status llama-swap.service | head -5
echo
echo "Aby běžel i bez přihlášení (po bootu):  sudo loginctl enable-linger $USER"
