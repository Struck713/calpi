---
name: pi-kiosk-setup
description: Provision a headless Raspberry Pi 3B (Raspberry Pi OS Lite, no desktop) to boot straight into a fullscreen GTK/Python kiosk app on a 1920x1080 HDMI screen using the cage Wayland compositor and systemd. Use when setting up or debugging the Pi's OS, display output, resolution, autostart, screen blanking, cursor, boot speed, SD-card wear, or the kiosk systemd service.
---

# Pi 3B kiosk setup (no desktop)

## Architecture (don't deviate without reason)

```
Raspberry Pi OS Lite (no desktop, no X11, no display manager)
  └─ systemd: calpi-kiosk.service  (runs as user `kiosk` on tty1, PAM session)
       └─ cage  (single-app Wayland kiosk compositor, draws via KMS/DRM)
            └─ python3 /opt/calpi/run.py  (GTK app, fullscreen)
```

Why:
- GTK can't draw to the screen on its own. It needs a Wayland compositor or an X server. **cage** is the smallest option: it runs one fullscreen app with no panels or window manager, and it exits when that app exits.
- The display goes through KMS (`vc4-kms-v3d`), which is the default on current Pi OS. Don't use the legacy firmware framebuffer or `fkms`.
- systemd manages the whole chain. If the app crashes, cage exits, and systemd restarts both.

Do NOT install `raspberrypi-ui-mods`, LXDE, labwc desktop sessions, lightdm, or X11. Do NOT use `startx` or `.bash_profile` autostart hacks.

## Pi 3B constraints to keep in mind

- 1 GB RAM and a 4× Cortex-A53 CPU. The VideoCore IV GPU supports **OpenGL ES 2.0 only**, which affects GTK's renderer choice (see the `gtk-kiosk-app` skill).
- Driving 1920x1080@60 over HDMI is fine. Full-screen redraws are expensive, so keep the UI mostly static.
- SD cards wear out and get corrupted on power loss. Consider the overlay filesystem once the setup is stable (below).

## Initial flash

Use Raspberry Pi Imager → **Raspberry Pi OS Lite (64-bit)**. In the OS customisation settings, set the hostname (e.g. `calpi`), an admin user, Wi-Fi, locale/timezone, and **enable SSH with a public key**. The Pi stays headless. All further work happens over SSH.

## Provisioning

Run the bundled script on the Pi as root: [setup-pi.sh](setup-pi.sh). It is idempotent and does the following:

1. Installs `cage`, PyGObject, GTK, fonts, and `wlr-randr`/`grim` for screen control and screenshots.
2. Creates the `kiosk` system user (groups `video render input`).
3. Installs `/etc/pam.d/calpi-kiosk` and `/etc/systemd/system/calpi-kiosk.service` from the templates [calpi-kiosk.service](calpi-kiosk.service) and [pam-calpi-kiosk](pam-calpi-kiosk).
4. Pins the resolution and disables console blanking in `cmdline.txt`.
5. Sets `graphical.target` as default, disables `getty@tty1`, and enables the kiosk service.

Copy it over and run:
```bash
scp .claude/skills/pi-kiosk-setup/{setup-pi.sh,calpi-kiosk.service,pam-calpi-kiosk} calpi:/tmp/
ssh calpi 'sudo bash /tmp/setup-pi.sh'
```

## Display / resolution

- Files are in `/boot/firmware/` (Bookworm and later). Older docs say `/boot/`, which is wrong on current images.
- `config.txt` must contain `dtoverlay=vc4-kms-v3d` (default). Legacy `hdmi_mode`/`hdmi_group`/`hdmi_force_hotplug` are **ignored under KMS**.
- Force the mode with the kernel command line. `cmdline.txt` is ONE line, so append to it and don't add a new line:
  `video=HDMI-A-1:1920x1080@60D consoleblank=0 quiet loglevel=3 logo.nologo vt.global_cursor_default=0`
  (`D` = force the output on even if no EDID is read, e.g. when the screen boots after the Pi.)
- Check which modes the monitor reports: `cat /sys/class/drm/card*-HDMI-A-1/modes`
- Check the live mode under cage: `sudo -u kiosk WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/$(id -u kiosk) wlr-randr`
- If you see overscan (black border), add `disable_overscan=1` to `config.txt`.
- Rotation: `cage` has no rotate flag. Use `wlr-randr --output HDMI-A-1 --transform 90` from an `ExecStartPost`, or append `,rotate=90` to the `video=` argument.

## Cursor, blanking, power

- **Cursor**: cage only shows a pointer when a mouse is attached. The app should also set an invisible cursor (see `gtk-kiosk-app`).
- **Blanking**: cage does not idle-blank. `consoleblank=0` stops the text console blanking before cage starts.
- **Screen off on a schedule** (e.g. at night): `vcgencmd display_power` does NOT work under KMS. Use a systemd timer that runs as `kiosk`:
  `WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/<uid> wlr-randr --output HDMI-A-1 --off` (and `--on`).

## Lean and robust

- Disable services the kiosk doesn't need: `sudo systemctl disable --now bluetooth hciuart avahi-daemon triggerhappy` (keep `ssh` and `systemd-timesyncd`).
- In `config.txt`: `disable_splash=1`. If Bluetooth is unused: `dtoverlay=disable-bt`.
- Time and timezone matter for a display: `sudo raspi-config nonint do_change_timezone America/Chicago` (adjust), then check with `timedatectl`.
- Hardware watchdog (reboots a hung Pi): `dtparam=watchdog=on` in `config.txt`, plus `RuntimeWatchdogSec=15` in `/etc/systemd/system.conf`.
- SD card protection, **after** everything works: `sudo raspi-config` → Performance → Overlay File System. Writes then go to RAM and the root filesystem becomes read-only. Disable the overlay before deploying new code, or deploy to a separate writable partition.

## Debugging checklist

| Symptom | Check |
|---|---|
| Black screen, service restarting | `journalctl -u calpi-kiosk -b -f` |
| `cage: failed to ... seat` / no DRM access | Is PAM file present, `PAMName=` set, `getty@tty1` disabled, user in `video render input`? `loginctl list-sessions` should show a session for `kiosk` on seat0/tty1. |
| Wrong resolution | `/sys/class/drm/card*-HDMI-A-1/modes`, `video=` in cmdline.txt, `wlr-randr` |
| No output when monitor powered on after Pi | Add `D` suffix to `video=` |
| App runs but nothing visible | Take a screenshot with `grim` (see `pi-deploy`). Launching cage by hand over SSH fails because SSH sessions have no seat, so always restart the service and read the journal. |
| Slow / tearing / high CPU | `top`, check GSK renderer (see `gtk-kiosk-app`), check `vcgencmd get_throttled` (0x0 = OK; otherwise weak PSU/heat) |
