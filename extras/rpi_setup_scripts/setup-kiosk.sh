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

# Two very different situations, so detect rather than assume:
#
#   Desktop image  — lightdm/labwc already own the display. Installing cage here
#                    would fight the display manager for it. Autostart Chromium
#                    inside the existing session instead.
#   Lite image     — nothing owns the display, so cage is the whole compositor.
#
if systemctl is-active --quiet lightdm || [ "$(systemctl get-default)" = "graphical.target" ]; then
    MODE="desktop"
else
    MODE="cage"
fi
echo "==> detected: $MODE session"

echo "==> browser"
apt-get update
apt-get install -y chromium-browser || apt-get install -y chromium
BROWSER="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "$BROWSER" ]; then
    echo "no chromium binary found — install it and re-run" >&2
    exit 1
fi
echo "    browser: $BROWSER"

# --password-store=basic stops Chromium reaching for the GNOME keyring, which on an
# autologin box is never unlocked and prompts on every boot. We are incognito and
# store nothing, so there is no secret to protect.
FLAGS="--kiosk --noerrdialogs --disable-infobars --incognito --force-prefers-reduced-motion --start-fullscreen --password-store=basic --disable-features=Translate"
URL="http://localhost:$PORT"

echo "==> stop the screen blanking mid-set"
raspi-config nonint do_blanking 1 2>/dev/null || echo "    (could not set blanking; check Screen Blanking in raspi-config)"

if [ "$MODE" = "desktop" ]; then
    echo "==> autostart in the existing desktop session"
    HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"
    mkdir -p "$HOME_DIR/.config/autostart"
    cat > "$HOME_DIR/.config/autostart/vizrock-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VizRock kiosk
# --start-fullscreen so it does not need a window manager hint to fill the panel
Exec=$BROWSER $FLAGS $URL
X-GNOME-Autostart-enabled=true
EOF
    # trailing colon takes the user's login group; assuming group == username is wrong
    chown -R "$RUN_USER:" "$HOME_DIR/.config" 2>/dev/null || true
    echo
    echo "Kiosk will launch with the desktop session against $URL"
    echo "  remove it : rm ~/.config/autostart/vizrock-kiosk.desktop"
    echo "  start now : $BROWSER $FLAGS $URL &"
else
    echo "==> cage compositor (no desktop present)"
    apt-get install -y cage seatd
    systemctl enable --now seatd
    usermod -aG video,input,render,seat "$RUN_USER"

    RUN_UID="$(id -u "$RUN_USER")"
    UNIT="$(mktemp)"
    sed -e "s|^User=.*|User=$RUN_USER|" \
        -e "s|/run/user/1000|/run/user/$RUN_UID|" \
        -e "s|BROWSER|$BROWSER|" \
        -e "s|http://localhost:8080|$URL|" \
        "$HERE/vizrock-kiosk.service" > "$UNIT"
    install -m 644 "$UNIT" /etc/systemd/system/vizrock-kiosk.service
    rm -f "$UNIT"
    systemctl daemon-reload
    systemctl enable --now vizrock-kiosk
    echo
    echo "Kiosk running against $URL"
    echo "  stop it  : sudo systemctl disable --now vizrock-kiosk"
    echo "  watch it : journalctl -u vizrock-kiosk -f"
fi

echo
echo "If the screen is blank:"
echo "  DSI panel  — check the ribbon is seated; display_auto_detect=1 handles the rest"
echo "  HDMI panel — use HDMI0, the port nearest USB-C. HDMI1 stays dark during boot"
