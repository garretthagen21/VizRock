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
- **Scene `1` is the main loop**, named by `meta.home_scene`, and is excluded from
  `SceneLibrary.order` — PREV/NEXT must never land on it. It is the default state you drop
  back into, not a step in the set.
- **`home` and `blackout` deliberately do not re-arm.** Bouncing out to the main loop has to
  leave whatever was queued still queued, or you lose your place mid-set.
- **Blackout is an action, not a scene.** `BLACKOUT_SCENE` is a constant dispatched directly —
  it needs no ring or dmx settings because they are zero by definition, and keeping it out of
  `scenes.json` leaves that file purely about the show.
- **Scene ids are set positions and get renumbered on reorder.** Dragging in EDIT renumbers
  scenes 2..N so the CUES grid always reads 01, 02, 03 — a grid you scan with a foot has to be
  in order. Each scene keeps its own `resolume.clip`, so the video travels with the scene and
  id/clip diverge on purpose. `Brain.reorder` remaps LIVE and ARMED so they follow the *scene*,
  not the number.
- **The generator matches on clip, never on id.** `vizrock_scenes` keys existing scenes by the
  clip they play, because ids drift after a reorder and keying on them would silently undo
  someone's running order.
- **The main loop is always the home scene, and always scene 1.** `meta.home_scene` exists,
  but if it ever names a scene that does not exist the library falls back to the lowest id
  rather than leaving HOME inert — a dead HOME button is the worst failure available, since it
  is the one thing you press to get out of trouble. Reordering never moves it.
- **The main loop is pinned, not listed.** In CUES it sits above the grid and is excluded from
  it; in EDIT it is not draggable. It is the default state, not a step in the set.
- **Reordering is desktop-only** (`hover:hover and pointer:fine`). Dragging with a finger
  fights scrolling, and a pedalboard is not where you rearrange a setlist.
- **Scene id and clip number are the same by convention, not by rule.** `vizrock_scenes`
  derives the clip from the filename number, so scene 3 is clip 3 — but `resolume.clip` is
  explicit per scene and the runtime never assumes identity. Two scenes may deliberately share
  one clip with different ring or DMX looks. Do not add code that infers one from the other.
- **`configs/scenes.json` is not source of truth** — the UI overwrites it. Committed values
  are defaults for a fresh Pi. This works because the install is editable (`pip install -e .`):
  `paths.py` resolves `REPO_DIR` to the clone, wherever it is, and the running user can write
  there. A non-editable install would silently break UI scene edits.
- **Never hardcode a path.** Everything resolves through `constants/paths.py`.
- **`install.sh` is the only setup path — nothing should need doing by hand.** Every setting we
  ever configured manually is now scripted: the wired profile, the direct-cable `vizrock-direct`
  profile, link-local, DHCP timeout, the hotspot, screen blanking, and config migration. If you
  find yourself running `nmcli` or editing JSON on the box, that is a bug in the script.
- **`vizrock_migrate` folds new keys from the examples into the live configs.** The live files
  are untracked so they survive updates — which also means a setting added upstream would never
  reach an existing box. Merging adds what is missing and **never** overwrites a tuned value.
- **The live configs are untracked; the `.example` files are the committed ones.** The UI
  rewrites `configs/*.json` at runtime, and a tracked file with local edits makes `git pull`
  fail — which would have broken self-update the first time anyone edited a scene.
  `paths.ensure_seeded()` copies the example on first read, so a fresh clone still works.
- **`broadcast` must schedule, not call.** `WebSocketResponse.send_str` is a coroutine;
  calling it from the synchronous `push_state` path only creates one. Every push after the
  initial snapshot silently vanished until this was fixed.
- **Gate every `:hover` behind `@media (hover:hover)`.** On touch, `:hover` latches after a
  tap, which made the transport buttons look stuck on. Pair each one with `:active`.
- **Boot dark with the main loop queued.** `Brain.boot()` comes up with blackout on and the
  restore target primed to the main loop. Powering on must never throw a visual at a screen
  nobody is ready for, but releasing blackout has to land somewhere rather than nothing.
- **Never reuse the word "live" for anything but the playing scene.** The connection indicator
  said `live` when it meant "websocket connected", which is exactly the overload that makes a
  glanceable UI unreadable. It says `connected` / `no brain`.
- **Blackout is a master mute, and nothing but blackout clears it.** You can load and change
  scenes underneath it — GO, MAIN, a cue tap all update LIVE — but `_commit` dispatches
  **nothing** while it is on, and releasing it reveals whatever ended up loaded. GO silently
  undoing a blackout someone put on deliberately would be the worst kind of surprise.
- **Blackout is a held toggle, not a one-way trip.** Turning it off restores whatever was
  playing, so killing the screen mid-song does not also lose your place. Committing any scene
  clears it. It lives in the header, deliberately away from the transport, because a stray tap
  next to GO would be expensive.
- **The transport is exactly the four pedal actions** — MAIN, PREV, NEXT, GO — in pedal order.
  Nothing else belongs in that bar; it is the one surface where muscle memory has to match.
- **The action is `home`, the label is MAIN.** Users see MAIN; the code, config and log keep
  `home`/`home_scene`. Do not rename the action.
- **Tapping a cue arms; it does not fire.** `ui.tap_fires` opts into firing straight from a
  tap and defaults **off**. A mis-tap that only changes what is queued costs nothing; one that
  fires a visual costs the song. `arm` is display-only and must never reach an output.
- **CUES density is per device, not a fixed count.** Roughly 8 big targets on the 5" panel and
  on a phone, everything at once on a laptop. A partly visible row is the only affordance
  saying there is more below — do not tidy it away.
- **One colour, one meaning. Never reuse one.**
  green `--live` = playing · amber `--armamber` = armed · purple `--home` = the main loop ·
  blue `--active` = interactive/addressable · orange `--warn` = the show title ·
  red = blackout. The main loop was briefly set to the same blue as `--active`, which made the
  LIVE dot, the ready pills and the main loop all look like the same thing.
- **Per-scene and global settings are separate screens, and each says its scope.** The
  inspector is headed `INSPECTOR · THIS SCENE ONLY`; outputs, cues, triggers, connect and
  software sit behind `⚙ GLOBAL SETTINGS`, headed `GLOBAL · APPLIES TO EVERY SCENE`. Mixing
  them invites someone editing a shared Resolume host believing it applies to one scene.
- **EDIT is master → detail.** The scene list and the inspector each scroll on their own; on
  a small screen tapping a scene swaps to the inspector and BACK returns. One long scrolling
  page made the scene table unreachable on the panel.
- **Only outputs with a real connection may say `ok`.** Fire-and-forget UDP says `ready` —
  addressable, not delivered — and the pill shows `sent` for ~1.4s after a cue actually goes
  out. A status that never changes tells you nothing, but neither should it claim delivery the
  protocol cannot confirm.
- **Three views: SHOW, CUES, EDIT.** SHOW is a heads-up display — glanceable, not a control
  surface. CUES is the live surface: a tappable grid of every scene, for the mounted
  touchscreen. EDIT is config. The status pills and transport are shared by SHOW and CUES and
  hidden in EDIT, because the transport is a live control and EDIT is not a live place.
- **The view wrappers must carry `flex:1`.** `.show` and `.cuegrid` declare `flex:1`, but that
  does nothing unless `#viewShow`/`#viewCues`/`#viewEdit` also grow — otherwise the page sizes
  to content and ends half way down the panel. This broke when the status bar and transport
  moved out of `viewShow`.
- **Three layouts, switched on shape not just width.** Portrait phone stacks LIVE over ON
  DECK. Short-and-wide (`max-height:560px` — the 5" 800x480 kiosk panel, or a phone on its
  side) keeps them side by side, compacts the chrome and **disables scrolling**: a HUD you
  have to scroll is not a HUD. Desktop is the default.
- **The narrow layout lets the page scroll.** The desktop shell is a fixed `100vh` with
  `overflow:hidden`, which puts the EDIT view out of reach on a phone. Below 860px the shell
  becomes `height:auto` and the transport sticks to the bottom so GO is always reachable.
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

## Optional kiosk

`extras/rpi_setup_scripts/setup-kiosk.sh` puts the UI on an attached screen via cage +
Chromium against `localhost`. It is **not** called by `install.sh` and touches no Python: the
screen is a browser client like any other. The unit uses `After=`/`Wants=` and never
`Requires=`, so the kiosk can fail without affecting the show. Keep it that way.

## Utilities

`utilities/system.py` reports the hostname and IPv4 addresses so the UI's CONNECT panel can
tell you where to point a phone without SSHing in. `local_addresses()` shells out to
`hostname -I` and **caches for 15s** — state is pushed on every ARM move, and forking a
process per button press would be daft. It returns `[]` rather than raising on any platform
without that flag.

## Setlist tooling

`vizrock_scenes <folder>` builds `configs/scenes.json` from clips named `NN_name.mov`. Two
rules it must keep: **nothing is written without `--write`**, and **merging preserves ring,
dmx and audio on existing scenes** — the file only drives name and clip number. Wiping tuned
cues on a regenerate would be worse than no tool at all.

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

- `midi_inputs` is a **substring** filter on ALSA port names, and defaults to `[]` — open
  everything. Naming a device you do not have is worse than naming nothing: the M-VAVE
  Chocolate reports as **`SINCO`**, so a filter of `["Chocolate"]` silently ignored it. Ports
  containing "through" are always skipped; that is ALSA's loopback, never a controller.
  Skipped ports are logged, so a filter that matches nothing is visible.
- Triggers match `note` / `pc` / `cc`. The M-VAVE Chocolate ships sending **Program Change
  0-3**, one message per press, left to right — confirmed on hardware. The map matches the
  pedal rather than requiring CubeSuite: `0→home · 1→arm_prev · 2→arm_next · 3→go`, i.e.
  **HOME · PREV · NEXT · GO** left to right. The UI transport uses the same order — there
  must be nothing to translate between the pedal and the screen.
- **`midi_inputs` names `SINCO` deliberately.** An FM3 also sends Program Change, so an open
  filter would let its preset changes fire show cues.
- **Resolume OSC is on 38200, not the default 7000.** Logic Pro squats on 7000 *and* 7001, and
  when Resolume cannot bind its OSC port it fails **silently** — the monitor just stays empty,
  which looks exactly like a network fault. 38200 has no registered service, is clear of the
  7000-9000 audio neighbourhood, and sits below macOS's 49152 ephemeral range so nothing can
  claim it at random. If OSC ever looks dead, check who owns the port (`lsof -nP -iUDP:38200`)
  before suspecting the network.
- DMX cues are named channel maps; an unknown cue name resolves to an all-zero frame, so a typo
  blacks out rather than crashing.
