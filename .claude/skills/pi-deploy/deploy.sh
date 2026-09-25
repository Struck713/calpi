#!/usr/bin/env bash
# Sync the calpi project to the Pi and restart the kiosk service.
# Usage: deploy.sh [--no-restart]
set -euo pipefail

HOST="${CALPI_HOST:-calpi.local}"
[[ -n "${CALPI_USER:-}" ]] && HOST="${CALPI_USER}@${HOST}"
APP_DIR=/opt/calpi
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RESTART=1
[[ "${1:-}" == "--no-restart" ]] && RESTART=0

ssh -o ConnectTimeout=5 "$HOST" true || { echo "cannot reach $HOST" >&2; exit 1; }

echo "==> syncing $ROOT -> $HOST:$APP_DIR"
rsync -az --delete \
  --rsync-path="sudo rsync" \
  --exclude .git --exclude .claude --exclude .agents --exclude .devcontainer \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
  --exclude tests --exclude 'scratch-*' --exclude skills-lock.json \
  "$ROOT"/ "$HOST:$APP_DIR"/

ssh "$HOST" "sudo chown -R root:root $APP_DIR && sudo chmod -R a+rX $APP_DIR"

if (( RESTART )); then
  echo "==> restarting calpi-kiosk"
  ssh "$HOST" 'sudo systemctl restart calpi-kiosk && sleep 4 && systemctl is-active calpi-kiosk; journalctl -u calpi-kiosk -n 30 --no-pager'
fi
