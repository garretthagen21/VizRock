#!/bin/bash
#
# Show Brain — one-shot install on a fresh Raspberry Pi OS Lite (Bookworm).
#
#   git clone https://github.com/garretthagen21/VizRock-Brain.git ~/show-brain
#   cd ~/show-brain && sudo extras/rpi_setup_scripts/install.sh <hotspot-password>
#
# Everything below is idempotent — safe to re-run after a git pull.
#
set -euo pipefail

PASSWORD="${1:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUN_USER="${SUDO_USER:-pi}"

if [ "$(id -u)" -ne 0 ]; then echo "run me with sudo" >&2; exit 1; fi
if [ -z "$PASSWORD" ]; then echo "usage: sudo $0 <hotspot-password>" >&2; exit 1; fi
if [ "$REPO" != "/home/$RUN_USER/show-brain" ]; then
    echo "WARNING: the systemd unit expects /home/$RUN_USER/show-brain, found $REPO" >&2
    echo "         clone there, or edit show-brain.service before enabling it." >&2
fi

echo "==> system packages"
apt-get update
apt-get install -y python3-venv libasound2-dev libjack-dev i2c-tools avahi-utils

echo "==> I2C for the OLED"
raspi-config nonint do_i2c 0

echo "==> python environment"
sudo -u "$RUN_USER" python3 -m venv "$REPO/venv"
# editable: paths.py resolves configs/ inside the clone, and the UI writes there at runtime
sudo -u "$RUN_USER" "$REPO/venv/bin/pip" install --upgrade pip
sudo -u "$RUN_USER" "$REPO/venv/bin/pip" install -e "$REPO"

echo "==> stable device names"
install -m 644 "$HERE/99-showbrain.rules" /etc/udev/rules.d/
udevadm control --reload

echo "==> network (mDNS, wired priority, SHOWBRAIN fallback)"
"$HERE/setup-network.sh" "$PASSWORD"

echo "==> boot as an appliance"
install -m 644 "$HERE/show-brain.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now show-brain

echo
echo "Installed. http://vizrock-brain.local:8080"
systemctl --no-pager --lines=5 status show-brain || true
echo
echo "Next: set the visuals targets in configs/show_config.json — or just edit them"
echo "      in the OUTPUTS panel of the web UI and hit APPLY."
