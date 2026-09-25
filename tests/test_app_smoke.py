import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.gtk
def test_smoke_script():
    r = subprocess.run([str(ROOT / "scripts/smoke.sh")], capture_output=True, text=True, timeout=40)
    assert r.returncode == 0, r.stdout + r.stderr
