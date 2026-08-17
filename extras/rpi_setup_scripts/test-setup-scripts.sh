#!/bin/bash
#
# Dry-run install.sh and setup-network.sh with every system command mocked.
#
#   ./test-setup-scripts.sh
#
# Verifies guards, call sequence, argument quoting and idempotency without a Pi.
# It cannot verify that apt/nmcli/systemctl behave correctly on real hardware —
# only that we call them correctly.
#
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
FAKE="$WORK/bin"; mkdir -p "$FAKE"
MOCKLOG="$WORK/calls.log"
trap 'rm -rf "$WORK"' EXIT

# stubs log one argument per line so word-splitting bugs are visible
for cmd in apt-get raspi-config udevadm systemctl nmcli install sudo usermod; do
    cat > "$FAKE/$cmd" <<EOF
#!/bin/bash
{ echo "CMD $cmd"; for a in "\$@"; do echo "ARG \$a"; done; } >> "\$MOCKLOG"
exit 0
EOF
    chmod +x "$FAKE/$cmd"
done
printf '#!/bin/bash\nexit 0\n' > "$FAKE/chromium-browser"; chmod +x "$FAKE/chromium-browser"
# nmcli needs to answer the profile lookup, otherwise the wired branch is skipped
cat > "$FAKE/nmcli" <<'EOF'
#!/bin/bash
{ echo "CMD nmcli"; for a in "$@"; do echo "ARG $a"; done; } >> "$MOCKLOG"
if [ "$1" = "-g" ]; then echo "Wired connection 1:802-3-ethernet"; fi
exit 0
EOF
chmod +x "$FAKE/nmcli"
cat > "$FAKE/id" <<'EOF'
#!/bin/bash
echo "${FAKE_UID:-0}"
EOF
chmod +x "$FAKE/id"

PASS=0; FAIL=0
check(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; PASS=$((PASS+1));
         else echo "  FAIL $1 (got '$2' want '$3')"; FAIL=$((FAIL+1)); fi; }
flat(){ sed 's/^CMD //; s/^ARG //' "$MOCKLOG" | tr '\n' ' '; }
has(){ flat | grep -qF "$1" && echo yes || echo no; }
arg(){ grep -qxF "ARG $1" "$MOCKLOG" && echo yes || echo no; }
run(){ : > "$MOCKLOG"; export MOCKLOG FAKE_UID="${FAKE_UID:-0}"
       PATH="$FAKE:$PATH" bash "$@" > "$WORK/out.txt" 2>&1; echo $?; }

echo "--- guards ---"
FAKE_UID=1000 rc=$(run "$HERE/install.sh" secretpw);   check "non-root refused" "$rc" 1
check "  ...with a message" "$(grep -c 'run me with sudo' "$WORK/out.txt")" 1
FAKE_UID=0
rc=$(run "$HERE/install.sh");                          check "missing password refused" "$rc" 1
rc=$(run "$HERE/setup-network.sh" short);              check "short password refused" "$rc" 1
rc=$(run "$HERE/setup-network.sh");                    check "network needs a password" "$rc" 1

echo "--- full install ---"
rc=$(run "$HERE/install.sh" vizrockpw);              check "completes" "$rc" 0
check "log is not empty"       "$([ -s "$MOCKLOG" ] && echo yes || echo no)" yes
check "installs packages"      "$(has 'apt-get install')" yes
check "enables I2C"            "$(has 'raspi-config nonint do_i2c 0')" yes
check "creates the venv"       "$(has 'python3 -m venv')" yes
check "editable install"       "$(has 'pip install -e')" yes
check "installs udev rules"    "$(has '99-vizrock.rules /etc/udev/rules.d/')" yes
check "reloads udev"           "$(has 'udevadm control --reload')" yes
check "installs the unit"      "$(has '/etc/systemd/system/vizrock.service')" yes
check "enables the service"    "$(has 'systemctl enable --now vizrock')" yes
check "brings up the hotspot"  "$(has 'nmcli connection up VIZROCK')" yes
check "hotspot is an AP"       "$(has '802-11-wireless.mode ap')" yes
check "shares ipv4"            "$(arg 'ipv4.method')" yes
check "password is set"        "$(arg 'vizrockpw')" yes
check "wired beats hotspot"    "$(grep -qxF 'ARG 100' "$MOCKLOG" && grep -qxF 'ARG 10' "$MOCKLOG" && echo yes || echo no)" yes
check "wired profile found by type" "$(arg '-g')" yes
check "link-local fallback set"     "$(arg 'ipv4.link-local')" yes
check "profile name is ONE arg" "$(arg 'Wired connection 1')" yes
check "no empty arguments"     "$(grep -qx 'ARG ' "$MOCKLOG" && echo bad || echo good)" good
# the generated unit lives in a mktemp file whose name differs every run; that is
# not a idempotency failure, so normalise it before comparing
normalise(){ sed -E 's#^(ARG )(/var/folders/|/tmp/)[^ ]*#\1TMPFILE#' "$MOCKLOG"; }
FIRST=$(normalise)

echo "--- idempotency ---"
rc=$(run "$HERE/install.sh" vizrockpw);              check "second run completes" "$rc" 0
check "second run identical"   "$([ "$FIRST" = "$(normalise)" ] && echo yes || echo no)" yes
check "deletes stale hotspot"  "$(has 'connection delete VIZROCK')" yes

echo "--- the unit adapts to the real user and path ---"
UNIT_OUT="$WORK/generated.service"
sed -e "s|^User=.*|User=someoneelse|" -e "s|/home/pi/vizrock|/opt/vizrock|g" \
    "$HERE/vizrock.service" > "$UNIT_OUT"
check "User is rewritten"      "$(grep -c '^User=someoneelse' "$UNIT_OUT")" 1
check "no stale pi user"       "$(grep -c '^User=pi' "$UNIT_OUT")" 0
check "paths are rewritten"    "$(grep -c '/opt/vizrock' "$UNIT_OUT")" 2
check "no stale clone path"    "$(grep -c '/home/pi/vizrock' "$UNIT_OUT")" 0

echo "--- kiosk is optional and independent ---"
check "install.sh never calls it" \
      "$(grep -c 'setup-kiosk' "$HERE/install.sh")" 0
rc=$(run "$HERE/setup-kiosk.sh"); check "kiosk completes" "$rc" 0
check "installs cage"          "$(has 'apt-get install -y cage seatd')" yes
check "enables seatd"          "$(has 'systemctl enable --now seatd')" yes
check "grants seat access"     "$(has 'usermod -aG video,input,render,seat')" yes
check "enables the kiosk unit" "$(has 'systemctl enable --now vizrock-kiosk')" yes
FAKE_UID=1000 rc=$(run "$HERE/setup-kiosk.sh"); check "kiosk refuses non-root" "$rc" 1
FAKE_UID=0
rc=$(run "$HERE/setup-kiosk.sh" notaport); check "kiosk rejects a bad port" "$rc" 1

# the whole point: a kiosk failure must not be able to stop the show
check "unit orders after the show"  "$(grep -c '^After=vizrock.service' "$HERE/vizrock-kiosk.service")" 1
check "unit does NOT Require it"    "$(grep -c '^Requires=' "$HERE/vizrock-kiosk.service")" 0
check "unit restarts on crash"      "$(grep -c '^Restart=always' "$HERE/vizrock-kiosk.service")" 1
check "kiosk points at localhost"   "$(grep -c 'http://localhost' "$HERE/vizrock-kiosk.service")" 1
check "no python package touched"   "$(grep -rc 'kiosk' "$HERE/../../vizrock" 2>/dev/null | grep -v ':0' | wc -l | tr -d ' ')" 0

echo "--- unit matches the package ---"
check "ExecStart is the console script" \
      "$(grep ExecStart "$HERE/vizrock.service" | sed 's/.*bin\///')" "vizrock_run"
check "WorkingDirectory matches clone path" \
      "$(grep WorkingDirectory "$HERE/vizrock.service" | cut -d= -f2)" "/home/pi/vizrock"

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
