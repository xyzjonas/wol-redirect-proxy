#!/bin/bash

set -e

virtualenv="$HOME/.virtualenvs/wol-proxy-$(date -I)"

mkdir -p "$virtualenv" && pushd "$virtualenv"
python -m venv .
source ./bin/activate
pip install -U wol-redirect-proxy

cmd="$(which wol-proxy)"
echo
echo -e "Run WoL proxy as \e[32m$cmd\e[0m"
echo
echo or to enable as a systemd service:
echo
echo 1. Save the following as /etc/systemd/system/wol-proxy.service
echo 2. sudo systemctl daemon-reload
echo 3. sudo systemctl enable --now wol-proxy
echo
echo "[Unit]"
echo Description=Wake-on-LAN proxy
echo After=network.target
echo
echo "[Service]"
echo Type=simple
echo "User=$USER"
echo "ExecStart=$cmd"
echo Restart=on-failure
echo
echo "[Install]"
echo WantedBy=multi-user.target