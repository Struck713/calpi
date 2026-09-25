---
name: pi-deploy
description: Deploy the calpi app from this dev machine to the headless Raspberry Pi over SSH, restart the kiosk, read its logs, and take a screenshot of what's actually on the HDMI screen. Use when asked to deploy, push to the Pi, restart the kiosk, check logs, check what the screen shows, or verify a UI change on real hardware.
---

# Deploy to the Pi and verify on hardware

Assumes the Pi was provisioned with the `pi-kiosk-setup` skill: service `calpi-kiosk`, app in `/opt/calpi`, user `kiosk`.

## Connection

- The host comes from `$CALPI_HOST` (default `calpi`, an `~/.ssh/config` entry with key auth; fallback `calpi.local` if mDNS resolves) and the SSH user from `$CALPI_USER`. `$CALPI_WAYLAND_DISPLAY` (default `wayland-0`) is used for screenshots.
- Every `scripts/pi` command checks connectivity first (5 s timeout, BatchMode). If it fails, stop and tell the user. Don't guess IPs or scan the network.

## `scripts/pi` (the one entry point)

```bash
scripts/pi deploy [--no-restart]  # snapshot to /opt/calpi.prev, sync run.py + calpi/ only, write calpi/BUILD stamp,
                                  # chown root, precompile .pyc, restart, wait <=45 s for a new "calpi ready" -> "DEPLOY OK <build>"
scripts/pi restart                # restart + wait for readiness
scripts/pi logs [-f] [-n N]       # journal of this boot (default last 100)
scripts/pi status                 # systemctl status, running build, app uptime/RSS/CPU
scripts/pi health                 # get_throttled (warns if not 0x0), temp, memory, load, disk, app RSS/CPU
scripts/pi screenshot [file.png]  # grim on the live HDMI output; default ./scratch-screenshot.png
scripts/pi deps [--update]        # install deps/apt-runtime.txt (--no-install-recommends, never upgrade)
scripts/pi rollback               # swap /opt/calpi <-> /opt/calpi.prev, restart, wait
scripts/pi ssh [cmd...]
```
`.claude/skills/pi-deploy/deploy.sh` is a thin wrapper for `scripts/pi deploy`.

- Only runtime files are deployed: `run.py` and `calpi/`. A new top-level runtime file must be added to the rsync list in `scripts/pi`.
- The build stamp (`<UTC time> <sha[-dirty]> <host>`) is written to `/opt/calpi/calpi/BUILD` (gitignored) and logged in `calpi ready ... build=`.
- Readiness uses a journal cursor, so only lines logged after the restart count. A deploy restarts the app, so mention that if the owner may be looking at the screen.
- Never sync `/etc/calpi` secrets from here.

If the overlay filesystem is enabled on the Pi (read-only root), a deploy won't persist across reboot. Tell the user rather than disabling the overlay yourself.

## Screenshot of the real screen

`scripts/pi screenshot` runs `grim` as the `kiosk` user against the cage socket and copies the PNG back. Then Read the PNG to check the UI visually. Always do this after a UI change instead of assuming it rendered correctly. Delete the local copy when you're done; don't commit screenshots.
If grim says "failed to connect to display", read the real value from the app process (`/proc/<pid>/environ`) and set `CALPI_WAYLAND_DISPLAY`.

## Quick performance check

```bash
ssh "$CALPI_HOST" 'top -b -n 3 -d 2 | grep -E "python3|cage" '
```
When the display is idle (between clock ticks), CPU usage should be close to 0%. Sustained CPU use at idle points to a redraw loop. See `gtk-kiosk-app` → Performance.

## Don'ts

- Don't reboot the Pi, change `/boot/firmware/*`, enable/disable the overlay FS, or run `apt upgrade` unless the user asks. These are slow or risky on a remote headless box.
- Don't leave debug env vars (e.g. `GSK_DEBUG`) in the service file after investigating.
