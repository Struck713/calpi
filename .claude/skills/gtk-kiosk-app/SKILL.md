---
name: gtk-kiosk-app
description: Conventions for writing the calpi fullscreen kiosk UI in Python + GTK (PyGObject) so it runs smoothly on a Raspberry Pi 3B at 1920x1080 under the cage compositor. Use when writing or changing any UI code, layout, CSS, timers, data fetching, images, fonts, or when diagnosing slowness, memory growth, or a stale/frozen screen. Also covers running the app locally in the devcontainer without a display.
---

# GTK kiosk app (Python + PyGObject)

Starting point: [example_app.py](example_app.py) is a minimal, correct kiosk app. It covers fullscreen, a hidden cursor, CSS, a minute-aligned clock, and a background fetch that marshals results back to the UI thread. Copy its structure.

## GTK version and renderer (Pi 3B specific)

- Target **GTK 4** (`gi.require_version("Gtk", "4.0")`, package `gir1.2-gtk-4.0`).
- The Pi 3B GPU (VideoCore IV) only supports **GLES 2.0**. Recent GTK 4 GPU renderers (`ngl`, `vulkan`) require GLES 3.0+. On this hardware GTK will either fail to create a GL context or fall back. **Always force the software renderer**: `GSK_RENDERER=cairo`. The systemd unit sets this. Set it in the app as well, before importing Gtk, so dev runs match.
- Cairo software rendering at 1080p is fine for a mostly static dashboard. It is too slow for continuous full-screen animation. **Design for that**: see "Performance" below.
- To check which renderer is in use: run with `GSK_DEBUG=renderer` and read the journal.
- Fallback: if GTK 4 turns out too heavy on the device, GTK 3 (`gir1.2-gtk-3.0`) uses less memory and has the same threading and timer model. Only the widget API differs. Don't mix the two.

## Dependencies

- On the Pi, install PyGObject from **apt** (`python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`). Never `pip install PyGObject` on the Pi: it compiles from source and needs dev headers.
- If you need extra pure-Python packages, use a venv created with `python3 -m venv --system-site-packages .venv` so `gi` stays visible. Prefer the stdlib (`urllib.request`, `json`, `zoneinfo`, `sqlite3`) to keep the deployment trivial.
- Target the Python shipped with Pi OS (3.11+ on current releases). Don't use newer syntax than that.

## App structure rules

1. **`Gtk.Application` + one `Gtk.ApplicationWindow`**, `window.fullscreen()`. Don't use `set_default_size` hacks. The window gets the output size from cage.
2. **Design for exactly 1920x1080.** A fixed layout is fine; this isn't a responsive app. Use `Gtk.Box`/`Gtk.Grid` with `hexpand`/`vexpand`. Use pixel sizes in CSS.
3. **Hide the cursor**: `window.set_cursor(Gdk.Cursor.new_from_name("none", None))`.
4. **Disable animations**: `Gtk.Settings.get_default().set_property("gtk-enable-animations", False)`. Don't use CSS `transition`/`animation` or `Gtk.Spinner`/`Gtk.Revealer` transitions.
5. **Style with one CSS file** loaded through `Gtk.CssProvider` at `STYLE_PROVIDER_PRIORITY_APPLICATION`. Keep colours and fonts there, not in code. Dark backgrounds reduce burn-in and glare.
6. A `--windowed` CLI flag skips fullscreen (and a `--scale` flag is optional) for development.

## Main-loop discipline (most important)

GTK is single-threaded. **Anything that blocks the main loop freezes the screen**, and with no mouse or keyboard nobody notices until the data is stale.

- Periodic work: `GLib.timeout_add_seconds(n, cb)` (coarse, CPU-friendly). Use `timeout_add` (ms) only if you need sub-second timing. The callback returns `GLib.SOURCE_CONTINUE` to repeat.
- Clock: align to the next minute boundary (see `example_app.py`). Don't tick every second unless seconds are displayed.
- Network, disk, or anything slow runs in a **worker thread** (`threading.Thread(daemon=True)`, or one `concurrent.futures.ThreadPoolExecutor`). Hand results back with `GLib.idle_add(fn, result)`. **Never touch a widget from a worker thread.**
- Every timer and idle callback catches its own exceptions and logs them. An uncaught exception inside a GLib callback is printed but the source may be removed, so updates silently stop.
- Network calls always use timeouts (`urlopen(url, timeout=10)`). On failure, keep showing the last good data and show a subtle "last updated HH:MM" / stale indicator. Don't blank the screen.

## Performance on the Pi 3B

- Update only the widgets whose value changed. Compare before `label.set_text()`: setting identical text still queues a redraw.
- Build the widget tree once and mutate it afterwards. Don't destroy and recreate large subtrees every refresh.
- Images: pre-scale to the exact display size **once** (`GdkPixbuf.Pixbuf.new_from_file_at_scale`, or Pillow at build time) and show them with `Gtk.Picture` + `Gdk.Texture.new_for_pixbuf`. Never let GTK scale a large photo on every frame. Prefer PNG/JPEG at display size. Avoid SVG with heavy filters.
- Custom drawing: `Gtk.DrawingArea.set_draw_func` with cairo. Redraw it only when its data changes (`queue_draw()`), not on a timer.
- Avoid huge `Gtk.ListView`/`ScrolledWindow` content and anything that scrolls or animates continuously (tickers, marquees). If you must have one, update at ≤ 10 fps and keep it small.
- Fonts: install them system-wide (`/usr/local/share/fonts`, then `fc-cache -f`) and name them in CSS. Missing fonts cause slow fallback lookups and odd glyphs. `fonts-dejavu-core` is the safe default.
- Memory budget: keep app RSS well under ~250 MB. Check with `ps -o rss,cmd -C python3` on the Pi. Growth over hours usually means reference cycles in callbacks or textures that are never released.

## Robustness

- Let crashes crash. systemd restarts cage and the app (`Restart=always`). Don't wrap `main()` in a retry loop.
- Log with `logging` to stdout. systemd sends it to the journal (`journalctl -u calpi-kiosk`). Don't write log files (SD card wear).
- Config (URLs, calendar IDs, timezone, API keys) goes in `/etc/calpi/config.toml` or env vars, read with `tomllib`. Never hardcode secrets or commit them.
- Handle clock jumps at boot (NTP sync after start): compute "now" on every tick instead of accumulating intervals.

## Running during development

The devcontainer has no display. Use GTK's **Broadway** backend, which renders into a browser tab:

```bash
sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 libgtk-4-bin   # once; provides gtk4-broadwayd
gtk4-broadwayd :5 &                        # listens on http://localhost:8085
GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 /usr/bin/python3 run.py --windowed
```
Forward port 8085 and open it in a browser. Use the system `/usr/bin/python3`, because the devcontainer's default `python3` may be a separate build that can't see apt's `gi`. Broadway is for layout and logic checks only. Measure performance **on the Pi**. For real screenshots from the device, see the `pi-deploy` skill.

Gotchas (verified):
- With GTK 4, `from gi.repository import Gtk` calls `Gtk.init_check()` at import time. With no display it **hangs instead of failing**. Always start broadwayd and set `GDK_BACKEND=broadway` first, and wrap automated runs in `timeout`.
- Start broadwayd detached (`setsid nohup gtk4-broadwayd :5 >/dev/null 2>&1 < /dev/null &`), or it keeps the shell's pipe open and the command never returns.
- For automated checks without a browser, schedule a `GLib.timeout_add_seconds` callback that prints label text / state and calls `app.quit()`.

Keep non-UI logic (data fetching, parsing, formatting) in plain modules with no `gi` imports, so it can be unit-tested with `pytest` anywhere.

## Suggested layout

```
run.py                 # entry point: sets GSK_RENDERER, calls calpi.app.main()
calpi/
  app.py               # Gtk.Application, window, CSS loading
  widgets/             # one module per panel (clock, calendar, weather...)
  data/                # fetchers + parsers, no gi imports, unit-tested
  style.css
tests/
```
