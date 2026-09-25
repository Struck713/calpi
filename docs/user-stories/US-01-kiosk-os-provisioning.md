# US-01 — Kiosk OS provisioning

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | — (nothing) |
| **Blocks** | US-03 Deploy workflow, US-12 Crash and power-loss recovery, US-23 Wi-Fi scan and connect, US-34 Touchscreen bring-up |
| **Phase** | 1. Foundation |
| **Can run in parallel with** | US-02 App skeleton |

## Story

> As the owner, I want the Pi to boot straight into the app, full screen, with no desktop, no cursor and no screen blanking.

## Context

This is the base layer of the whole device. When it's done, a Raspberry Pi 3B with a freshly flashed SD card can be turned into a machine that, on every power-on, goes from firmware to kernel to systemd to `cage` to our Python app with nothing in between: no login prompt, no desktop, no mouse pointer, and no screen that goes black after ten minutes.

Most of the work is already scripted in the `pi-kiosk-setup` skill (`.claude/skills/pi-kiosk-setup/`). That skill was written and checked beforehand. **Your job is to run it on real hardware, fix whatever breaks, add the few things this project needs that the skill doesn't do yet (listed below), and record what the device actually is**, so later stories can depend on facts instead of guesses.

Load the `pi-kiosk-setup` skill before you start. It is the source of truth for the architecture (cage + systemd + PAM session on tty1) and it lists what **not** to do (no LXDE, no lightdm, no X11, no `.bash_profile` autostart hacks).

The provisioning files stay in `.claude/skills/pi-kiosk-setup/`. That directory is the **single source** for OS provisioning. Later stories (US-12, US-23, US-28, US-29, US-30, US-34) **add idempotent sections** to `setup-pi.sh` and edit `calpi-kiosk.service` there. Don't make a second copy anywhere else in the repo.

---

## Blockers

### Hard blockers
None. This story can start right away.

### External blockers: you can't finish without these

| Blocker | Why it blocks | What to do if it's missing |
|---|---|---|
| **A physical Raspberry Pi 3B with a reliable power supply** (official 5.1 V / 2.5 A micro-USB) | Everything here runs on the device. A weak supply causes under-voltage, throttling and SD corruption, which look exactly like software bugs. | Stop and ask the owner. Don't try to "simulate" provisioning. |
| **A microSD card (16 GB+, A1/A2 class) and a way to flash it** (Raspberry Pi Imager on the owner's computer) | The devcontainer can't flash cards. | Ask the owner to flash it using the settings in step 1, then continue over SSH. |
| **The HDMI test monitor**, connected before boot | You need it to see that the app is actually on the screen, and to read the modes the monitor reports. | You can do most of the work without it, but you can't tick the acceptance criteria. |
| **Network access from the dev machine to the Pi over SSH**, with key auth | Every later step runs over SSH. | See "Things that may block you mid-work" below. |
| **The owner's Wi-Fi SSID/password** (or Ethernet) for the first boot | The Pi needs a network for `apt-get`. | Ethernet works too. The Pi 3B has a 100 Mbit port. |

### Soft dependencies
- **US-02 (App skeleton)** is being built in parallel. Until it lands, `/opt/calpi/run.py` doesn't exist and the service restarts every 3 seconds. That's expected. To prove the whole chain works, deploy a **temporary placeholder app** (step 7) so you can check fullscreen, cursor and blanking without waiting for US-02. Delete the placeholder once US-02 is deployed.

### Things that may block you mid-work (and what to do)

| Problem | Symptom | What to do |
|---|---|---|
| **The devcontainer can't resolve `calpi.local`** (mDNS doesn't work inside Docker) | `ssh: Could not resolve hostname calpi.local` | Ask the owner for the Pi's IP address (from the router's client list), and use `CALPI_HOST=<ip>`. **Don't scan the network** to find it. |
| **No SSH key in the devcontainer**, or the key isn't in the Pi's `authorized_keys` | `Permission denied (publickey)` | Ask the owner to add the devcontainer's public key (`~/.ssh/id_ed25519.pub`, or generate one with `ssh-keygen -t ed25519`) using Pi Imager's SSH settings, or by appending it to `~/.ssh/authorized_keys` on the Pi. Never ask for or store a password. |
| **`sudo` asks for a password** | `sudo: a terminal is required` | Pi OS normally gives the first user passwordless sudo (`/etc/sudoers.d/010_pi-nopasswd`). If it's missing, ask the owner. Don't edit sudoers blindly. |
| **Wi-Fi is soft-blocked by rfkill** | `nmcli radio` shows `wifi disabled`, `rfkill list` shows `Soft blocked: yes` | Pi OS keeps Wi-Fi blocked until a **Wi-Fi country** is set. Set it with `raspi-config nonint do_wifi_country <CC>` (step 5). Ask the owner for the country code. Don't guess. |
| **`cage` can't take the seat** | Journal: `failed to ... seat`, `Could not take control of session` | Go through the skill's debugging checklist: is the PAM file installed, is `PAMName=` set, is `getty@tty1` disabled, is `kiosk` in `video render input`? `loginctl list-sessions` should show a `kiosk` session on `seat0`/`tty1`. |
| **The monitor shows "No signal" or the wrong resolution** | Black screen, or 1024×768 | Check `cat /sys/class/drm/card*-HDMI-A-1/modes`. If `1920x1080` isn't listed, the monitor or cable can't do it. Report that to the owner. The `D` suffix in `video=` forces the output on even without an EDID. |
| **The OS release is different from what the skill assumes** (for example Trixie instead of Bookworm) | Package names differ, `cage` version differs | Record it in `docs/platform-versions.md` and adjust `setup-pi.sh`. Don't downgrade the OS. |
| **The Pi is throttling** | `vcgencmd get_throttled` isn't `throttled=0x0` | It's the power supply or heat. Tell the owner before chasing software problems. |

---

## Scope

### In scope
- Flashing instructions for the owner (Pi OS Lite 64-bit, SSH key, hostname, Wi-Fi, locale, Wi-Fi country).
- Running and fixing `setup-pi.sh` on the device.
- The additions to the provisioning that this project needs (see the design decisions).
- Checking: boots to fullscreen app, no desktop, no cursor, no blanking, and it survives a reboot.
- Recording the platform versions in `docs/platform-versions.md`.
- A placeholder app used only for testing.

### Out of scope (belongs to other stories)
- Deploy tooling → **US-03**.
- Crash-restart policy, watchdog, SD card wear, journald settings, sd_notify → **US-12**. (You only set the basics that the skill already contains.)
- NetworkManager polkit permissions for the app → **US-23**.
- Timezone polkit rule → **US-28**.
- Backlight/DDC permissions → **US-29**.
- Touchscreen → **US-34**.
- The overlay (read-only) filesystem: **don't enable it.** The app needs `/var/lib/calpi` to be writable and persistent (see US-12).

---

## Acceptance criteria

1. From a cold power-on with the monitor attached, the Pi shows the app fullscreen at **1920×1080** with no login prompt, desktop, panel, window decoration, or text console visible after the kernel boot messages. (A few lines of kernel/firmware output before the app appears are OK, but hide as much as the skill's `cmdline.txt` settings can.)
2. **No mouse cursor** is visible when no mouse is plugged in. With a mouse plugged in, the cursor behaviour is owned by US-11. For this story it's enough that the app sets an invisible cursor.
3. The screen **never blanks** on its own. Check it by leaving the device idle for at least **30 minutes** with the placeholder app, then confirming the screen is still showing it.
4. `systemctl is-enabled calpi-kiosk` → `enabled`. `systemctl get-default` → `graphical.target`. `getty@tty1` is disabled.
5. If the app process is killed (`sudo pkill -f /opt/calpi/run.py`), the service brings the app back within about **5 seconds**.
6. The unit **doesn't wait for the network**. With the network cable unplugged and Wi-Fi out of range, the app still appears (it will be offline). See design decision D3.
7. `/var/lib/calpi` exists, is owned by `kiosk:kiosk`, has mode `0700`, and survives a reboot.
8. The Wi-Fi country is set, and `nmcli radio wifi` → `enabled`.
9. `docs/platform-versions.md` exists and records the values listed in step 9.
10. Running `setup-pi.sh` a second time changes nothing and doesn't fail (it's idempotent).

---

## Design decisions (already made — follow them)

- **D1. cage + systemd + PAM session**, exactly as in the skill. No display manager.
- **D2. The app runs as the system user `kiosk`**, which has no password and no login shell (`/usr/sbin/nologin`) and is in the groups `video render input`. The admin user (the one set in Imager) is only used over SSH.
- **D3. Remove the network-online dependency from the unit.** The skill's template has `After=... network-online.target` and `Wants=network-online.target`. That makes boot wait for `NetworkManager-wait-online`, which can take **30 seconds or more with no network**. That goes against "the calendar appears right away at boot and stays visible offline" (US-04) and against the boot-time target in US-36. The app handles being offline itself (US-17). **Delete both `network-online.target` references** from `calpi-kiosk.service`.
- **D4. Add `StateDirectory=calpi` and `StateDirectoryMode=0700`** to the unit. systemd then creates `/var/lib/calpi` owned by `kiosk` and exports `$STATE_DIRECTORY` to the process. **cage passes its environment to the app**, so the app sees it. `calpi/paths.py` (US-02) reads `$STATE_DIRECTORY` first.
- **D5. Add `RuntimeDirectory=calpi` and `RuntimeDirectoryPreserve=yes`** so `/run/calpi` (tmpfs) exists for US-12's crash counter. The preserve flag keeps it across service restarts, so the crash counter survives an app crash. It's wiped at reboot, which is what we want.
- **D6. Set the Wi-Fi country during provisioning** (`raspi-config nonint do_wifi_country $WIFI_COUNTRY`), with the country passed in as an environment variable to `setup-pi.sh`. Without it Wi-Fi stays rfkill-blocked, and US-23 can't work.
- **D7. Keep the text console hidden**: `consoleblank=0 quiet loglevel=3 logo.nologo vt.global_cursor_default=0` (already in the skill) plus `disable_splash=1` in `config.txt`.
- **D8. Don't install `adwaita-icon-theme` just for icons.** The UI uses text glyphs and bundled PNGs (see the README). Do install `fonts-dejavu-core` (the skill does already).
- **D9. Don't enable the overlay filesystem.** It would throw away `/var/lib/calpi` at every reboot. US-12 covers SD card wear in other ways.
- **D10. Record facts, don't assume them.** Write every version and path you find to `docs/platform-versions.md`.

---

## Implementation plan

### Step 1 — Write the flashing instructions for the owner

You can't flash the card yourself. Write out exact instructions for the owner (put them in `docs/platform-versions.md` under "How this device was flashed", so a rebuild can be repeated):

1. Raspberry Pi Imager → **Raspberry Pi 3** → **Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)**.
2. OS customisation:
   - Hostname: `calpi`
   - Username: the owner's choice (for example `admin`). Password: the owner's choice. You never need it if key auth works.
   - Wi-Fi: SSID, password, **Wi-Fi country** (this also sets the rfkill country)
   - Locale: the owner's timezone and keyboard layout
   - Services: **enable SSH, allow public-key authentication only**, and paste the public key the devcontainer will use. Print it with `cat ~/.ssh/id_ed25519.pub`, or generate one first with `ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`.
3. Insert the card, connect HDMI (the monitor **on**), and power on. The first boot takes 1–3 minutes (it resizes the filesystem and applies the settings).

### Step 2 — Connect and look around

```bash
export CALPI_HOST=calpi.local   # or the IP the owner gives you
ssh -o ConnectTimeout=5 "$CALPI_HOST" 'uname -a; cat /etc/os-release; id; sudo -n true && echo SUDO_OK'
```
If this fails, go to the table in "Things that may block you mid-work". **Don't go further without working passwordless sudo.**

Suggest that the owner adds a `Host calpi` entry to `~/.ssh/config` in the devcontainer:
```
Host calpi
  HostName <ip-or-calpi.local>
  User <admin-user>
  IdentityFile ~/.ssh/id_ed25519
  ServerAliveInterval 30
```

Collect the facts you'll record in step 9:
```bash
ssh calpi '
  cat /etc/os-release | grep -E "PRETTY_NAME|VERSION_CODENAME";
  uname -r;
  python3 --version;
  cat /proc/device-tree/model; echo;
  vcgencmd get_throttled; vcgencmd measure_temp;
  free -m; df -h /;
  systemctl --version | head -1;
  nmcli --version || echo "no NetworkManager";
  cat /sys/class/drm/card*-HDMI-A-1/modes 2>/dev/null | head -5;
  cat /boot/firmware/cmdline.txt; grep -vE "^\s*#|^\s*$" /boot/firmware/config.txt
'
```

### Step 3 — Update the provisioning templates for D3, D4, D5

Edit `.claude/skills/pi-kiosk-setup/calpi-kiosk.service`:

```ini
[Unit]
Description=calpi kiosk (cage + GTK app) on tty1
# NOTE: deliberately NOT waiting for network-online.target (see US-01 D3):
# the calendar must appear immediately, even offline.
After=systemd-user-sessions.service plymouth-quit-wait.service
Wants=dbus.socket systemd-logind.service
After=dbus.socket systemd-logind.service
Conflicts=getty@tty1.service
After=getty@tty1.service
ConditionPathExists=/dev/tty1
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
Type=simple
User=kiosk
WorkingDirectory=/opt/calpi
ExecStart=/usr/bin/cage -d -- /usr/bin/python3 /opt/calpi/run.py
Environment=GSK_RENDERER=cairo
Environment=GTK_A11Y=none
Environment=PYTHONUNBUFFERED=1
# Persistent app state: /var/lib/calpi, owned by kiosk, exported as $STATE_DIRECTORY
StateDirectory=calpi
StateDirectoryMode=0700
# tmpfs scratch that survives service restarts but not reboots (US-12 crash counter)
RuntimeDirectory=calpi
RuntimeDirectoryPreserve=yes
Restart=always
RestartSec=3
# ... PAM/TTY lines unchanged ...
```

Leave `StartLimitIntervalSec`/`StartLimitBurst` as they are for now. **US-12 owns the restart policy** and will change it. Don't touch `Type=`, because US-12 changes that too.

`GTK_A11Y=none` stops GTK trying to connect to the accessibility bus. That saves startup time and avoids log warnings. Keep it.

### Step 4 — Add the Wi-Fi country to `setup-pi.sh`

Add near the top:
```bash
WIFI_COUNTRY="${WIFI_COUNTRY:-}"   # ISO 3166 alpha-2, e.g. US, GB, DE — required for Wi-Fi
```
and a section after the packages:
```bash
echo "==> wifi country"
if [[ -n "$WIFI_COUNTRY" ]]; then
  raspi-config nonint do_wifi_country "$WIFI_COUNTRY"
  rfkill unblock wifi || true
else
  current="$(raspi-config nonint get_wifi_country 2>/dev/null || true)"
  echo "    WIFI_COUNTRY not given; current: ${current:-<unset>}"
  [[ -n "$current" ]] || echo "    WARNING: Wi-Fi stays rfkill-blocked until a country is set" >&2
fi
```
`raspi-config nonint get_wifi_country` may not exist on every release. The `|| true` keeps the script going if it doesn't. Test this on the device.

Also check that the package list still installs on the recorded OS release. For example, on Trixie check that `cage`, `wlr-randr`, and `grim` are all still available (`apt-cache policy cage wlr-randr grim`). If one isn't, **record it and ask**. Don't swap in a different compositor.

### Step 5 — Copy it over and run the setup

```bash
scp .claude/skills/pi-kiosk-setup/{setup-pi.sh,calpi-kiosk.service,pam-calpi-kiosk} calpi:/tmp/
ssh calpi 'sudo WIFI_COUNTRY=<CC> bash /tmp/setup-pi.sh'
```
Read the whole output. Afterwards, check:
```bash
ssh calpi '
  id kiosk;
  systemctl is-enabled calpi-kiosk; systemctl get-default;
  systemctl is-enabled getty@tty1 || true;
  cat /boot/firmware/cmdline.txt;
  nmcli radio wifi; rfkill list
'
```

### Step 6 — Lean down the boot (from the skill's "Lean and robust" section)

Only disable what the skill lists, and only if the service exists on this release:
```bash
ssh calpi 'for s in bluetooth hciuart avahi-daemon triggerhappy; do
  systemctl list-unit-files "$s.service" >/dev/null 2>&1 && sudo systemctl disable --now "$s" || true; done'
```
**Keep `avahi-daemon` if the owner connects with `calpi.local`.** Disabling it breaks mDNS name resolution. Ask first, or keep it. **Keep** `ssh`, `NetworkManager`, and `systemd-timesyncd`.

Add these to `setup-pi.sh` too, so they're repeatable: a `LEAN=1` flag that disables `bluetooth`, `hciuart`, and `triggerhappy` (not avahi), plus `dtoverlay=disable-bt` in `config.txt` when `DISABLE_BT=1`.

### Step 7 — Deploy a placeholder app to test the chain

US-02 isn't ready yet, so install a tiny placeholder. **It is only for this story.** Write it to `/opt/calpi/run.py` straight from the Pi shell (don't add it to the repo), or copy the skill's `example_app.py`:

```bash
scp .claude/skills/gtk-kiosk-app/example_app.py calpi:/tmp/run.py
ssh calpi 'sudo install -D -m 0644 /tmp/run.py /opt/calpi/run.py && sudo systemctl restart calpi-kiosk'
```
`example_app.py` fetches `https://example.com` every 15 minutes. That's fine for a test.

Also add a line that proves `STATE_DIRECTORY` gets through cage. Temporarily run this instead:
```bash
ssh calpi 'sudo systemctl show calpi-kiosk -p Environment; \
  pid=$(pgrep -f "/opt/calpi/run.py" | head -1); sudo tr "\0" "\n" < /proc/$pid/environ | grep -E "STATE_DIRECTORY|RUNTIME_DIRECTORY|GSK_RENDERER|WAYLAND_DISPLAY"'
```
You should see `STATE_DIRECTORY=/var/lib/calpi`, `RUNTIME_DIRECTORY=/run/calpi`, `GSK_RENDERER=cairo`, and `WAYLAND_DISPLAY=wayland-0` (the socket name may vary). **Record the actual `WAYLAND_DISPLAY` value.** US-03, US-29 and US-30 depend on it.

### Step 8 — Check each acceptance criterion

| Check | How |
|---|---|
| Fullscreen at 1080p | Take a screenshot as described in the `pi-deploy` skill (`grim`) and look at it. Confirm the PNG is 1920×1080: `file scratch-screenshot.png`. Then confirm with the owner that the physical screen shows the same. |
| Live mode | `sudo -u kiosk env XDG_RUNTIME_DIR=/run/user/$(id -u kiosk) WAYLAND_DISPLAY=wayland-0 wlr-randr` → `1920x1080 px, 60.000000 Hz (current)` |
| No cursor | Ask the owner to look at the screen, with no mouse plugged in. |
| No blanking | Leave it idle for 30+ minutes, then take another screenshot. **And** ask the owner to check the physical screen: some monitors go to their own standby when the picture doesn't change. If the monitor does that, note it as a monitor setting, not a Pi problem. |
| Restart | `sudo pkill -f /opt/calpi/run.py; sleep 6; systemctl is-active calpi-kiosk; journalctl -u calpi-kiosk -n 20 --no-pager` |
| Survives reboot | `sudo reboot` (**ask the owner first**, as the `pi-deploy` skill says). Wait about 90 seconds. `ssh calpi 'systemctl is-active calpi-kiosk; ls -ld /var/lib/calpi'` |
| Boots offline | Ask the owner to unplug Ethernet and/or turn off the Wi-Fi router, then power-cycle. The app must appear. Time it with a stopwatch and record the number (US-36 will want it). |
| Idempotent | Run `setup-pi.sh` again. `diff` `cmdline.txt` before and after. No duplicate entries in `config.txt`. |

### Step 9 — Record the platform facts

Create `docs/platform-versions.md`:

```markdown
# Platform versions (recorded on the device)

Recorded: <date> by <who>, from `ssh calpi ...` output.

| Item | Value |
|---|---|
| Board | Raspberry Pi 3 Model B Rev 1.2 |
| OS | Raspberry Pi OS Lite 64-bit, Debian <codename> (<version>) |
| Kernel | ... |
| systemd | ... |
| Python (/usr/bin/python3) | 3.x.y |
| GTK 4 | 4.x.y  (python3 -c 'import gi; gi.require_version("Gtk","4.0"); from gi.repository import Gtk; print(Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version())' — run under cage or with a display, it hangs otherwise; alternatively `dpkg -s libgtk-4-1 | grep Version`) |
| cage | `dpkg -s cage | grep Version` |
| NetworkManager | ... |
| WAYLAND_DISPLAY under the service | wayland-0 |
| HDMI connector name | HDMI-A-1 |
| Monitor modes | ... |
| Wi-Fi country | .. |
| Boot to app visible (online / offline) | NN s / NN s |

## How this device was flashed
...
```

**Use `dpkg -s libgtk-4-1`** to find the GTK version. Importing Gtk over SSH with no display hangs (see the `gtk-kiosk-app` skill).

### Step 10 — Update the skill documentation

In `.claude/skills/pi-kiosk-setup/SKILL.md`:
- Document the `WIFI_COUNTRY` and `LEAN` variables.
- Say why the network-online dependency was removed.
- Mention `StateDirectory`/`RuntimeDirectory`.
- Keep the skill short and factual, matching its current style.

---

## Files

| File | Change |
|---|---|
| `.claude/skills/pi-kiosk-setup/calpi-kiosk.service` | Remove network-online; add StateDirectory/RuntimeDirectory |
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | Wi-Fi country, optional LEAN/DISABLE_BT sections |
| `.claude/skills/pi-kiosk-setup/SKILL.md` | Document the above |
| `docs/platform-versions.md` | **New.** Recorded facts and flashing instructions |

Nothing goes into `calpi/` in this story.

---

## Testing

There's no unit testing here. It's all checking on hardware (step 8). Save the command outputs you used as evidence in your hand-off notes: `systemctl` states, the screenshot's dimensions, and the offline boot time.

---

## Pitfalls

- **`cmdline.txt` must stay ONE line.** A newline in it breaks boot. The script handles this. If you edit by hand, check with `wc -l` (it must print `0` or `1`).
- **`/boot/firmware/`, not `/boot/`**, on current images.
- **Don't launch `cage` by hand over SSH** to test something. SSH sessions have no seat, so it fails confusingly. Always go through the service.
- **Don't `apt upgrade`** as part of this story unless the owner asks. It takes a long time and changes the versions you're recording.
- **Don't disable avahi** without checking whether the owner relies on `calpi.local`.
- **Monitor standby isn't blanking.** A monitor's own power saving is a monitor setting. Record it rather than chasing it in software.
- **The placeholder `run.py` isn't part of the product.** Once US-02 and US-03 land, the real deploy replaces it (US-03 uses `rsync --delete`).

---

## Definition of done

- [ ] All 10 acceptance criteria checked on the device, with evidence in the hand-off notes.
- [ ] Skill templates updated (D3, D4, D5, D6), and the skill doc updated.
- [ ] `docs/platform-versions.md` written.
- [ ] `setup-pi.sh` is idempotent (you've run it twice).
- [ ] The owner has confirmed on the physical screen: no desktop, no cursor, no blanking after 30 minutes.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| Service name `calpi-kiosk`, app at `/opt/calpi/run.py`, runs as `kiosk` | US-03, US-12, everything |
| `$STATE_DIRECTORY=/var/lib/calpi` (0700, `kiosk`), persistent | US-02 `paths.py`, US-04, US-05, US-13 |
| `$RUNTIME_DIRECTORY=/run/calpi`, preserved across restarts, cleared at reboot | US-12 |
| The unit does **not** wait for network-online | US-17, US-36 |
| `WAYLAND_DISPLAY` value and output name (`HDMI-A-1`) recorded in `docs/platform-versions.md` | US-03 (screenshots), US-29, US-30, US-34 |
| Wi-Fi country set; NetworkManager manages `wlan0` | US-23 |
| `setup-pi.sh` is the single idempotent provisioning script; later stories add sections to it | US-12, US-23, US-28, US-29, US-30, US-34 |
