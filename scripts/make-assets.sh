#!/usr/bin/env bash
# Regenerate pre-rendered assets (dev machine only; the PNGs are committed).
# Needs: `pip install qrcode` (or qrencode, preferred if present).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p calpi/assets
URL='https://account.apple.com'
OUT=calpi/assets/qr-account-apple-com.png
if command -v qrencode >/dev/null; then
  qrencode -o "$OUT" -s 12 -m 2 -l M "$URL"
else
  python3 scripts/make_qr.py "$OUT" "$URL" 12 2
fi
