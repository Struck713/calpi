# US-02 — App skeleton

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | — (nothing) |
| **Blocks** | US-03 Deploy workflow, US-04 Local event store, US-05 Settings store, US-06 Month grid, US-11 Pointer and touch input |
| **Phase** | 1. Foundation |
| **Can run in parallel with** | US-01 Kiosk OS provisioning |

## Story

> As a developer, I want a minimal fullscreen GTK app that runs on the Pi and in the devcontainer without a display, so UI work can start.

## Context

This story sets up the code base that every other story builds on. It isn't about features. It's about **structure and conventions**: where files go, how screens are switched, how background work gets back onto the UI thread, where state is stored, how logs work, and how a developer runs and tests the app without a screen.

Take your time here. Every shortcut in this story gets copied 40 times.

Load the **`gtk-kiosk-app`** skill before writing any code. Its `example_app.py` is the reference: copy its structure, not just its ideas. The skill records several gotchas that were checked on real systems (for example, importing Gtk with no display **hangs** instead of failing).

Read the repository's [README](README.md) first as well: this story creates the modules listed there as "US-02".

---

## Blockers

### Hard blockers
None.

### External blockers

| Blocker | Why | What to do |
|---|---|---|
| **apt access in the devcontainer** (`sudo apt-get install`) | PyGObject and GTK 4 come from apt (the skill says never to `pip install PyGObject`). Broadway (`gtk4-broadwayd`) comes from `libgtk-4-bin`. | If apt fails (no network, or a proxy), stop and report it. There's no way round it. |
| **Port 8085 forwarded from the devcontainer** | To look at the Broadway UI in a browser. | Optional: the headless smoke test works without it. Ask the owner to forward the port if they want to watch. |

### Soft dependencies
- **US-01**: you don't need it to finish this story. The app has to run in the devcontainer, and on the Pi *once US-01/US-03 exist*. If US-01 is done before you finish, deploy by hand once (`scp` + restart) to confirm it starts under cage. Otherwise US-03 does that check.

### Things that may block you mid-work (and what to do)

| Problem | Symptom | What to do |
|---|---|---|
| **The devcontainer's `python3` can't see `gi`** | `ModuleNotFoundError: No module named 'gi'` | The devcontainer image (`mcr.microsoft.com/devcontainers/python:3`) puts its own Python at `/usr/local/bin/python3`. apt installs `gi` for **`/usr/bin/python3`**. Always use `/usr/bin/python3` for the app and for tests. The scripts in this story hard-code it. |
| **The app hangs on start** | Nothing prints, no exit | You imported Gtk before `GDK_BACKEND=broadway` was set and broadwayd was running. Always run through `scripts/dev-run.sh` or `scripts/smoke.sh`, and wrap automated runs in `timeout`. |
| **The shell hangs after starting broadwayd** | The command never returns | Start it fully detached: `setsid nohup gtk4-broadwayd :5 >/dev/null 2>&1 </dev/null &` (from the skill). |
| **GTK versions differ between the devcontainer and the Pi** | Code works in dev but raises `AttributeError` on the Pi | The devcontainer is probably newer (Trixie → GTK 4.18). The Pi might be on Bookworm (GTK 4.8). Until `docs/platform-versions.md` exists (US-01), **write for GTK 4.8**: no `Gtk.AlertDialog` (4.10), no `Gtk.FileDialog` (4.10), no CSS `var()` (4.16). Use `@define-color` for colours. |
| **A `Gtk.StyleContext` deprecation warning** | A warning in the log about `add_provider_for_display` | In GTK 4.10+ it's `Gtk.StyleContext.add_provider_for_display` (deprecated) versus `Gtk.style_context_add_provider_for_display`. Use whichever exists, behind one helper (step 5). |

---

## Scope

### In scope
- `run.py`, the `calpi` package, and the modules marked US-02 in the README layout.
- A fullscreen window with an invisible cursor, animations off, and the CSS loaded.
- Screen switching (`Navigator`) with one placeholder screen, called `calendar`.
- The thread helper (`run_in_thread`) and the callback guard (`safe_callback`).
- State-directory resolution (`paths.py`).
- Logging to stdout.
- The CLI flags `--windowed`, `--state-dir`, `--exit-after`.
- Dev scripts: `scripts/dev-run.sh` and `scripts/smoke.sh`.
- `deps/apt-runtime.txt` and `deps/apt-dev.txt`, plus a devcontainer `postCreateCommand` that installs them.
- `pyproject.toml` with the pytest settings, and the first tests.

### Out of scope
- The month grid (US-06), storage (US-04, US-05), and cursor auto-hide for mice (US-11: here the cursor is simply always invisible).
- Deploying (US-03). A manual `scp` once, to check, is fine.
- Anything to do with sync.

---

## Acceptance criteria

1. `scripts/smoke.sh` exits **0** in the devcontainer within 20 seconds. It starts broadwayd if needed, runs the app with `--exit-after 3`, and checks that the log contains `calpi ready` and `screen=calendar`.
2. `scripts/dev-run.sh` runs the app in Broadway at `http://localhost:8085`. The placeholder screen shows "calpi" and the current time. The time updates on the minute boundary.
3. On the Pi, under cage, the app is **fullscreen at 1920×1080** with no visible cursor and no window decorations. You can check this once US-01 is done, or it gets checked in US-03.
4. `GSK_RENDERER` is `cairo` inside the app, whether it's started by `run.py` directly or by the systemd unit. `run.py` calls `os.environ.setdefault` **before** importing Gtk.
5. `/usr/bin/python3 -m pytest` passes in the devcontainer. Tests for `paths.py` and `tasks.py` exist. Test modules that don't need a display never import Gtk.
6. `paths.state_dir()` returns `$STATE_DIRECTORY` if it's set, then `$CALPI_STATE_DIR`, then `--state-dir`, then `~/.local/state/calpi`. It creates the directory with mode 0700 if it's missing (see step 3 for the exact precedence).
7. An exception raised in a timer callback is **logged with a traceback**, and the timer **keeps running**. A test shows this.
8. An exception raised in a `run_in_thread` worker reaches `on_error` **on the main thread**, and is logged.
9. The app logs to stdout in the format `LEVEL name: message`, at INFO level by default. `CALPI_LOG_LEVEL=DEBUG` changes the level.
10. `Ctrl+Q` quits the app when it's started with `--windowed`. In kiosk mode (fullscreen), no key quits it.

---

## Design decisions (already made — follow them)

- **D1. GTK 4**, `Gtk.Application` with id `dev.calpi.Kiosk`, and exactly one `MainWindow(Gtk.ApplicationWindow)`. There's a GTK 3 fallback in the skill; only use it if US-36 proves GTK 4 is too heavy.
- **D2. Root widget tree:**
  ```
  MainWindow
  └─ Gtk.Overlay  (self.overlay)            ← later: keyboard dock, dim layer, toasts
     └─ Gtk.Stack (self.stack, transition NONE)
        └─ "calendar" → PlaceholderScreen   ← replaced by MonthView in US-06
  ```
- **D3. Screens are plain `Gtk.Widget` subclasses** that can optionally define `on_show(**params)` and `on_hide()`. The `Navigator` calls them. There's no framework beyond that.
- **D4. The package `calpi.data` and the package `calpi.sync` never import `gi`.** `paths.py` and `logging_setup.py` don't either. That keeps them testable with plain pytest and keeps the sync process light.
- **D5. `/usr/bin/python3` everywhere** (the scripts, the tests, the unit file).
- **D6. The stylesheet is a single file, `calpi/style.css`**, loaded once at `STYLE_PROVIDER_PRIORITY_APPLICATION`. Colours are defined with `@define-color` at the top. Dark background.
- **D7. No third-party pip packages in this story.** The venv fallback from the skill is only for later stories, and only if an apt package really isn't available.
- **D8. `--exit-after N`** is a test hook: after N seconds it logs the app state and quits cleanly. It's used by the smoke tests of this story and of later ones.
- **D9. Design size is 1920×1080.** In `--windowed` mode, the default window size is 1920×1080 so Broadway shows the real layout. (The browser can zoom out.) There's an optional `--scale 0.5` flag that sets a CSS scale class. **Skip `--scale`** unless it's trivial. It isn't required.

---

## Implementation plan

### Step 1 — apt dependency lists and the devcontainer

`deps/apt-runtime.txt` (what the **app** needs on the Pi; OS-level kiosk packages stay in `setup-pi.sh`):
```
# One package per line. Installed on the Pi by `scripts/pi deps` (US-03) and in the devcontainer.
python3-gi
python3-gi-cairo
gir1.2-gtk-4.0
fonts-dejavu-core
```

`deps/apt-dev.txt`:
```
# Devcontainer-only extras
libgtk-4-bin        # gtk4-broadwayd
python3-pytest
```

`.devcontainer/devcontainer.json`: add
```json
"postCreateCommand": "sudo apt-get update && grep -hvE '^\\s*(#|$)' deps/apt-runtime.txt deps/apt-dev.txt | sed 's/#.*//' | xargs sudo apt-get install -y --no-install-recommends",
"forwardPorts": [8085]
```
Check that it works by running the same command by hand now (you don't need to rebuild the container to test it). Then check:
```bash
/usr/bin/python3 -c "import gi; gi.require_version('Gtk','4.0'); print('gi ok')"   # must NOT import Gtk itself
which gtk4-broadwayd
/usr/bin/python3 -m pytest --version
```

### Step 2 — `pyproject.toml` (tool config only)

```toml
[project]
name = "calpi"
requires-python = ">=3.11"
version = "0.1.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
markers = [
  "gtk: needs a GTK display (Broadway); skipped unless CALPI_GTK_TESTS=1",
]
```
This isn't used for packaging. The Pi runs the code straight from `/opt/calpi`.

### Step 3 — `calpi/paths.py` (no gi)

```python
"""Filesystem locations. No gi imports: used by the UI and the sync process."""
from __future__ import annotations
import os
from pathlib import Path

_override: Path | None = None

def set_state_dir_override(path: str | os.PathLike | None) -> None:
    """Set from --state-dir. Tests use it too."""
    global _override
    _override = Path(path) if path else None

def state_dir() -> Path:
    """Persistent state directory, created 0700 if missing.

    Precedence: --state-dir override > $STATE_DIRECTORY (systemd) > $CALPI_STATE_DIR > ~/.local/state/calpi
    """
    if _override is not None:
        p = _override
    elif os.environ.get("STATE_DIRECTORY"):
        # systemd may pass several colon-separated dirs; we only declare one.
        p = Path(os.environ["STATE_DIRECTORY"].split(":")[0])
    elif os.environ.get("CALPI_STATE_DIR"):
        p = Path(os.environ["CALPI_STATE_DIR"])
    else:
        p = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "calpi"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p

def runtime_dir() -> Path:
    """Non-persistent scratch (tmpfs on the Pi). $RUNTIME_DIRECTORY > $XDG_RUNTIME_DIR/calpi > <state>/run"""
    if os.environ.get("RUNTIME_DIRECTORY"):
        p = Path(os.environ["RUNTIME_DIRECTORY"].split(":")[0])
    elif os.environ.get("XDG_RUNTIME_DIR"):
        p = Path(os.environ["XDG_RUNTIME_DIR"]) / "calpi"
    else:
        p = state_dir() / "run"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p

def app_dir() -> Path:
    """Directory containing the calpi package (read-only on the Pi)."""
    return Path(__file__).resolve().parent

def asset(name: str) -> Path:
    return app_dir() / "assets" / name
```
Note that the `--state-dir` override comes **first**, so a developer can point the app at a scratch directory even when `STATE_DIRECTORY` is set. Acceptance criterion 6 lists the precedence. Write the tests for this order.

### Step 4 — `calpi/logging_setup.py` (no gi)

```python
import logging, os, sys

def setup_logging() -> None:
    level = os.environ.get("CALPI_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",   # journald adds timestamps
        stream=sys.stdout,
    )
```
Log to stdout only. journald stores it. **Never write log files** (SD card wear). Use logger names under `calpi.` (for example `calpi.app`, `calpi.sync`).

### Step 5 — `calpi/tasks.py` (imports GLib only)

This is the most important helper in the project. Everything that runs work off the main thread uses it.

```python
"""Main-loop discipline helpers. See the gtk-kiosk-app skill: never touch widgets off the main thread."""
from __future__ import annotations
import functools, logging, threading
from typing import Any, Callable
from gi.repository import GLib

log = logging.getLogger("calpi.tasks")

def safe_callback(fn=None, *, repeat: bool | None = None):
    """Wrap a GLib timeout/idle callback so an exception is logged and doesn't kill the source.

    repeat=None  -> return whatever fn returns (fn must return SOURCE_CONTINUE/REMOVE); on exception keep going
                     if the function declared repeat=True, else remove.
    Usage: GLib.timeout_add_seconds(60, safe_callback(self._tick, repeat=True))
    """
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                result = f(*args, **kwargs)
            except Exception:
                log.exception("callback %s failed", getattr(f, "__qualname__", f))
                return GLib.SOURCE_CONTINUE if repeat else GLib.SOURCE_REMOVE
            if repeat is None:
                return result if result is not None else GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE if repeat else GLib.SOURCE_REMOVE
        return wrapper
    return deco(fn) if fn is not None else deco

def call_on_main(fn: Callable[..., Any], *args) -> None:
    """Schedule fn(*args) on the main loop once. Safe from any thread."""
    GLib.idle_add(safe_callback(lambda: fn(*args), repeat=False))

def run_in_thread(work: Callable[[], Any], *,
                  on_done: Callable[[Any], None] | None = None,
                  on_error: Callable[[BaseException], None] | None = None,
                  name: str = "calpi-worker") -> threading.Thread:
    """Run blocking `work()` in a daemon thread; deliver the result or exception on the main thread."""
    def runner():
        try:
            result = work()
        except BaseException as e:  # noqa: BLE001 — must reach on_error
            log.warning("worker %s failed: %s", name, e, exc_info=True)
            if on_error:
                call_on_main(on_error, e)
            return
        if on_done:
            call_on_main(on_done, result)
    t = threading.Thread(target=runner, name=name, daemon=True)
    t.start()
    return t
```

Rules to write in the module docstring:
- `work` **must not** touch any widget, or any GObject owned by the UI.
- `on_done` and `on_error` run on the main thread and may touch widgets.
- If the screen that asked for the work has been closed by the time the result arrives, `on_done` must cope with that. (Check a "still showing" flag. Don't rely on the widget being alive.)

### Step 6 — `calpi/widgets/util.py`

```python
from gi.repository import Gtk

def set_text_if_changed(label: Gtk.Label, text: str) -> None:
    if label.get_text() != text:
        label.set_text(text)

def set_visible_if_changed(widget: Gtk.Widget, visible: bool) -> None:
    if widget.get_visible() != visible:
        widget.set_visible(visible)

def set_class(widget: Gtk.Widget, css_class: str, on: bool) -> None:
    if on and not widget.has_css_class(css_class):
        widget.add_css_class(css_class)
    elif not on and widget.has_css_class(css_class):
        widget.remove_css_class(css_class)

def add_style_provider(provider, priority) -> None:
    """Version-tolerant wrapper for adding a display-wide CSS provider."""
    from gi.repository import Gdk
    display = Gdk.Display.get_default()
    fn = getattr(Gtk, "style_context_add_provider_for_display", None)
    if fn is not None:
        fn(display, provider, priority)
    else:
        Gtk.StyleContext.add_provider_for_display(display, provider, priority)
```
Check whether `Gtk.style_context_add_provider_for_display` actually exists in PyGObject on the Pi's GTK version. If it doesn't, the fallback is used, which is fine.

### Step 7 — `calpi/style.css`

```css
/* calpi stylesheet — the only place colours and fonts live. GTK 4.8-compatible (no var()). */
@define-color bg        #101418;
@define-color surface   #182028;
@define-color text      #e8e8e8;
@define-color text_dim  #9aa4ae;
@define-color text_faint #5c6670;
@define-color accent    #4f9dff;
@define-color danger    #ff6b6b;

window, .screen { background-color: @bg; color: @text; font-family: "DejaVu Sans"; }
.placeholder-title { font-size: 96px; font-weight: 300; }
.placeholder-sub   { font-size: 36px; color: @text_dim; }
```
**No `transition` or `animation` properties anywhere.** Put that rule in a comment at the top.

### Step 8 — `calpi/app.py`

```python
from __future__ import annotations
import argparse, datetime as dt, logging
from gi.repository import Gdk, GLib, Gtk

from calpi import paths, __version__
from calpi.tasks import safe_callback
from calpi.widgets.util import add_style_provider, set_text_if_changed

log = logging.getLogger("calpi.app")

class Navigator:
    """Switches screens in the root Gtk.Stack and calls on_show/on_hide hooks."""
    def __init__(self, stack: Gtk.Stack):
        self._stack = stack
        self._screens: dict[str, Gtk.Widget] = {}
        self._history: list[str] = []

    def add(self, name: str, widget: Gtk.Widget) -> None:
        self._screens[name] = widget
        self._stack.add_named(widget, name)

    def get(self, name: str) -> Gtk.Widget | None:
        return self._screens.get(name)

    @property
    def current(self) -> str | None:
        return self._stack.get_visible_child_name()

    def show(self, name: str, **params) -> None:
        cur = self.current
        if cur == name and not params:
            return
        if cur is not None:
            old = self._screens[cur]
            if hasattr(old, "on_hide"):
                old.on_hide()
            if cur != name:
                self._history.append(cur)
                del self._history[:-10]           # bounded: long uptime (US-37)
        self._stack.set_visible_child_name(name)
        new = self._screens[name]
        if hasattr(new, "on_show"):
            new.on_show(**params)
        log.info("screen=%s", name)

    def back(self, default: str = "calendar") -> None:
        target = self._history.pop() if self._history else default
        self.show(target)

    def reset(self, name: str = "calendar") -> None:
        self._history.clear()
        self.show(name)


class PlaceholderScreen(Gtk.Box):
    """Temporary first screen; US-06 replaces it with MonthView."""
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                         spacing=12, css_classes=["screen"])
        self.title = Gtk.Label(label="calpi", css_classes=["placeholder-title"])
        self.clock = Gtk.Label(css_classes=["placeholder-sub"])
        self.append(self.title); self.append(self.clock)
        self._tick()
        self._schedule_next_minute()

    def _schedule_next_minute(self):
        now = dt.datetime.now()
        delay_ms = (60 - now.second) * 1000 - now.microsecond // 1000 + 50
        GLib.timeout_add(delay_ms, self._on_minute)

    @safe_callback(repeat=False)
    def _on_minute(self):
        try:
            self._tick()
        finally:
            self._schedule_next_minute()     # always reschedule, even if _tick failed

    def _tick(self):
        set_text_if_changed(self.clock, dt.datetime.now().strftime("%A %d %B · %H:%M"))


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "CalpiApp", windowed: bool):
        super().__init__(application=app, title="calpi")
        self.set_cursor(Gdk.Cursor.new_from_name("none", None))   # US-11 refines this
        self.overlay = Gtk.Overlay()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, hexpand=True, vexpand=True)
        self.overlay.set_child(self.stack)
        self.set_child(self.overlay)
        self.navigator = Navigator(self.stack)
        self.navigator.add("calendar", PlaceholderScreen())
        self.navigator.show("calendar")
        if windowed:
            self.set_default_size(1920, 1080)
            self._install_dev_shortcuts()
        else:
            self.fullscreen()

    def _install_dev_shortcuts(self):
        ctl = Gtk.ShortcutController()
        ctl.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>q"),
            Gtk.CallbackAction.new(lambda *a: (self.get_application().quit(), True)[1])))
        self.add_controller(ctl)


class CalpiApp(Gtk.Application):
    def __init__(self, args: argparse.Namespace):
        super().__init__(application_id="dev.calpi.Kiosk")
        self.args = args
        self.window: MainWindow | None = None
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app):
        if self.window is not None:          # activate can fire twice; keep one window
            self.window.present(); return
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(paths.app_dir() / "style.css"))
        add_style_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = MainWindow(self, self.args.windowed)
        self.window.present()
        log.info("calpi ready version=%s state_dir=%s renderer=%s",
                 __version__, paths.state_dir(), __import__("os").environ.get("GSK_RENDERER"))
        if self.args.exit_after:
            GLib.timeout_add_seconds(self.args.exit_after, self._exit_for_test)

    @safe_callback(repeat=False)
    def _exit_for_test(self):
        log.info("exit-after: screen=%s", self.window.navigator.current)
        self.quit()


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="calpi")
    p.add_argument("--windowed", action="store_true", help="don't go fullscreen (dev)")
    p.add_argument("--state-dir", help="override the state directory (dev/tests)")
    p.add_argument("--exit-after", type=int, default=0, metavar="SECONDS",
                   help="log state and quit after N seconds (smoke tests)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    from calpi.logging_setup import setup_logging
    setup_logging()
    args = parse_args(argv)
    paths.set_state_dir_override(args.state_dir)
    app = CalpiApp(args)
    return app.run([])       # don't pass our argv to GTK
```

Notes:
- `app.run([])`: **don't pass `sys.argv`** to GTK. It would try to parse our flags.
- The `activate` guard stops a second window being created if activate fires twice.
- `Gtk.CallbackAction`'s callback signature varies between versions. If the lambda fails, write a small function `def _quit(widget, args, *rest): ...; return True`.
- Log `calpi ready` exactly once. The smoke test looks for it.

### Step 9 — `run.py` and `calpi/__init__.py`

```python
#!/usr/bin/env python3
"""calpi entry point. GSK_RENDERER must be set before Gtk is imported (Pi 3B: GLES 2.0 only)."""
import os, sys
os.environ.setdefault("GSK_RENDERER", "cairo")
os.environ.setdefault("GTK_A11Y", "none")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from calpi.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
```
`calpi/__init__.py`: `__version__ = "0.1.0"`. **Don't import gi there**: the sync process imports `calpi.*` too.

The `gi.require_version` calls must happen before *any* `from gi.repository import Gtk`, including the ones inside `calpi.tasks`. That's why `run.py` does it first. Tests that import `calpi.tasks` need GLib only; `from gi.repository import GLib` doesn't need a display and doesn't hang.

### Step 10 — Dev scripts

`scripts/dev-run.sh`:
```bash
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
```

`scripts/smoke.sh`:
```bash
#!/usr/bin/env bash
# Headless smoke test: start, wait, check log markers, quit. Exit 0 = pass.
set -euo pipefail
cd "$(dirname "$0")/.."
DISPLAY_NUM="${BROADWAY_DISPLAY:-:6}"     # separate display from dev-run
pgrep -f "gtk4-broadwayd $DISPLAY_NUM" >/dev/null || { setsid nohup gtk4-broadwayd "$DISPLAY_NUM" >/dev/null 2>&1 </dev/null & sleep 1; }
STATE="$(mktemp -d)"
LOG="$(mktemp)"
trap 'rm -rf "$STATE" "$LOG"' EXIT
GDK_BACKEND=broadway BROADWAY_DISPLAY="$DISPLAY_NUM" \
  timeout 20 /usr/bin/python3 run.py --windowed --state-dir "$STATE" --exit-after "${SMOKE_SECONDS:-3}" "$@" >"$LOG" 2>&1 || { cat "$LOG"; echo "SMOKE FAIL: exit $?"; exit 1; }
grep -q "calpi ready" "$LOG"   || { cat "$LOG"; echo "SMOKE FAIL: no ready line"; exit 1; }
grep -q "screen=calendar" "$LOG" || { cat "$LOG"; echo "SMOKE FAIL: calendar screen not shown"; exit 1; }
if grep -E "Traceback|CRITICAL|ERROR" "$LOG"; then echo "SMOKE FAIL: errors in log"; exit 1; fi
echo "SMOKE OK"
```
Later stories extend `smoke.sh` with more `grep` checks, or with their own `SMOKE_*` flags. Keep it simple and readable.

Add `.devstate/` and `scratch-*` to a `.gitignore` (create one; the project isn't a git repo yet, but it will be).

### Step 11 — Tests

`tests/test_paths.py` (no display):
- With the override set, `STATE_DIRECTORY` set, and `CALPI_STATE_DIR` set, the override wins.
- With only `STATE_DIRECTORY` (including the `a:b` colon form), the first path is used.
- The directory is created with mode `0700` (`stat.S_IMODE(os.stat(p).st_mode) == 0o700`).
- `monkeypatch` the environment, and use `tmp_path`. Reset the override in a fixture.

`tests/test_tasks.py` (GLib only, no display needed):
- Run a `GLib.MainLoop` in the test: `run_in_thread(lambda: 42, on_done=...)`. Check that the callback runs on the main thread (`threading.current_thread() is threading.main_thread()`) and gets 42. Quit the loop from the callback, and add a 2-second `GLib.timeout_add` safety quit so the test can't hang.
- `run_in_thread` where the work raises → `on_error` gets the exception on the main thread.
- A `safe_callback(repeat=True)` function that raises on its first call and counts its calls: attach it with `GLib.timeout_add(10, ...)` and check it gets called again (≥ 3 calls within 200 ms).
- Check that `from gi.repository import GLib` doesn't need a display. It doesn't hang, because only Gtk initialises the display.

`tests/test_app_smoke.py`: mark it `@pytest.mark.gtk`, and have it run `scripts/smoke.sh` with `subprocess.run` and check the return code. Skip it unless `CALPI_GTK_TESTS=1`. Add to `tests/conftest.py`:
```python
import os, pytest
def pytest_collection_modifyitems(config, items):
    if os.environ.get("CALPI_GTK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set CALPI_GTK_TESTS=1 to run GTK/Broadway tests")
    for item in items:
        if "gtk" in item.keywords:
            item.add_marker(skip)
```

### Step 12 — Check on the Pi (if US-01 is already done)

```bash
rsync -a --exclude .git --exclude .claude --exclude .devcontainer --exclude tests ./ calpi:/tmp/calpi-test/
ssh calpi 'sudo rsync -a --delete /tmp/calpi-test/ /opt/calpi/ && sudo systemctl restart calpi-kiosk && sleep 6 && journalctl -u calpi-kiosk -n 20 --no-pager'
```
Look for `calpi ready ... renderer=cairo state_dir=/var/lib/calpi`. Take a screenshot as described in the `pi-deploy` skill. If US-01 isn't done, leave this check for US-03.

---

## Files

| File | New/Changed |
|---|---|
| `run.py` | New |
| `pyproject.toml` | New |
| `.gitignore` | New (`.devstate/`, `scratch-*`, `__pycache__/`, `.pytest_cache/`) |
| `deps/apt-runtime.txt`, `deps/apt-dev.txt` | New |
| `.devcontainer/devcontainer.json` | `postCreateCommand`, `forwardPorts` |
| `calpi/__init__.py`, `app.py`, `paths.py`, `logging_setup.py`, `tasks.py`, `style.css` | New |
| `calpi/widgets/__init__.py`, `calpi/widgets/util.py` | New |
| `calpi/data/__init__.py` | New (empty; the package is used from US-04 onwards) |
| `scripts/dev-run.sh`, `scripts/smoke.sh` | New (`chmod +x`) |
| `tests/conftest.py`, `tests/test_paths.py`, `tests/test_tasks.py`, `tests/test_app_smoke.py` | New |

---

## Testing summary

| Level | Command | Expected |
|---|---|---|
| Unit | `/usr/bin/python3 -m pytest` | all pass, GTK test skipped |
| Smoke | `scripts/smoke.sh` | `SMOKE OK` |
| GTK tests | `CALPI_GTK_TESTS=1 /usr/bin/python3 -m pytest` | all pass |
| Visual (dev) | `scripts/dev-run.sh`, open :8085 | placeholder with clock |
| Pi | deploy (by hand or US-03), `journalctl`, `grim` screenshot | fullscreen, `renderer=cairo`, no cursor |

---

## Pitfalls

- **Importing Gtk at module level in anything under `calpi.data` or `calpi.sync`.** That breaks the sync process, and makes unit tests hang with no display.
- **Passing `sys.argv` to `app.run()`.**
- **Calling `GLib.timeout_add` with a lambda that returns `None`.** `None` is treated as `SOURCE_REMOVE`, so the timer silently stops after one run. Always use `safe_callback(repeat=...)`, or return the constant explicitly.
- **A widget touched in a worker.** It sometimes works in Broadway and then crashes randomly on the Pi. Always use `run_in_thread(..., on_done=...)`.
- **Using `time.sleep` on the main thread.** Never do it.
- **Unbounded history in `Navigator`.** Keep it capped (the device runs for weeks).
- **`set_default_size` in fullscreen mode.** Don't. cage gives the window its size.

---

## Definition of done

- [ ] All acceptance criteria met. Smoke test and unit tests pass.
- [ ] Code follows the `gtk-kiosk-app` skill (renderer, cursor, animations, CSS, main-loop rules).
- [ ] No `gi` imports in `paths.py`, `logging_setup.py`, or `calpi/data/`.
- [ ] Checked on the Pi, or explicitly handed to US-03 in the notes.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `window.navigator.add(name, widget)`, `.show(name, **params)`, `.back()`, `.reset()`, `.current`; screens' optional `on_show(**params)` / `on_hide()` | US-06, US-08, US-09, US-22, US-32, US-39, US-40 |
| `window.overlay` (a `Gtk.Overlay`) for top-level layers | US-21, US-22, US-29, US-30, US-38 |
| `calpi.tasks.run_in_thread`, `safe_callback`, `call_on_main` | every story with background work |
| `calpi.paths.state_dir()`, `runtime_dir()`, `asset()` | US-04, US-05, US-12, US-13, US-33, US-41 |
| `calpi.widgets.util.set_text_if_changed`, `set_visible_if_changed`, `set_class`, `add_style_provider` | all UI stories |
| `--windowed`, `--state-dir`, `--exit-after`; `calpi ready` and `screen=<name>` log lines | smoke tests in later stories |
| `scripts/smoke.sh`, `scripts/dev-run.sh` | all UI stories |
| `deps/apt-runtime.txt` is the list of runtime apt packages | US-03 (`scripts/pi deps`), US-13, US-15, … |
| The stylesheet is `calpi/style.css`, with colours from `@define-color` | all UI stories |
