#!/usr/bin/env bash
# Headless smoke test: start, wait, check log markers, quit. Exit 0 = pass.
set -euo pipefail
cd "$(dirname "$0")/.."
DISPLAY_NUM="${BROADWAY_DISPLAY:-:6}"     # separate display from dev-run
pgrep -f "gtk4-broadwayd $DISPLAY_NUM" >/dev/null || { setsid nohup gtk4-broadwayd "$DISPLAY_NUM" >/dev/null 2>&1 </dev/null & sleep 1; }
STATE="$(mktemp -d)"
LOG="$(mktemp)"
trap 'rm -rf "$STATE" "$LOG"' EXIT
rc=0
GDK_BACKEND=broadway BROADWAY_DISPLAY="$DISPLAY_NUM" \
  CALPI_SKIP_SETUP=1 timeout 20 /usr/bin/python3 run.py --windowed --state-dir "$STATE" --exit-after "${SMOKE_SECONDS:-3}" "$@" >"$LOG" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || { cat "$LOG"; echo "SMOKE FAIL: exit $rc"; exit 1; }
grep -q "calpi ready" "$LOG"   || { cat "$LOG"; echo "SMOKE FAIL: no ready line"; exit 1; }
grep -q "screen=calendar" "$LOG" || { cat "$LOG"; echo "SMOKE FAIL: calendar screen not shown"; exit 1; }
grep -q "month_view: showing" "$LOG" || { cat "$LOG"; echo "SMOKE FAIL: no month_view line"; exit 1; }
if grep -E "Traceback|CRITICAL|ERROR" "$LOG"; then echo "SMOKE FAIL: errors in log"; exit 1; fi
# US-32: an empty state directory starts the setup wizard
WLOG="$(mktemp)"; WSTATE="$(mktemp -d)"
trap 'rm -rf "$STATE" "$LOG" "$WLOG" "$WSTATE"' EXIT
GDK_BACKEND=broadway BROADWAY_DISPLAY="$DISPLAY_NUM" CALPI_SKIP_SETUP=0 \
  timeout 20 /usr/bin/python3 run.py --windowed --state-dir "$WSTATE" --exit-after 2 >"$WLOG" 2>&1 || { cat "$WLOG"; echo "SMOKE FAIL: wizard run"; exit 1; }
grep -q "setup: start screen=wizard" "$WLOG" || { cat "$WLOG"; echo "SMOKE FAIL: wizard not started on empty state"; exit 1; }
echo "SMOKE OK"
