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
- `show_brain/` — the package (`show_brain.py` state machine, `managers/`, `outputs/`,
  `interface/`, `configurations/`, `constants/`)
- `configs/show_config.json` — outputs, MIDI inputs, trigger map, DMX cues
- `configs/scenes.json` — the show (edited live from the UI, saved here)
- `extras/rpi_setup_scripts/` — udev rule + systemd unit
- `setup.py` — deps and the `showbrain_run` console script

## Install (Raspberry Pi OS Lite, Bookworm)

One command on a fresh flash — packages, venv, I2C, udev, mDNS, hotspot, systemd:

```bash
git clone https://github.com/garretthagen21/VizRock-Brain.git ~/show-brain
cd ~/show-brain && sudo extras/rpi_setup_scripts/install.sh <hotspot-password>
```

Idempotent, so re-run it after a `git pull`. Then open `http://show-brain.local:8080`.
Flash the SD card with Raspberry Pi Imager and preset the hostname to `show-brain`, plus
your WiFi and SSH key, so the only device-side step is the clone.

<details><summary>Manual steps, if you'd rather not run the script</summary>

Use **Raspberry Pi OS Lite** (not Desktop) on **Bookworm**. Trixie ships Python 3.13, and the
pinned `aiohttp` and `python-rtmidi` have no cp313 wheels — see `CLAUDE.md`.
```bash
sudo apt update && sudo apt install -y python3-venv libasound2-dev libjack-dev i2c-tools \
  avahi-daemon libnss-mdns          # mDNS: .local names, both directions
git clone https://github.com/garretthagen21/VizRock-Brain.git ~/show-brain && cd ~/show-brain
python3 -m venv venv && ./venv/bin/pip install -e .
sudo raspi-config nonint do_i2c 0          # enable I2C for the OLED
sudo cp extras/rpi_setup_scripts/99-showbrain.rules /etc/udev/rules.d/ && sudo udevadm control --reload
./venv/bin/showbrain_run                   # test run; open http://<pi>.local:8080
```
Clone to `~/show-brain` — the systemd unit hardcodes that path.

Boot as an appliance:
```bash
sudo cp extras/rpi_setup_scripts/show-brain.service /etc/systemd/system/
sudo systemctl enable --now show-brain
```
</details>

## Connecting at the venue

**Prefer a cable.** The UI binds `0.0.0.0:8080`, so the Pi answers on every interface at once —
ethernet, WiFi, hotspot — with nothing to configure or switch. A direct ethernet run from the
Pi to your laptop needs no DHCP server: both ends take link-local `169.254.x.x` addresses and
find each other by mDNS at `show-brain.local:8080`. One cheap switch puts the Pi, your laptop
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

Installs mDNS, gives the wired connection top priority, and creates a persistent **SHOWBRAIN**
hotspot that autoconnects on boot as the fallback. Nothing needs switching afterwards — the
cable wins when it's plugged in, the hotspot is there when it isn't, and the UI answers on
every interface either way.
The show path never needs internet; the Pi just has to let your phone and the Resolume
machine see each other. Make the Pi a self-contained access point:
```bash
sudo nmcli device wifi hotspot ssid SHOWBRAIN password <choose-one> ifname wlan0
```
Then either **wire the Resolume machine to the Pi over ethernet** (recommended — OSC and
Art-Net run great over a cable; put both on one cheap switch) or have that machine join
the SHOWBRAIN hotspot. Add its IP to `configs/show_config.json` → `outputs.resolume.hosts`. The rings
are on **ESP-NOW**, not WiFi, so they're unaffected by any of this.

> Ask THC: can you get a wired ethernet link (or a spare port) to their Resolume machine,
> and can they enable **OSC input** (Preferences → OSC, note the port)?

## OLED wiring (I2C SSD1306, 128×64)
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
