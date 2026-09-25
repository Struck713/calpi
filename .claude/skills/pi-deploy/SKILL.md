---
name: pi-deploy
description: Deploy the calpi app from this dev machine to the headless Raspberry Pi over SSH, restart the kiosk, read its logs, and take a screenshot of what's actually on the HDMI screen. Use when asked to deploy, push to the Pi, restart the kiosk, check logs, check what the screen shows, or verify a UI change on real hardware.
---

# Deploy to the Pi and verify on hardware

Assumes the Pi was provisioned with the `pi-kiosk-setup` skill: service `calpi-kiosk`, app in `/opt/calpi`, user `kiosk`.

## Connection

- The host comes from `$CALPI_HOST` (default `calpi.local`) and the SSH user from `$CALPI_USER` (default: SSH config). Prefer a `Host calpi` entry in `~/.ssh/config` with key auth.
- Before doing anything, check connectivity: `ssh -o ConnectTimeout=5 "$CALPI_HOST" true`. If it fails, stop and tell the user. Don't guess IPs or scan the network.
- The devcontainer may not resolve `.local` (mDNS). If so, ask the user for the Pi's IP.

## Deploy

Use [deploy.sh](deploy.sh):
```bash
.claude/skills/pi-deploy/deploy.sh            # sync + restart + show recent logs
.claude/skills/pi-deploy/deploy.sh --no-restart
```
It rsyncs the repo to `/opt/calpi` (excluding `.git`, `.claude`, `.devcontainer`, venvs, caches, tests), fixes ownership, restarts `calpi-kiosk`, and prints the last journal lines. Deploy only files under the project; never sync `/etc/calpi` secrets from here.

If the overlay filesystem is enabled on the Pi (read-only root), a deploy won't persist across reboot. Tell the user rather than disabling the overlay yourself.

## Logs and status

```bash
ssh "$CALPI_HOST" 'systemctl status calpi-kiosk --no-pager'
ssh "$CALPI_HOST" 'journalctl -u calpi-kiosk -b --no-pager -n 100'
ssh "$CALPI_HOST" 'vcgencmd get_throttled; vcgencmd measure_temp; free -m; ps -o pid,rss,pcpu,cmd -C python3'
```
`get_throttled` should be `throttled=0x0`. Anything else means under-voltage or overheating. Report that before chasing software performance problems.

## Screenshot of the real screen

cage supports the wlroots screencopy protocol, so `grim` can capture the live output:
```bash
ssh "$CALPI_HOST" 'sudo -u kiosk env XDG_RUNTIME_DIR=/run/user/$(id -u kiosk) WAYLAND_DISPLAY=wayland-0 grim -t png /tmp/calpi.png'
scp "$CALPI_HOST":/tmp/calpi.png ./scratch-screenshot.png
```
Then Read the PNG to check the UI visually. Always do this after a UI change instead of assuming it rendered correctly. Delete the local copy when you're done; don't commit screenshots.

## Quick performance check

```bash
ssh "$CALPI_HOST" 'top -b -n 3 -d 2 | grep -E "python3|cage" '
```
When the display is idle (between clock ticks), CPU usage should be close to 0%. Sustained CPU use at idle points to a redraw loop. See `gtk-kiosk-app` → Performance.

## Don'ts

- Don't reboot the Pi, change `/boot/firmware/*`, enable/disable the overlay FS, or run `apt upgrade` unless the user asks. These are slow or risky on a remote headless box.
- Don't leave debug env vars (e.g. `GSK_DEBUG`) in the service file after investigating.
