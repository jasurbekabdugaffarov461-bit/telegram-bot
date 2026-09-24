#!/bin/bash
# VPS (Ubuntu/Debian) da bot.py va userbot.py ni doimiy xizmat sifatida o'rnatadi.
set -e
DIR="$HOME/telegram-bot"
cd "$DIR"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
USER_NAME=$(whoami)

echo ">>> Python o'rnatilmoqda..."
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq python3 python3-venv python3-pip >/dev/null

echo ">>> Kutubxonalar o'rnatilmoqda..."
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q "python-telegram-bot>=22.0" telethon google-genai

make_service () {
  NAME=$1; SCRIPT=$2
  $SUDO tee /etc/systemd/system/$NAME.service >/dev/null <<EOF
[Unit]
Description=$NAME ($SCRIPT)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python -u $DIR/$SCRIPT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
}

echo ">>> Xizmatlar yaratilmoqda..."
make_service tgbot bot.py
make_service userbot userbot.py
$SUDO systemctl daemon-reload
$SUDO systemctl enable tgbot userbot >/dev/null 2>&1
$SUDO systemctl restart tgbot userbot

sleep 8
echo
echo "================ HOLAT ================"
for S in tgbot userbot; do
  printf "%-8s : %s\n" "$S" "$($SUDO systemctl is-active $S)"
done
echo "======================================="
echo "Oxirgi loglar:"
$SUDO journalctl -u tgbot -u userbot -n 15 --no-pager
