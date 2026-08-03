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

## Files
- `brain.py` — state machine, MIDI intake, dispatch
- `adapters.py` — OSC / Art-Net / ring-serial / OLED outputs (common interface)
- `server.py` — serves `web/` + websocket for live state and edits
- `config.json` — outputs, MIDI inputs, trigger map, DMX cues
- `scenes.json` — the show (edited live from the UI, saved here)
- `web/index.html` — SHOW (LIVE|ARMED) + EDIT UI
- `setup/` — udev rule + systemd unit

## Install (Raspberry Pi OS Lite, Bookworm)
Needs **Python 3.10+** — Bookworm ships 3.11.
```bash
sudo apt update && sudo apt install -y python3-venv libasound2-dev libjack-dev i2c-tools
git clone https://github.com/garretthagen21/VizRock-Brain.git ~/show-brain && cd ~/show-brain
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
sudo raspi-config nonint do_i2c 0          # enable I2C for the OLED
sudo cp setup/99-showbrain.rules /etc/udev/rules.d/ && sudo udevadm control --reload
./venv/bin/python3 brain.py                # test run; open http://<pi>.local:8080
```
Clone to `~/show-brain` — the systemd unit and udev rule hardcode that path.

Boot as an appliance:
```bash
sudo cp setup/show-brain.service /etc/systemd/system/
sudo systemctl enable --now show-brain
```

## No WiFi at the venue — the Pi is the network
The show path never needs internet; the Pi just has to let your phone and the Resolume
machine see each other. Make the Pi a self-contained access point:
```bash
sudo nmcli device wifi hotspot ssid SHOWBRAIN password <choose-one> ifname wlan0
```
Then either **wire the Resolume machine to the Pi over ethernet** (recommended — OSC and
Art-Net run great over a cable; put both on one cheap switch) or have that machine join
the SHOWBRAIN hotspot. Set its IP in `config.json` → `outputs.resolume.host`. The rings
are on **ESP-NOW**, not WiFi, so they're unaffected by any of this.

> Ask THC: can you get a wired ethernet link (or a spare port) to their Resolume machine,
> and can they enable **OSC input** (Preferences → OSC, note the port)?

## OLED wiring (I2C SSD1306, 128×64)
`VCC→3V3 (pin 1) · GND→(pin 6) · SDA→GPIO2 (pin 3) · SCL→GPIO3 (pin 5)`.
Confirm it's seen: `i2cdetect -y 1` should show `3c`. If you don't wire one, the OLED
adapter just no-ops.

## Program the M-VAVE Chocolate (once, in the CubeSuite app)
Set the four switches to send **Note On** 60/61/62/63, then export the profile as `.fcp`.
The `config.json` trigger map binds: `60→arm_prev · 61→arm_next · 62→go · 63→blackout`.
Buy the plain Chocolate (or run the Plus in **wired USB mode**) — ignore its Bluetooth.

## Clip prep (so nothing stutters or goes silent)
Render to THC's exact board **W×H/fps** → convert to **DXV** in Resolume Alley (free) →
audio as **PCM 48k/16-bit** (not AAC) → verify audio survived → name `NN_name.mov` to
match scene ids.
