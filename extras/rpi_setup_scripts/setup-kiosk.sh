#!/bin/bash
#
# Optional: show the VizRock UI on a screen plugged into the Pi.
#
#   sudo ./setup-kiosk.sh [port]        # port defaults to 8080
#
# This is entirely independent of the show. It installs a Wayland kiosk
# compositor (cage) running Chromium against http://localhost, so the screen is
# just another browser client — the same thing your phone is. The brain has no
# idea it exists, and `systemctl disable --now vizrock-kiosk` removes it.
#
# Not called by install.sh. Run it only if you have a screen attached.
#
set -euo pipefail

PORT="${1:-8080}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-pi}"

if [ "$(id -u)" -ne 0 ]; then echo "run me with sudo" >&2; exit 1; fi
if ! [ "$PORT" -eq "$PORT" ] 2>/dev/null; then
    echo "port must be a number, got '$PORT'" >&2; exit 1
fi

echo "==> kiosk packages"
apt-get update
apt-get install -y cage seatd
# Raspberry Pi OS calls it chromium-browser, Debian calls it chromium
apt-get install -y chromium-browser || apt-get install -y chromium

BROWSER="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "$BROWSER" ]; then
    echo "no chromium binary found — install it and re-run" >&2
    exit 1
fi
echo "    browser: $BROWSER"

echo "==> seat access for $RUN_USER"
systemctl enable --now seatd
usermod -aG video,input,render,seat "$RUN_USER"

echo "==> kiosk unit"
RUN_UID="$(id -u "$RUN_USER")"
UNIT="$(mktemp)"
sed -e "s|^User=.*|User=$RUN_USER|" \
    -e "s|/run/user/1000|/run/user/$RUN_UID|" \
    -e "s|BROWSER|$BROWSER|" \
    -e "s|http://localhost:8080|http://localhost:$PORT|" \
    "$HERE/vizrock-kiosk.service" > "$UNIT"
install -m 644 "$UNIT" /etc/systemd/system/vizrock-kiosk.service
rm -f "$UNIT"

systemctl daemon-reload
systemctl enable --now vizrock-kiosk

echo
echo "Kiosk running against http://localhost:$PORT"
echo "  stop it     : sudo systemctl disable --now vizrock-kiosk"
echo "  watch it    : journalctl -u vizrock-kiosk -f"
echo
echo "If the screen is blank, check the cable is in HDMI0 — the port nearest USB-C."
echo "Touch panels may need a dtoverlay line in /boot/firmware/config.txt; see the"
echo "panel's own documentation."
