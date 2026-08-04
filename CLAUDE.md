# VizRock-Brain

Python appliance on a Raspberry Pi. Takes MIDI footswitch triggers and fans a committed scene
out to Resolume (OSC), DMX (Art-Net), the wearable LED rings (USB serial → ESP-NOW), and a
pedalboard OLED. Serves its own control UI over websocket.

Workspace root is `../` — read `../CLAUDE.md` first for cross-repo contracts
(ring wire protocol, arm-and-GO model, venue networking).

## Layout

Standard Gener8 Python package shape: `show_brain/` package, `configs/` for JSON, `setup.py`
with a console-script entry point.

| Path | Role |
|------|------|
| `show_brain/show_brain.py` | `ShowBrain` — LIVE/ARMED state and dispatch |
| `show_brain/__main__.py` | `showbrain_run` entry point; wires everything together |
| `show_brain/managers/scene_library.py` | Scene table, setlist order, `scenes.json` persistence |
| `show_brain/managers/midi_interface.py` | MIDI port setup + trigger matching |
| `show_brain/outputs/` | One file per output + `build_outputs()` factory |
| `show_brain/interface/ui_server.py` | aiohttp static serving + websocket |
| `show_brain/interface/web/index.html` | Single-file UI, no build step |
| `show_brain/configurations/settings.py` | Singleton `show_settings` |
| `show_brain/constants/paths.py` | `Directories` / `Files` — all path resolution |
| `configs/show_config.json` | Outputs, MIDI input filters, trigger map, named DMX cues |
| `configs/scenes.json` | The show — **rewritten at runtime by the UI** |
| `extras/rpi_setup_scripts/` | systemd unit + udev rules |

## Run

Targets Python 3.10+ (`python_requires` in `setup.py`); Bookworm ships 3.11.

```bash
python3 -m venv venv && ./venv/bin/pip install -e .
./venv/bin/showbrain_run          # UI at http://<host>:8080
```

Works on a dev laptop: with no OLED, no MIDI devices and nothing listening on the UDP ports,
every output degrades to a no-op and the web UI still drives the full state machine.

## Rules

- **Outputs never raise into the brain.** `_commit` wraps each `apply()` in try/except, but an
  output that throws on every scene spams the log and silently does nothing — handle your own
  errors and report them through `status()`.
- **Nothing blocks in the dispatch path.** `apply()` runs inline on the event loop during GO.
  Anything with a real connection owns a background thread and `apply()` only updates state —
  see `outputs/ring_serial.py`.
- **State changes happen on the asyncio loop only.** MIDI arrives on a rtmidi callback thread;
  `__main__` hands `MidiInterface` a handler that hops via `call_soon_threadsafe`. There are
  no locks and there shouldn't need to be.
- **Scene id `0` is Blackout** and is excluded from `SceneLibrary.order`. Anything that steps
  the setlist must keep skipping it.
- **`configs/scenes.json` is not source of truth** — the UI overwrites it. Committed values
  are defaults for a fresh Pi.
- **Never hardcode a path.** Everything resolves through `constants/paths.py`.
- Adding a new output = one file in `outputs/` + an entry in `OUTPUT_KINDS`. Don't
  special-case outputs inside `show_brain.py`.
- Adding a ring mode means editing `interface/web/index.html` (`paintRing`) **and** both
  sketches in `../VizRock-Firmware`. `outputs/ring_serial.py` passes the mode string through
  untouched — there is no table here to update. See the wire protocol in `../CLAUDE.md`.

## Config notes

- `midi_inputs` are **substring** filters against port names (`["Chocolate", "FM3"]`); empty
  list means open everything.
- Triggers match `note` / `pc` / `cc`. Default map: `60→arm_prev · 61→arm_next · 62→go ·
  63→blackout`, plus PC `1`/`2` → `goto` scenes 2/3.
- DMX cues are named channel maps; an unknown cue name resolves to an all-zero frame, so a typo
  blacks out rather than crashing.
