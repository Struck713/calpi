# Pi bring-up checklist

Everything that could NOT be verified in the devcontainer (no Pi, real accounts, touchscreen or owner was
available while the 41 stories were built). Ordered as a bring-up sequence. Each item names the story it belongs
to; record results in the doc named in brackets. Items marked **[OWNER OK]** change the device in a way that needs
the owner's approval first (reboot, power cut, boot trims, security scope, editing the owner's real accounts).

Everything below was checked in the devcontainer only: unit tests, Broadway GTK tests, `scripts/smoke.sh`.
Broadway is no evidence for timing, memory, colour, or input on the Pi.

## 0. Before touching the Pi

- Read `docs/platform-versions.md` and `.claude/skills/pi-kiosk-setup/SKILL.md`. Flash per "How this device was flashed".
- Have ready: Wi-Fi SSID/password/country, the owner's iCloud Apple ID plus a fresh app-specific password, the
  touchscreen, an official 5.1 V / 2.5 A supply, and the owner at the screen for the visual checks.

## 1. US-01 Provisioning (`setup-pi.sh`)

- [ ] Run `sudo WIFI_COUNTRY=<CC> bash /tmp/setup-pi.sh` on a fresh Raspberry Pi OS Lite 64-bit; it has never run on
      a real device. Check every step for errors; re-run it to confirm it is idempotent.
- [ ] Fill in `docs/platform-versions.md` (board, OS, kernel, systemd, Python, SQLite, GTK, cage, NM versions,
      `WAYLAND_DISPLAY` under the service, HDMI connector name, modes, Wi-Fi country, apt availability of cage,
      wlr-randr, wlopm, grim, ddcutil). If Python is not 3.11 or GTK not 4.8, review the code assumptions.
- [ ] `calpi-kiosk.service` starts on boot, is fullscreen, cairo renderer, no cursor, 1920x1080 screenshot.
- [ ] Offline boot time and online boot time (record in platform-versions.md).
- [ ] Screen blanking off, `/tmp` and journal are volatile, SD-wear settings are in effect.
- [ ] **[OWNER OK]** reboot tests and unplugging power (US-12 below).
- [ ] **[OWNER OK]** boot trims (apt-daily timers, man-db, ModemManager, bluetooth...) under a `LEAN=1` switch: NOT
      done and not implemented in setup-pi.sh. Only after `systemd-analyze blame` shows they matter (US-36).

## 2. US-03 Deploy workflow (`scripts/pi`)

- [ ] `~/.ssh/config` entry, then `scripts/pi deps`, `scripts/pi deploy`, `restart`, `logs`, `screenshot`, `health`,
      `ssh`. Only `bash -n` was run; never executed against a device.
- [ ] Deploy include list, `.pyc` compilation, build stamp (shown on About/Status), readiness wait and
      **rollback on failed deploy** (break the app deliberately once and confirm the rollback).
- [ ] `grim` screenshot works under cage as the kiosk user.

## 3. US-02 Skeleton, US-11 Input, US-12 Crash / power-loss recovery

- [ ] US-02: fullscreen, `renderer=cairo`, no cursor; startup log lines as in `scripts/smoke.sh`.
- [ ] US-11: cursor hides on touch and shows on mouse motion under cage; touch targets meet the size rules on the
      real screen (see also US-34).
- [ ] US-12: `WatchdogSec` actually restarts a frozen app (freeze it: `kill -STOP`, wait for the restart);
      crash loop leads to safe mode; SIGTERM shutdown is clean; faulthandler output lands in the journal.
- [ ] **[OWNER OK]** US-12: real power-cut test (pull the plug during a sync and during a settings save), 5+ times.
      After each: boots, DB integrity check passes or resets cleanly, `settings.json` intact, no lost accounts.
- [ ] US-12: corrupt-DB reset and credentials-unreadable notice on the real filesystem (on a COPY of state).

## 4. US-13 Credential storage

- [ ] Key derivation uses the Pi's hardware serial (`hardware_serial()` was only exercised with a fake): store and
      read back a test secret as the kiosk user with `STATE_DIRECTORY=/var/lib/calpi`. File modes 0600/0700.
- [ ] Re-flashing / moving the SD card to another Pi makes credentials unreadable by design: confirm the message.
- [ ] Owner greps the journal for the password (must find nothing).

## 5. US-04..US-10 Data, month grid, navigation, day detail, midnight

- [ ] Load sample data (`python3 -m calpi.data.sample_data --load`) and screenshot month grid, events, day detail.
      Check fonts, colours, lane layout on the real 1920x1080 screen (Broadway used different fonts).
- [ ] US-06/07/09: `month_render` and `day_open` timings (see US-36).
- [ ] US-08: idle-return timer, keyboard navigation with a real keyboard/mouse.
- [ ] US-10: fake-now drop-in across midnight (`CALPI_FAKE_NOW=...T23:59:00`), then REMOVE the drop-in and check
      `systemctl cat calpi-kiosk` has no `CALPI_FAKE_NOW`. Real midnight overnight: one `clock: day changed`.
      **[OWNER OK]** optional NTP jump test (`date -s '+2 hours'`; put the time back).

## 6. US-14 / US-15 / US-16 / US-17 / US-18 / US-19 iCloud, sync, offline, status, refresh (real account)

- [ ] US-14: real CalDAV discovery against iCloud with the owner's app-specific password (all tests use fixtures).
- [ ] US-15: fetch and parse the owner's real calendars: check odd events (recurrence, time zones, all-day) in the grid.
- [ ] US-16: scheduled sync runs as the worker process under the service (`STATE_DIRECTORY`, sandboxing/`ProtectSystem`
      may block writes: check the journal), header indicator, interval changes.
- [ ] US-17: pull the router/WAN and the Wi-Fi for a few hours: offline banner/indicator, backoff, recovery, clock
      trust before NTP (boot without network: dates must not be trusted until synced).
- [ ] US-18: `python3 -m calpi.sync.cli status` after 2-3 syncs and after a deliberate failure.
- [ ] US-19: add an event on the owner's phone, press refresh: appears within seconds; F5/Ctrl+R; cooldown behaviour.
- [ ] US-20: real ICS feed and, if the owner has one, a CalDAV provider (Fastmail/Nextcloud etc.) via UI and CLI.

## 7. US-21..US-27 Settings, keyboard, networking, accounts (owner interaction)

- [ ] US-21: on-screen keyboard: size, key hit rate with a finger, layouts, password field behaviour under cage.
- [ ] US-22: Settings open/close, sidebar, overlays on the real screen.
- [ ] US-23: scan, join a real WPA2 network (owner types the password), wrong-password error, hidden SSID, join while
      offline. Uses NetworkManager over D-Bus/nmcli: unverified against a real NM.
- [ ] Polkit rule check (see section "Security / owner approvals" below): every Wi-Fi action must still work as
      kiosk after the narrowing done in the cleanup commit.
- [ ] US-24: forget the non-active network; **only on Ethernet or with a scheduled restore** forget the active one;
      "No internet" with WAN unplugged.
- [ ] US-25: add the account through the UI (owner types Apple ID and app password), deselect a calendar, wrong
      password once (AUTH message), update password flow, remove account; grep logs for the password.
- [ ] US-26: rename/recolour/hide a calendar; overrides survive a forced sync.
- [ ] US-27: set 5 minutes and watch `sync:` log lines; "Next update" counts down; "Sync now" row (added in cleanup)
      triggers a sync. Set back to 15.

## 8. US-28 Regional, US-29 Brightness, US-30 Overnight dim/sleep (owner watching the screen)

- [ ] US-28: change the time zone to a far zone: grid moves "today" and `timedatectl` shows the new zone (needs the
      timedate polkit rule from setup-pi.sh); set it back. 12/24 h and week start.
- [ ] US-29: brightness probe on the real monitor (`ls /sys/class/backlight`, `/dev/i2c-*`, `ddcutil detect`);
      record backend in platform-versions.md "Display capabilities"; owner confirms the screen visibly changes;
      saved brightness reapplied after restart. DDC writes wear monitor EEPROM slightly: keep the test short.
- [ ] US-30: `wlopm --off/--on HDMI-A-1` x10 (then wlr-randr only if that fails); does touch/mouse wake the screen;
      window starting in 2 minutes: dim at start, wake by touch, dim again, normal at end; record the method used in
      platform-versions.md "Display off methods". Leave the test window OFF or set the owner's schedule afterwards.
      **[OWNER OK]** DDC power-off (VCP D6) only after the Preview and owner confirmation.

## 9. US-31 Status, US-32 Wizard, US-33 iCloud guide, US-38 Error handling

- [ ] US-31: Status screen in normal state; with the network removed ("offline" verdict); throttling line with the
      real PSU (`vcgencmd get_throttled` 0x0); power-warning wording with a weak supply if available (owner).
      Technical line (code + detail) and Fix targets (added in cleanup) on a real failing account.
- [ ] US-32: fresh-state wizard end to end on the Pi (with the real Wi-Fi step), resume after power cut mid-wizard,
      "Run setup again" from About. **[OWNER OK]** anything that wipes real state: use a copy (`--state-dir`).
- [ ] US-33: QR code scans with the owner's phone and opens the Apple support page; the guide is readable at arm's
      length. The link may have changed: verify the URL in `docs/icloud-guide.md`.
- [ ] US-38: revoked password (owner revokes at account.apple.com and creates a new one): header "Sign-in problem",
      banner, Fix leads to Update password; credentials-unreadable on a COPY of state with a replaced key; grace
      periods (offline banner appears only after the grace time) with real timing; owner reviews all wording
      (`python3 -m calpi.data.messages` prints the review document).

## 10. US-34 Touchscreen bring-up, US-35 Gestures (needs the touchscreen and the owner)

- [ ] US-34: identify the device (`libinput list-devices`), native mode must be 1920x1080 (otherwise STOP, see story),
      orientation (0/180) and overscan; calibration matrix only if the 9-target test exceeds 12 px (max) error.
      Run with `CALPI_DEV_TOUCHTEST=1` via a temporary drop-in; remove it afterwards.
- [ ] US-34: touch wakes the display while it is off; no throttling with the screen attached (`get_throttled`);
      finger-only walkthrough of every screen (fill the table in platform-versions.md).
- [ ] US-35: swipe left/right for month/week feels right with a finger (thresholds in the gestures classifier are
      guesses); vertical scrolling in settings/agenda is not mistaken for swipes; taps still register.

## 11. US-39 Week view, US-40 Agenda, US-41 Weather

- [ ] US-39: real data week screenshot, overlap-heavy week, current-time line, tap a block for day detail, timings.
- [ ] US-40: agenda with the owner's real events, "Start with" setting, long lists scroll with touch.
- [ ] US-41: Open-Meteo reachability from the Pi and from the owner's network, place search (geocoding), units,
      icons/emoji glyph availability in the installed fonts (missing glyphs show as boxes: check on the screen),
      forecast in day cells, off-by-default behaviour, fetch only when online. Weather now registers itself in the
      periodic registry as `weather` (cleanup); confirm it appears in the `health:` line source count.

## 12. US-36 Performance (only on the Pi)

Method: `docs/performance.md` "Method on the Pi". Everything in its tables is TBD.

- [ ] `scripts/pi health` (`throttled=0x0`, temp < 70 C), then `scripts/pi perf`, `perf --stress`,
      `perf --during-sync --week`; fill in the table, apply optimisations only for misses.
- [ ] Boot: `systemd-analyze blame`, `critical-chain calpi-kiosk.service`, and **[OWNER OK]** 3 stopwatch power
      cycles (target <= 35 s to calendar).
- [ ] Idle CPU with `pidstat` (sysstat is a dev-only install), RSS after startup and after the run, sync process
      peak RSS. Re-run on the final touchscreen and after any later feature.
- [ ] Check `PrivateTmp` does not hide `/tmp/calpi-perf` from the service.

## 13. US-37 Long-running stability (last; freezes the code)

Method and thresholds: `docs/stability.md`. Nothing was run on the Pi.

- [ ] 6 h rehearsal in soak mode, then 5 days soak mode + 9 days normal (`scripts/pi soak start|sample|collect|stop`,
      `scripts/soak-analyze.py`). A deploy resets the soak.
- [ ] RSS slope <= 0.5 MB/day and max <= 150 MB on cairo/Wayland (Broadway RSS growth is not representative), fds,
      threads, periodic sources flat, no zombies, DB/WAL/journal sizes, month-render p90 within +20 %.
- [ ] Safety valve never fires; whether cage passes exit code 75 through.
- [ ] Real multi-hour outage during the soak, and NRestarts=0, one day change per day.
- [ ] Paste results into `docs/stability.md` (timeline, per-metric table, pass/fail).

## Security / owner approvals

- **NetworkManager polkit rule (`/etc/polkit-1/rules.d/50-calpi-networkmanager.rules`).** It used to grant the
  `kiosk` user every `org.freedesktop.NetworkManager.*` action. The cleanup commit narrows it to what Settings ->
  Network uses: `network-control`, `wifi.scan`, `enable-disable-wifi`, `settings.modify.system`,
  `settings.modify.own`. Not granted: wifi.share.*, checkpoint-rollback, reload, enable-disable-network/wwan,
  sleep-wake, hostname/DNS management. **Unverified on a real NM**: walk through scan, join, connect a saved
  network, forget, Wi-Fi on/off as `kiosk`. If an action fails with "not authorized", check
  `journalctl -u polkit` for the action id and add only that id. Also review `51-calpi-timedate.rules` (should only
  allow `org.freedesktop.timedate1.set-timezone`).
- Reboots and power cuts (US-01, US-12, US-36), boot trims (US-01/US-36), deleting or replacing real state or
  credentials (US-12, US-32, US-38), changing the system clock (US-10), DDC power-off (US-30), and leaving any
  test drop-in (`fakenow.conf`, touch test, perf, soak) installed all need the owner's explicit OK.
- SSH key auth only; nothing in the repo contains the owner's credentials.
