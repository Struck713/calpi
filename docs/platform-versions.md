# Platform versions (recorded on the device)

STATUS: **not yet recorded.** No Pi was reachable when US-01 was implemented. Fill the
`TBD` cells from the output of the command in "Collecting the facts" and delete this line.
Until then, write code for Python 3.11 and GTK 4.8 (see `user-stories/README.md`).

Recorded: TBD by TBD.

| Item | Value |
|---|---|
| Board | TBD (`cat /proc/device-tree/model`) |
| OS | TBD (Raspberry Pi OS Lite 64-bit, Debian codename/version) |
| Kernel | TBD |
| systemd | TBD |
| Python (/usr/bin/python3) | TBD |
| SQLite (Python sqlite3 module) | devcontainer 3.46.1; Pi: TBD (`/usr/bin/python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`) |
| GTK 4 | TBD (`dpkg -s libgtk-4-1 \| grep Version`; do not import Gtk over SSH, it hangs) |
| cage | TBD (`dpkg -s cage \| grep Version`) |
| NetworkManager | TBD |
| WAYLAND_DISPLAY under the service | TBD (expected `wayland-0`; US-03, US-29, US-30 depend on it) |
| HDMI connector name | TBD (expected `HDMI-A-1`) |
| Monitor modes | TBD |
| Wi-Fi country | TBD |
| Boot to app visible (online / offline) | TBD s / TBD s |
| cage, wlr-randr, grim available via apt | TBD (`apt-cache policy cage wlr-randr grim`) |

## Collecting the facts

```bash
ssh calpi '
  grep -E "PRETTY_NAME|VERSION_CODENAME" /etc/os-release; uname -r; python3 --version;
  cat /proc/device-tree/model; echo;
  vcgencmd get_throttled; vcgencmd measure_temp; free -m; df -h /;
  systemctl --version | head -1; nmcli --version;
  dpkg -s libgtk-4-1 cage | grep -E "^(Package|Version)";
  cat /sys/class/drm/card*-HDMI-A-1/modes | head -5;
  cat /boot/firmware/cmdline.txt; grep -vE "^\s*#|^\s*$" /boot/firmware/config.txt
'
```

## How this device was flashed

1. Raspberry Pi Imager: device **Raspberry Pi 3**, OS **Raspberry Pi OS (other) -> Raspberry Pi OS Lite (64-bit)**.
2. OS customisation:
   - Hostname `calpi`.
   - Username and password of the owner's choice (not needed if key auth works).
   - Wi-Fi SSID, password and **Wi-Fi country** (also sets the rfkill country).
   - Locale: the owner's timezone and keyboard layout.
   - Services: enable SSH, public-key authentication only, paste the devcontainer's public key
     (`cat ~/.ssh/id_ed25519.pub`, or first `ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`).
3. Insert the card, connect HDMI with the monitor on, power on with the official 5.1 V / 2.5 A supply.
   First boot takes 1-3 minutes.
4. Optional `~/.ssh/config` in the devcontainer:
   ```
   Host calpi
     HostName <ip-or-calpi.local>
     User <admin-user>
     IdentityFile ~/.ssh/id_ed25519
     ServerAliveInterval 30
   ```
   (`calpi.local` often does not resolve inside Docker; use the Pi's IP.)
5. Provision:
   ```bash
   scp .claude/skills/pi-kiosk-setup/{setup-pi.sh,calpi-kiosk.service,pam-calpi-kiosk} calpi:/tmp/
   ssh calpi 'sudo WIFI_COUNTRY=<CC> bash /tmp/setup-pi.sh'
   ```

## Display capabilities (US-29)

Not yet recorded: no Pi or monitor was reachable when US-29 was built. On the Pi, run:
`ls -l /sys/class/backlight/ /dev/i2c-*; id kiosk; sudo -u kiosk ddcutil detect --terse; sudo -u kiosk ddcutil --terse getvcp 10`
and fill in: monitor model, backlight device (usually none for HDMI), DDC/CI supported (yes/no), backend chosen
by the probe (`journalctl -u calpi-kiosk | grep "brightness: backend"`).

## Display off methods (US-30)

Not yet recorded: no Pi or monitor was reachable when US-30 was built. On the Pi (owner watching the screen), try,
as the kiosk user with `XDG_RUNTIME_DIR=/run/user/$(id -u kiosk) WAYLAND_DISPLAY=wayland-0`:
`wlopm` (lists outputs), `wlopm --off HDMI-A-1; sleep 5; wlopm --on HDMI-A-1` (x10), then only if that fails
`wlr-randr --output HDMI-A-1 --off/--on`. Record which work reliably, whether the monitor wakes by mouse/touch while
off, and the method the app picked (`journalctl -u calpi-kiosk | grep "display power: methods"`,
`grep "dim: night"`). DDC (VCP D6) and wlr-randr are only used after Preview + owner confirmation.
