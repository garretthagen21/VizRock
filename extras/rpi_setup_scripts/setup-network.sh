#!/bin/bash
#
# VizRock network setup. Run once on the Pi, as root.
#
#   sudo ./setup-network.sh [hotspot-password]
#
# Layering, highest priority first:
#   1. Ethernet  — plug a cable into the Pi and it wins. No DHCP server needed:
#                  both ends fall back to link-local 169.254.x.x and find each
#                  other by mDNS. This is the path to prefer at the venue.
#   2. VIZROCK — the Pi's own hotspot, for phone control or when there is no
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
# Find the profile by type, not by name. NetworkManager auto-creates it as
# "Wired connection 1" but that is only a default — hardcoding the name meant this
# whole step could silently do nothing.
WIRED="$(nmcli -g NAME,TYPE connection show | awk -F: '$2 ~ /ethernet/ {print $1; exit}')"
if [ -z "$WIRED" ]; then
    echo "    no wired profile yet — plug a cable in once, then re-run this script" >&2
else
    echo "    profile: $WIRED"
    # ipv4.link-local=fallback is the important one: on a direct Pi-to-laptop cable
    # there is no DHCP server, and without it NetworkManager gives up with no address
    # at all rather than self-assigning 169.254.x.x. That is the venue path.
    nmcli connection modify "$WIRED" \
        connection.autoconnect yes \
        connection.autoconnect-priority 100 \
        ipv4.may-fail yes \
        ipv4.link-local fallback 2>/dev/null \
      || nmcli connection modify "$WIRED" \
            connection.autoconnect yes \
            connection.autoconnect-priority 100 \
            ipv4.may-fail yes \
            ipv4.link-local 3          # older NetworkManager: 3 == enabled
fi

echo "==> VIZROCK hotspot as the fallback"
nmcli connection delete VIZROCK 2>/dev/null || true
nmcli connection add type wifi ifname wlan0 con-name VIZROCK autoconnect yes ssid VIZROCK
nmcli connection modify VIZROCK \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$PASSWORD" \
    connection.autoconnect-priority 10
nmcli connection up VIZROCK

echo
echo "Done. The Pi is reachable at http://vizrock-box.local:8080"
echo "  cable  : plug in and browse — nothing to configure"
echo "  wifi   : join VIZROCK, then browse the same address"
echo
echo "Confirm from your laptop:  ping vizrock-box.local"
echo "Set the visuals targets in configs/show_config.json to the machines' .local names."
