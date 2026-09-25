import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    from calpi.widgets.sync_indicator import SyncIndicator, indicator_text
    tz = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 9, 25, 14, 30, tzinfo=tz)
    assert indicator_text(True, None, now) == "Updating\\u2026"
    assert indicator_text(False, None, now) == ""
    assert indicator_text(False, now.replace(hour=14, minute=5), now) == "Updated 14:05"
    assert indicator_text(False, (now - timedelta(days=1)).replace(hour=22, minute=15), now) == "Updated yesterday 22:15"
    eng = SimpleNamespace(state_callbacks=[], result_callbacks=[], is_running=False, last_success_wall=None)
    ind = SyncIndicator(eng)
    assert not ind.get_visible()
    eng.is_running = True
    eng.state_callbacks[0](True)
    assert ind.get_visible() and ind.get_text() == "Updating\\u2026"
    print("OK")
''')


@pytest.mark.gtk
def test_indicator():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6", GSK_RENDERER="cairo")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
