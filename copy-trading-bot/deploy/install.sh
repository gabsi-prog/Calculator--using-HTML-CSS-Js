#!/usr/bin/env bash
# Installiert den Bot auf einem Linux-Server (Ubuntu) als Dienst, der rund um die Uhr läuft
# und nach Absturz/Neustart automatisch wieder startet.
#   Aufruf (im Ordner copy-trading-bot):  bash deploy/install.sh
set -e
cd "$(dirname "$0")/.."
DIR="$(pwd)"
sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo ">> Bitte jetzt .env ausfüllen: nano .env  – danach dieses Skript erneut starten"; exit 0; }
sed -e "s|%USER%|$USER|" -e "s|%DIR%|$DIR|g" deploy/copybot.service | sudo tee /etc/systemd/system/copybot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now copybot
echo ">> Bot läuft. Log ansehen:  journalctl -u copybot -f    Stoppen:  sudo systemctl stop copybot"
