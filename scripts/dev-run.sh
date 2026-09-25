#!/usr/bin/env bash
# Run calpi in the devcontainer via GTK Broadway: open http://localhost:8085
set -euo pipefail
cd "$(dirname "$0")/.."
DISPLAY_NUM="${BROADWAY_DISPLAY:-:5}"
if ! pgrep -f "gtk4-broadwayd $DISPLAY_NUM" >/dev/null; then
  setsid nohup gtk4-broadwayd "$DISPLAY_NUM" >/dev/null 2>&1 </dev/null &
  sleep 1
fi
export GDK_BACKEND=broadway BROADWAY_DISPLAY="$DISPLAY_NUM"
export CALPI_STATE_DIR="${CALPI_STATE_DIR:-$PWD/.devstate}"
exec /usr/bin/python3 run.py --windowed "$@"
