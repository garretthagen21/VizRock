# VizRock

Python appliance on a Raspberry Pi. Takes MIDI footswitch triggers and fans a committed scene
out to Resolume (OSC), DMX (Art-Net), the wearable LED rings (USB serial → ESP-NOW), and a
pedalboard OLED. Serves its own control UI over websocket.

Workspace root is `../` — read `../CLAUDE.md` first for cross-repo contracts
(ring wire protocol, arm-and-GO model, venue networking).

## Layout

Standard Gener8 Python package shape: `vizrock/` package, `configs/` for JSON, `setup.py`
with a console-script entry point.

| Path | Role |
|------|------|
| `vizrock/brain.py` | `Brain` — LIVE/ARMED state and dispatch |
| `vizrock/__main__.py` | `vizrock_run` entry point; wires everything together |
| `vizrock/managers/scene_library.py` | Scene table, setlist order, `scenes.json` persistence |
| `vizrock/managers/midi_interface.py` | MIDI port setup + trigger matching |
| `vizrock/managers/updater.py` | Reachability polling, `git pull`, self-restart |
| `vizrock/outputs/` | One file per output + `build_outputs()` factory |
| `vizrock/interface/ui_server.py` | aiohttp static serving + websocket |
| `vizrock/interface/web/index.html` | Single-file UI, no build step |
| `vizrock/configurations/settings.py` | Singleton `vizrock_settings` |
| `vizrock/constants/paths.py` | `Directories` / `Files` — all path resolution |
| `configs/show_config.json` | Outputs, MIDI input filters, trigger map, named DMX cues |
| `configs/scenes.json` | The show — **rewritten at runtime by the UI** |
| `extras/rpi_setup_scripts/` | `install.sh` (one-shot), network setup, systemd unit, udev rules |

## Run

Targets **Raspberry Pi OS Lite, Bookworm** (Python 3.11). Lite, not Desktop — the Pi is
headless and the UI is served over HTTP.

**Bookworm is the verified target. Trixie is untested.** Trixie ships Python 3.13:
`aiohttp` has cp313 wheels from 3.14 onward, but **`python-rtmidi` has none at any version**,
so on Trixie it must compile from source. `install.sh` installs `build-essential` and
`python3-dev` so that build can at least be attempted. Dependencies are lower bounds rather
than exact pins so pip can pick a prebuilt wheel wherever one exists.

```bash
python3 -m venv venv && ./venv/bin/pip install -e .
./venv/bin/vizrock_run          # UI at http://<host>:8080
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
  are defaults for a fresh Pi. This works because the install is editable (`pip install -e .`):
  `paths.py` resolves `REPO_DIR` to the clone, wherever it is, and the running user can write
  there. A non-editable install would silently break UI scene edits.
- **Never hardcode a path.** Everything resolves through `constants/paths.py`.
- **The UI ships no external assets.** No CDN fonts, scripts or styles — the venue has no
  internet, and a render-blocking fetch delays first paint until it times out. Everything
  `index.html` needs must be inline or served from `interface/web/`.
- **Outputs validate their own config in `__init__`.** The factory turns a raise into a
  rejection, and a live config edit is persisted only if the output actually came up — so
  validation is what stops a bad edit reaching disk. Python won't do it for you: `list('abc')`
  succeeds and `self.port = 'nope'` is silently accepted.
- **Never resolve a hostname in the dispatch path.** `ResolumeOsc` resolves on a background
  thread and `apply()` uses the cache; a blocking mDNS lookup during GO would stall the cue.
- **Debounce anything that writes `scenes.json`.** It lands on the Pi's SD card; a slider
  firing per pixel would hammer it.
- **Only outputs with a real connection may report `ok`.** Fire-and-forget UDP (Resolume,
  DMX) reports `sending` — it means the packet left, not that anything received it. Don't
  let the UI imply a confirmation the protocol can't give.
- **Updating restarts the process, it does not reload.** `Updater` pulls, optionally
  reinstalls, then raises SIGTERM to itself; systemd's `Restart=always` brings it back on the
  new code. That is why no sudo is needed. It refuses when offline, when already running, or
  when the requested sha is not the one the UI last displayed — so a queued click cannot apply
  something the operator never saw.
- Adding a new output = one file in `outputs/` + an entry in `OUTPUT_KINDS`. Don't
  special-case outputs inside `brain.py`.
- Adding a ring mode means editing `interface/web/index.html` — **both** `RING_MODES` and
  `paintRing` — **and** both sketches in `../VizRock-Firmware`. `outputs/ring_serial.py` passes the mode string through
  untouched — there is no table here to update. See the wire protocol in `../CLAUDE.md`.

## Tests

```bash
./venv/bin/vizrock_test                      # python suites
extras/rpi_setup_scripts/test-setup-scripts.sh # setup scripts, system commands mocked
```

Run both after any change — the suites are cheap and a later edit silently breaking an earlier
one is the failure mode they exist to catch. `test_config_edit` writes `show_config.json` and
restores it; if it is interrupted, check `git diff configs/`.

They cover logic, not hardware: no MIDI device, ring, OLED or Pi is involved anywhere.

## Config notes

- `midi_inputs` are **substring** filters against port names (`["Chocolate", "FM3"]`); empty
  list means open everything.
- Triggers match `note` / `pc` / `cc`. Default map: `60→arm_prev · 61→arm_next · 62→go ·
  63→blackout`, plus PC `1`/`2` → `goto` scenes 2/3.
- DMX cues are named channel maps; an unknown cue name resolves to an all-zero frame, so a typo
  blacks out rather than crashing.
