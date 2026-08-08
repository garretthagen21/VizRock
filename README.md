# Show Brain

A headless Raspberry Pi appliance that turns footswitch triggers into a synced show:
Resolume visuals (over the network) + optional DMX + wearable LED rings, driven by an
**arm-and-GO** cue model. Configured from any browser; runs with no WiFi at the venue.

```
FM3 + M-VAVE Chocolate ──USB MIDI──► Pi (brain) ──► OSC     ► Resolume (THC board + clip audio)
                                       │         ├─ Art-Net ► DMX fixtures (optional)
                                       │         └─ serial  ► USB→ESP-NOW TX ──► ring nodes
   phone/laptop browser ──WS──► UI     └─ OLED on the pedalboard (LIVE / NEXT / status)
```

Two pieces of state: **LIVE** (playing now) and **ARMED** (what GO fires next).
PREV/NEXT move ARMED only; GO commits it and auto-arms the next scene. Every output is
an isolated adapter — a missing or unplugged one is a logged warning, never a crash, and
the brain re-pushes the current cue when it reconnects.

The ESP32 sketches live in the sibling repo **[VizRock-Firmware](../VizRock-Firmware)**.

## Layout
- `vizrock/` — the package (`vizrock.py` state machine, `managers/`, `outputs/`,
  `interface/`, `configurations/`, `constants/`)
- `configs/show_config.json` — outputs, MIDI inputs, trigger map, DMX cues
- `configs/scenes.json` — the show (edited live from the UI, saved here)
- `extras/rpi_setup_scripts/` — udev rule + systemd unit
- `setup.py` — deps and the `vizrock_run` console script

## Install (Raspberry Pi OS Lite, Bookworm)

One command on a fresh flash — packages, venv, I2C, udev, mDNS, hotspot, systemd:

```bash
git clone https://github.com/garretthagen21/VizRock.git
cd VizRock && sudo extras/rpi_setup_scripts/install.sh <hotspot-password>
```

Clone wherever you like — the installer rewrites the systemd unit for the actual path and
user. Idempotent, so re-run it after a `git pull`. Then open
`http://vizrock-box.local:8080`.
Flash the SD card with Raspberry Pi Imager and preset the hostname — `vizrock-box` here, but it is a free choice and nothing in the
code depends on it, plus
your WiFi, and SSH with password auth, so the only device-side step is the clone. Password
auth rather than key-only means you can SSH from any machine at the venue, not just the
one holding your key — the Pi is never internet-facing.

<details><summary>Manual steps, if you'd rather not run the script</summary>

Use **Raspberry Pi OS Lite** (not Desktop). **Bookworm** is the verified target; Trixie is
untested because `python-rtmidi` publishes no cp313 wheels and would compile from source.

Imager now defaults to Trixie. For Bookworm: *Choose OS* → **Raspberry Pi OS (other)** →
**Raspberry Pi OS Lite (Legacy, 64-bit)**. Failing that, download the Bookworm image from
raspberrypi.com/software/operating-systems and use *Use custom* in Imager.
```bash
sudo apt update && sudo apt install -y python3-venv libasound2-dev libjack-dev i2c-tools \
  avahi-daemon libnss-mdns          # mDNS: .local names, both directions
git clone https://github.com/garretthagen21/VizRock.git && cd VizRock
python3 -m venv venv && ./venv/bin/pip install -e .
sudo raspi-config nonint do_i2c 0          # enable I2C for the OLED
sudo cp extras/rpi_setup_scripts/99-vizrock.rules /etc/udev/rules.d/ && sudo udevadm control --reload
./venv/bin/vizrock_run                   # test run; open http://<pi>.local:8080
```
The systemd unit is generated for wherever you cloned, so the location is free.

Boot as an appliance:
```bash
sudo cp extras/rpi_setup_scripts/vizrock.service /etc/systemd/system/
sudo systemctl enable --now vizrock
```
</details>

## Connecting at the venue

**Prefer a cable.** The UI binds `0.0.0.0:8080`, so the Pi answers on every interface at once —
ethernet, WiFi, hotspot — with nothing to configure or switch. A direct ethernet run from the
Pi to your laptop needs no DHCP server: both ends take link-local `169.254.x.x` addresses and
find each other by mDNS at `vizrock-box.local:8080`. One cheap switch puts the Pi, your laptop
and THC's machine on one wire and covers every connection in the show.

Because link-local addresses are assigned at random, **use mDNS names, not IPs**, for the
visuals targets:

```json
"resolume": { "type": "osc", "hosts": ["thc-resolume.local", "my-laptop.local"], "port": 7000 }
```

Names resolve on a background thread, never during a cue, and the OUTPUTS panel shows each
one as `host→ip` or `(unresolved)` — the closest thing to delivery feedback OSC allows. Plain
IPs still work if you prefer them.

Names that resolve to several addresses — a laptop on both a cable and WiFi — are cued on
**all** of them. The OSC verbs are idempotent, so the duplicate costs one UDP packet and buys
automatic failover if the cable is pulled mid-show.

## Network setup — run once

```bash
sudo extras/rpi_setup_scripts/setup-network.sh <hotspot-password>
```

Installs mDNS, gives the wired connection top priority, and creates a persistent **VIZROCK**
hotspot that autoconnects on boot as the fallback. Nothing needs switching afterwards — the
cable wins when it's plugged in, the hotspot is there when it isn't, and the UI answers on
every interface either way.

### Phone or tablet at the pedalboard

No venue network, router or internet needed — the Pi is the access point and hands out DHCP
itself. Join **VIZROCK** and browse `vizrock-box.local:8080`.

If the name doesn't resolve — Android browsers are patchy with mDNS where iOS is not — use
**`http://10.42.0.1:8080`**. NetworkManager's shared mode always places the Pi at that address,
so it's a reliable fallback. Expect a "no internet" warning; stay connected and the phone
routes LAN over WiFi and internet over cellular. A spare phone with no SIM works fine.

`wlan0` and `eth0` run simultaneously, so a laptop on the cable and a phone on VIZROCK both
reach the same brain.
The show path never needs internet; the Pi just has to let your phone and the Resolume
machine see each other. Make the Pi a self-contained access point:
```bash
sudo nmcli device wifi hotspot ssid VIZROCK password <choose-one> ifname wlan0
```
Then either **wire the Resolume machine to the Pi over ethernet** (recommended — OSC and
Art-Net run great over a cable; put both on one cheap switch) or have that machine join
the VIZROCK hotspot. Add its IP to `configs/show_config.json` → `outputs.resolume.hosts`. The rings
are on **ESP-NOW**, not WiFi, so they're unaffected by any of this.

> Ask THC: can you get a wired ethernet link (or a spare port) to their Resolume machine,
> and can they enable **OSC input** (Preferences → OSC, note the port)?

## Tests

```bash
./venv/bin/vizrock_test                      # python suites
extras/rpi_setup_scripts/test-setup-scripts.sh # setup scripts, system commands mocked
```

Logic only — no hardware is involved.

## OLED wiring (I2C, 128×64)

Buy a **0.96" SSD1306 I2C** module — 4 pins. Avoid 7-pin SPI boards; many 1.3" modules use the
SH1106 driver instead. Both `driver` (`ssd1306` / `sh1106`) and `address` are set in
`configs/show_config.json`, so either panel works.

`VCC→3V3 (pin 1) · GND→(pin 6) · SDA→GPIO2 (pin 3) · SCL→GPIO3 (pin 5)`.
Confirm it's seen: `i2cdetect -y 1` should show `3c`. If you don't wire one, the OLED
adapter just no-ops.

## Program the M-VAVE Chocolate (once, in the CubeSuite app)
Set the four switches to send **Note On** 60/61/62/63, then export the profile as `.fcp`.
The `show_config.json` trigger map binds: `60→arm_prev · 61→arm_next · 62→go · 63→blackout`.
Buy the plain Chocolate (or run the Plus in **wired USB mode**) — ignore its Bluetooth.

## Clip prep (so nothing stutters or goes silent)
Render to THC's exact board **W×H/fps** → convert to **DXV** in Resolume Alley (free) →
audio as **PCM 48k/16-bit** (not AAC) → verify audio survived → name `NN_name.mov` to
match scene ids.
