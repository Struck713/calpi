#!/usr/bin/env python3
"""calpi entry point. GSK_RENDERER must be set before Gtk is imported (Pi 3B: GLES 2.0 only)."""
import faulthandler
import os
import signal
import sys

faulthandler.enable(file=sys.stderr, all_threads=True)          # US-12: tracebacks for segfaults
faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
os.environ.setdefault("GSK_RENDERER", "cairo")
os.environ.setdefault("GTK_A11Y", "none")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from calpi.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
