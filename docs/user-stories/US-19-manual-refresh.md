# US-19 — Manual refresh

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P1 |
| **Blocked by** | US-16 Scheduled background sync |
| **Blocks** | — |
| **Phase** | 2. Syncing (P1) |

## Story

> As a user, I want to trigger a sync right away instead of waiting for the next scheduled one.

## Context

Someone adds an event on their phone and wants to see it on the wall **now**, not in 15 minutes. This story adds a **refresh control** to the calendar header (next to the sync indicator from US-16/17), and a "Sync now" button that Settings (US-27) will reuse.

The engine already supports it: `app.sync.request_sync(reason="manual")` runs at once or queues behind a running sync (US-16), and bypasses the backoff (US-17 D6). The work here is **UI and feedback**. The press must feel instant (with no spinner animation on the Pi: US-02 D6), repeated presses must not stack up syncs, and the result must be clear ("Updated just now", or a short failure note).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-16** Scheduled background sync | `app.sync.request_sync(reason)`, `state_callbacks(running)`, `result_callbacks`, `last_success_wall`, `SyncIndicator` in `header.end_slot` | `grep -n "def request_sync\|state_callbacks" calpi/sync_engine.py`. On the Pi, the header shows "Updated HH:MM". |

### Soft dependencies
- **US-17**: `retry.classify(result)` and the indicator states. A manual refresh that fails because the device is offline should say so briefly (acceptance criterion 5). If US-17 isn't done, use `result["accounts"][*]["error"]` directly.
- **US-11**: target sizes and keyboard conventions (`on_key`). F5 / `Ctrl+R` go through `MonthView.on_key`.
- **US-22**: a toast/overlay helper (`overlays.py`) would be nice for the result message. If it doesn't exist, show the message in the sync indicator label itself for 5 s (D3).
- **US-38**: will replace the short failure text with the full plain-language message and fix. Keep the text in one function, so US-38 can swap it out.

### External blockers
None beyond US-16's.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The press seems to do nothing, because the sync finishes in 1 s and the label flips back | That's fine, but make sure "Updating…" is visible for at least 1 s (D4), so the user sees that something happened. |
| No refresh icon available | Use the text glyph `⟳` (U+27F3) or `↻` (U+21BB) in DejaVu Sans. Check it renders on the Pi (take a screenshot). Fall back to the word "Refresh". |

---

## Scope

### In scope
- A refresh button in the calendar header (`header.end_slot`, right after the `SyncIndicator`).
- The keyboard shortcuts F5 and `Ctrl+R` on the calendar and day screens.
- Button states: idle, running (insensitive, label "Updating…"), done (a short result text for 5 s).
- Debounce: presses while a sync is running are ignored (the button is insensitive anyway), and presses within 5 s of a **successful** manual sync are ignored.
- A reusable `RefreshButton` widget for US-27's Settings section.
- Result feedback text (a short success or failure summary).

### Out of scope
- Detailed error messages and fixes (US-38).
- Pull-to-refresh gestures (not planned).
- Refreshing one calendar at a time.

---

## Acceptance criteria

1. The calendar header shows a refresh button (at least 72 × 72 px, glyph `↻` or the word "Refresh") next to the sync status text.
2. Pressing it calls `app.sync.request_sync(reason="manual", force=False)` **straight away** (a normal sync using ctags: fast, but it picks up any change).
3. While any sync is running (manual or scheduled), the button is **insensitive** and the status text reads "Updating…". It shows "Updating…" for **at least 1 s** even if the sync ends sooner.
4. On success, the status text shows "Updated just now" for 5 s, then the usual "Updated HH:MM" text.
5. On failure, the status text shows a **short** reason for 10 s: "Couldn't update: offline", "Couldn't update: sign-in problem", "Couldn't update: iCloud not responding", or "Couldn't update". Then it goes back to the normal indicator state (US-17). The mapping lives in one function, `manual_result_text(result) -> str`, which US-38 will replace.
6. F5 and `Ctrl+R` do the same as pressing the button, on the `calendar` and `day` screens.
7. Pressing it again within 5 s of a completed successful manual sync does nothing (and logs `sync: manual refresh ignored (just synced)` at DEBUG).
8. A manual press during a backoff period (US-17) syncs **immediately**. It doesn't wait for the retry timer.
9. In safe mode (US-12), the button still works (US-16 acceptance criterion 10).
10. `RefreshButton` is a separate widget class, usable elsewhere (US-27), that follows the same engine state.

---

## Design decisions (already made)

- **D1. `RefreshButton(Gtk.Button)`** subscribes to `app.sync.state_callbacks` and `result_callbacks` itself, and **unsubscribes in `do_unroot`** (or when its screen is destroyed), so instances created for Settings don't leak callbacks. (The callback lists from US-16 are plain lists: add `remove` helpers, or make them small `CallbackList` objects with `add(cb) -> handle`, `remove(handle)`. **Do that refactor here if it isn't done yet**, and keep the other users working.)
- **D2. No `force=True`** for the manual refresh: ctag checks already catch every server-side change. Force only makes it slower. (A developer "force" mode is available through the CLI.)
- **D3. Result feedback goes in the sync indicator label** (a temporary override with an expiry time), **not** in a separate popup. The indicator gets `show_transient(text, css_state, seconds)`. When US-22's toast helper exists, US-38 may switch to toasts. Keep the transient text logic in one place.
- **D4. The minimum "Updating…" time**: the engine reports the running state immediately. The indicator records the start time, and on finish, if less than 1 s has passed, delays the switch with a one-shot `GLib.timeout_add`.
- **D5. Tracking whether the result was from our press**: the engine includes `reason` in the result. A result whose reason contains `manual` (including merged `coalesced:...manual...`) counts as the manual result for feedback.

---

## Implementation plan

### Step 1 — Small engine additions
- `app.sync.is_running` (a property).
- If they're plain lists, turn `state_callbacks` and `result_callbacks` into `CallbackList` objects with `add`/`remove` (D1). Put `CallbackList` in `calpi/tasks.py` (no widget code). Update US-16, US-17, and US-18 subscribers.
- Make sure `Request.merge` keeps `manual` visible in the merged `reason` (D5). Test it.

### Step 2 — `calpi/widgets/refresh_button.py`
```python
class RefreshButton(Gtk.Button):
    COOLDOWN_S = 5
    def __init__(self, app, label="↻"):
        super().__init__(label=label, css_classes=["nav-button", "refresh-button"])
        self.app = app
        self._last_manual_ok_mono = 0.0
        self._h_state = app.sync.state_callbacks.add(self._on_state)
        self._h_result = app.sync.result_callbacks.add(self._on_result)
        self.connect("clicked", self._on_clicked)
        self._on_state(app.sync.is_running)

    def _on_clicked(self, *_):
        if self.app.sync.is_running: return
        if time.monotonic() - self._last_manual_ok_mono < self.COOLDOWN_S:
            log.debug("sync: manual refresh ignored (just synced)"); return
        self.app.sync.request_sync(reason="manual")

    def _on_state(self, running: bool):
        if self.get_sensitive() == running:          # insensitive while running
            self.set_sensitive(not running)

    def _on_result(self, r: dict):
        if "manual" in (r.get("reason") or "") and retry.classify(r) == "success":
            self._last_manual_ok_mono = time.monotonic()

    def do_unroot(self):
        self.app.sync.state_callbacks.remove(self._h_state)
        self.app.sync.result_callbacks.remove(self._h_result)
        Gtk.Button.do_unroot(self)
```
**Check** that `do_unroot` works as a virtual method override in PyGObject for GTK 4 on the Pi's version. If it doesn't, connect to the `unrealize` signal, or give the owning screen an explicit `dispose()`. For the header button, which lives for the whole app, this doesn't matter. For Settings (US-27) it does.

### Step 3 — The indicator's transient text (`sync_indicator.py`)
```python
def show_transient(self, text: str, state: str, seconds: int) -> None:
    self._transient = (text, state, time.monotonic() + seconds)
    self._apply()
    GLib.timeout_add_seconds(seconds, self._expire_transient)
```
`_apply()` uses the transient override while it hasn't expired, otherwise `compute_state(...)` (US-17). Also the minimum-running time (D4).

On a result with `manual` in its reason:
```python
text = manual_result_text(r)          # in calpi/data/sync_text.py (no gi), tested
if retry.classify(r) == "success": self.show_transient("Updated just now", "ok", 5)
else:                              self.show_transient(text, "error", 10)
```
`manual_result_text`: all accounts `NETWORKISH` → "Couldn't update: offline". Any `AUTH_FAILED` or `CREDENTIALS_UNREADABLE` → "Couldn't update: sign-in problem". `SERVER_ERROR`/`RATE_LIMITED`/`TIMEOUT` → "Couldn't update: iCloud not responding" (name the provider from the account, for US-20). Otherwise "Couldn't update".

### Step 4 — Place it and add the keys
`MainWindow`: `self.refresh_button = RefreshButton(app)` → `month_view.header.end_slot`, right after the indicator. In `MonthView.on_key` and `DayDetail.on_key` (US-11 `KeyRouter`): `F5`, or `r` with `Gdk.ModifierType.CONTROL_MASK` → `self.app.window.refresh_button.emit("clicked")` (or call a shared `trigger_manual_refresh()` on the app, which is cleaner. **Use `app.trigger_manual_refresh()`**, and have the button call it too, so the cooldown logic lives in one place. Move `_last_manual_ok_mono` to the app, or keep it on the engine.)

CSS:
```css
.refresh-button { font-size: 36px; min-width: 72px; }
.sync-status.error { color: @danger; }
```

### Step 5 — Tests
- `tests/test_sync_text.py`: `manual_result_text` for each case, including mixed results.
- The engine: merging keeps `manual` in the reason. A manual request during a backoff runs at once (fake spawner).
- `CallbackList`: add, remove, call; a removed callback isn't called; an exception in one doesn't stop the others.
- Manual Broadway check: click → "Updating…" (≥ 1 s) → "Updated just now" → after 5 s "Updated HH:MM". Click twice quickly → one sync (the log shows one `sync: manual`).

### Step 6 — Pi check
Deploy. Add an event on the owner's phone (or ask the owner to), press refresh with the mouse → the event appears within a few seconds. Take a screenshot during "Updating…" if you can (use a test hook that delays the worker, `CALPI_TEST_SYNC_DELAY=5`, in a **temporary** drop-in. Remove it afterwards). With the network off (US-17 step 7 method), press refresh → "Couldn't update: offline".

---

## Files

| File | Change |
|---|---|
| `calpi/widgets/refresh_button.py` | New |
| `calpi/widgets/sync_indicator.py` | `show_transient`, the minimum running time |
| `calpi/data/sync_text.py` | `manual_result_text` |
| `calpi/tasks.py` | `CallbackList` |
| `calpi/sync_engine.py` | `is_running`, `CallbackList`s, reason merging |
| `calpi/app.py` | `trigger_manual_refresh()`, places the button |
| `calpi/widgets/month_view.py`, `day_detail.py` | F5 / Ctrl+R in `on_key` |
| `calpi/style.css` | Button and error state |

---

## Pitfalls

- **Stacking syncs** with repeated presses. The engine coalesces, but also disable the button while running.
- **Forcing the sync.** It's slower, and there's no benefit (D2).
- **A spinner animation.** Not on the Pi. Use text.
- **Leaking callbacks** from `RefreshButton` instances in Settings (D1).
- **Hard-coding "iCloud"** in messages. Name the account's provider.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Phone change → manual refresh → visible, checked on the Pi.
- [ ] Offline manual refresh shows the offline message.
- [ ] Test drop-ins removed.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `RefreshButton(app, label=...)` | US-27 (Settings → "Sync now"), US-31 (Status screen) |
| `app.trigger_manual_refresh()` | US-27, US-31, US-35 (a gesture could call it) |
| `SyncIndicator.show_transient(text, state, seconds)` | US-38 |
| `sync_text.manual_result_text(result)`: to be replaced by US-38's message catalogue | US-38 |
| `CallbackList` (`add` → handle, `remove`) | everyone subscribing to engine or app events |
