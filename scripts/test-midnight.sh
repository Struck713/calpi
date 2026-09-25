#!/usr/bin/env bash
# Midnight rollover integration tests (US-10). Exit 0 = pass.
set -euo pipefail
cd "$(dirname "$0")/.."
DISPLAY_NUM="${BROADWAY_DISPLAY:-:6}"
pgrep -f "gtk4-broadwayd $DISPLAY_NUM" >/dev/null || { setsid nohup gtk4-broadwayd "$DISPLAY_NUM" >/dev/null 2>&1 </dev/null & sleep 1; }
run() {  # $1=fake now, remaining env assignments via env
  local state log; state="$(mktemp -d)"; log="$(mktemp)"
  env "${@:2}" CALPI_FAKE_NOW="$1" GDK_BACKEND=broadway BROADWAY_DISPLAY="$DISPLAY_NUM" \
    timeout 60 /usr/bin/python3 run.py --windowed --state-dir "$state" --exit-after 45 >"$log" 2>&1 || { cat "$log"; echo "FAIL: exit"; exit 1; }
  rm -rf "$state"; echo "$log"
}
L1="$(run 2026-09-30T23:59:30 X=1)"
grep -q "clock: day changed 2026-09-30 -> 2026-10-01" "$L1" || { cat "$L1"; echo "FAIL: no day change"; exit 1; }
grep -q "month_view: showing 2026-10" "$L1" || { cat "$L1"; echo "FAIL: month did not move"; exit 1; }
L2="$(run 2026-09-14T23:59:30 CALPI_TEST_START_MONTH=2026-11)"
grep -q "clock: day changed 2026-09-14 -> 2026-09-15" "$L2" || { cat "$L2"; echo "FAIL: no day change (browse)"; exit 1; }
grep -q "month_view: showing 2026-11" "$L2" || { cat "$L2"; echo "FAIL: not on Nov"; exit 1; }
if grep -q "showing 2026-09" "$L2"; then cat "$L2"; echo "FAIL: grid moved"; exit 1; fi
rm -f "$L1" "$L2"
echo "MIDNIGHT OK"
