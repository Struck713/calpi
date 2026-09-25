#!/usr/bin/env bash
# Provision a Raspberry Pi OS Lite install as a cage + GTK kiosk.
# Run as root on the Pi, from the directory containing calpi-kiosk.service and pam-calpi-kiosk.
# Idempotent: safe to re-run.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR=/opt/calpi
KIOSK_USER=kiosk
CMDLINE=/boot/firmware/cmdline.txt
MODE="${MODE:-1920x1080@60D}"
GTK_VERSION="${GTK_VERSION:-4}"   # 4 or 3
WIFI_COUNTRY="${WIFI_COUNTRY:-}"   # ISO 3166 alpha-2, e.g. US, GB, DE; required for Wi-Fi
LEAN="${LEAN:-0}"                  # 1 = disable bluetooth, hciuart, triggerhappy (never avahi)
DISABLE_BT="${DISABLE_BT:-0}"      # 1 = dtoverlay=disable-bt in config.txt

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

echo "==> packages"
apt-get update
apt-get install -y --no-install-recommends \
  cage wlr-randr grim \
  python3 python3-gi python3-gi-cairo "gir1.2-gtk-${GTK_VERSION}.0" \
  fonts-dejavu-core fontconfig \
  rsync

echo "==> wifi country"
if [[ -n "$WIFI_COUNTRY" ]]; then
  raspi-config nonint do_wifi_country "$WIFI_COUNTRY"
  rfkill unblock wifi || true
else
  current="$(raspi-config nonint get_wifi_country 2>/dev/null || true)"
  echo "    WIFI_COUNTRY not given; current: ${current:-<unset>}"
  [[ -n "$current" ]] || echo "    WARNING: Wi-Fi stays rfkill-blocked until a country is set" >&2
fi

echo "==> kiosk user"
if ! id "$KIOSK_USER" &>/dev/null; then
  useradd --system --create-home --shell /usr/sbin/nologin "$KIOSK_USER"
fi
usermod -aG video,render,input "$KIOSK_USER"

echo "==> app dir"
mkdir -p "$APP_DIR"
if [[ ! -f "$APP_DIR/run.py" ]]; then
  echo "    (no app deployed yet — service will restart until $APP_DIR/run.py exists)"
fi

echo "==> pam + systemd unit"
install -m 0644 "$HERE/pam-calpi-kiosk" /etc/pam.d/calpi-kiosk
install -m 0644 "$HERE/calpi-kiosk.service" /etc/systemd/system/calpi-kiosk.service

echo "==> kernel cmdline"
cp -n "$CMDLINE" "$CMDLINE.orig" || true
# drop any previous values we manage, then append ours
line="$(tr -d '\n' < "$CMDLINE" | tr ' ' '\n' \
  | grep -vE '^(video=HDMI-A-1:|consoleblank=|quiet$|loglevel=|logo\.nologo$|vt\.global_cursor_default=)' \
  | tr '\n' ' ')"
line="$line video=HDMI-A-1:${MODE} consoleblank=0 quiet loglevel=3 logo.nologo vt.global_cursor_default=0"
echo "$line" | tr -s ' ' > "$CMDLINE"
cat "$CMDLINE"

echo "==> config.txt"
CONFIG=/boot/firmware/config.txt
grep -q '^dtoverlay=vc4-kms-v3d' "$CONFIG" || echo 'dtoverlay=vc4-kms-v3d' >> "$CONFIG"
grep -q '^disable_splash=1' "$CONFIG" || echo 'disable_splash=1' >> "$CONFIG"

if [[ "$DISABLE_BT" == 1 ]]; then
  grep -q '^dtoverlay=disable-bt' "$CONFIG" || echo 'dtoverlay=disable-bt' >> "$CONFIG"
fi

if [[ "$LEAN" == 1 ]]; then
  echo "==> lean: disabling unused services"
  for s in bluetooth hciuart triggerhappy; do
    if systemctl list-unit-files "$s.service" 2>/dev/null | grep -q "^$s.service"; then
      systemctl disable --now "$s.service" || true
    fi
  done
fi

echo "==> boot target"
systemctl daemon-reload
systemctl disable getty@tty1.service || true
systemctl set-default graphical.target
systemctl enable calpi-kiosk.service

echo "==> done. Deploy the app to $APP_DIR, then reboot."
