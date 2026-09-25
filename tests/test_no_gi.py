import pkgutil
import subprocess
import sys

import calpi.data


def test_data_modules_do_not_import_gi():
    mods = [m.name for m in pkgutil.iter_modules(calpi.data.__path__)]
    assert {"models", "db", "event_store", "sample_data"} <= set(mods)
    code = ("import sys, importlib\n"
            + "".join(f"importlib.import_module('calpi.data.{m}')\n" for m in mods)
            + "assert 'gi' not in sys.modules, 'gi imported'\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_sync_modules_do_not_import_gi():
    import calpi.sync
    mods = [m.name for m in pkgutil.iter_modules(calpi.sync.__path__)]
    assert {"errors", "http", "caldav", "icloud", "cli"} <= set(mods)
    code = ("import sys, importlib\n"
            + "".join(f"importlib.import_module('calpi.sync.{m}')\n" for m in mods)
            + "importlib.import_module('calpi.data.accounts')\n"
            + "assert 'gi' not in sys.modules, 'gi imported'\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
