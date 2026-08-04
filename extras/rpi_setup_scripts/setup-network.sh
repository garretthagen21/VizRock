#!/bin/bash
#
# Show Brain network setup. Run once on the Pi, as root.
#
#   sudo ./setup-network.sh [hotspot-password]
#
# Layering, highest priority first:
#   1. Ethernet  — plug a cable into the Pi and it wins. No DHCP server needed:
#                  both ends fall back to link-local 169.254.x.x and find each
#                  other by mDNS. This is the path to prefer at the venue.
#   2. SHOWBRAIN — the Pi's own hotspot, for phone control or when there is no
#                  cable. Persistent and autoconnecting, so it survives a reboot.
#
# Nothing needs switching: the UI binds 0.0.0.0 and answers on every interface at
# once, and visuals targets are cued on every address their name resolves to.
#
set -euo pipefail

PASSWORD="${1:-}"
if [ -z "$PASSWORD" ]; then
    echo "usage: sudo $0 <hotspot-password>   (8+ characters)" >&2
    exit 1
fi
if [ "${#PASSWORD}" -lt 8 ]; then
    echo "WPA requires at least 8 characters" >&2
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "run me with sudo" >&2
    exit 1
fi

echo "==> mDNS (.local names, both directions)"
apt-get install -y avahi-daemon libnss-mdns avahi-utils
systemctl enable --now avahi-daemon

echo "==> wired connection takes priority when a cable is present"
# link-local so a direct Pi-to-laptop cable works with no DHCP server anywhere
nmcli connection modify "Wired connection 1" \
    connection.autoconnect yes \
    connection.autoconnect-priority 100 \
    ipv4.may-fail yes 2>/dev/null || echo "    (no wired profile yet — created on first plug-in)"

echo "==> SHOWBRAIN hotspot as the fallback"
nmcli connection delete SHOWBRAIN 2>/dev/null || true
nmcli connection add type wifi ifname wlan0 con-name SHOWBRAIN autoconnect yes ssid SHOWBRAIN
nmcli connection modify SHOWBRAIN \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$PASSWORD" \
    connection.autoconnect-priority 10
nmcli connection up SHOWBRAIN

echo
echo "Done. The Pi is reachable at http://show-brain.local:8080"
echo "  cable  : plug in and browse — nothing to configure"
echo "  wifi   : join SHOWBRAIN, then browse the same address"
echo
echo "Confirm from your laptop:  ping show-brain.local"
echo "Set the visuals targets in configs/show_config.json to the machines' .local names."
