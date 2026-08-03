# VizRock-Brain

Python appliance on a Raspberry Pi. Takes MIDI footswitch triggers and fans a committed scene
out to Resolume (OSC), DMX (Art-Net), the wearable LED rings (USB serial → ESP-NOW), and a
pedalboard OLED. Serves its own control UI over websocket.

Workspace root is `../` — read `../CLAUDE.md` first for cross-repo contracts
(ring wire protocol, arm-and-GO model, venue networking).

## Layout

| File | Role |
|------|------|
| `brain.py` | `Brain` state machine, MIDI intake, dispatch, asyncio entrypoint |
| `adapters.py` | Output adapters over one interface + `build_adapters()` factory |
| `server.py` | aiohttp static serving + websocket |
| `config.json` | Outputs, MIDI input filters, trigger map, named DMX cues |
| `scenes.json` | The show — **rewritten at runtime by the UI** |
| `web/index.html` | Single-file UI, no build step |
| `setup/` | systemd unit + udev rules |

## Run

Python **3.10+** (PEP 604 annotations in `brain.py`).

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python3 brain.py          # UI at http://<host>:8080
```

Works on a dev laptop: with no OLED, no MIDI devices and nothing listening on the UDP ports,
every adapter degrades to a no-op and the web UI still drives the full state machine.

## Rules

- **Adapters never raise into the brain.** `_commit` wraps each `apply()` in try/except, but an
  adapter that throws on every scene spams the log and silently does nothing — handle your own
  errors and report them through `status()`.
- **Nothing blocks in the dispatch path.** `apply()` runs inline on the event loop during GO.
  Anything with a real connection owns a background thread and `apply()` only updates state —
  see `RingSerial`.
- **State changes happen on the asyncio loop only.** MIDI arrives on a rtmidi callback thread;
  `_on_midi` must keep hopping via `call_soon_threadsafe`. There are no locks and there
  shouldn't need to be.
- **Scene id `0` is Blackout** and is excluded from `self.order`. Anything that steps the
  setlist must keep skipping it.
- **`scenes.json` is not source of truth** — the UI overwrites it. Committed values are
  defaults for a fresh Pi.
- Adding a new output = one class with `apply()` + an entry in `_KINDS`. Don't special-case
  outputs inside `brain.py`.
- Adding a ring mode means editing `web/index.html` (`paintRing`) **and** both sketches in
  `../VizRock-Firmware`. `adapters.py` passes the mode string through untouched — there is no
  table here to update. See the wire protocol in `../CLAUDE.md`.

## Config notes

- `midi_inputs` are **substring** filters against port names (`["Chocolate", "FM3"]`); empty
  list means open everything.
- Triggers match `note` / `pc` / `cc`. Default map: `60→arm_prev · 61→arm_next · 62→go ·
  63→blackout`, plus PC `1`/`2` → `goto` scenes 2/3.
- DMX cues are named channel maps; an unknown cue name resolves to an all-zero frame, so a typo
  blacks out rather than crashing.
