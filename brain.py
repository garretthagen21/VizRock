#!/usr/bin/env python3
"""
Show Brain — core state machine + dispatch.

The brain holds two pieces of state: LIVE (what's currently playing) and ARMED
(what GO will fire next). Triggers move ARMED; GO commits ARMED -> LIVE and fans
the scene out to every output adapter. Nothing is a hard dependency: a missing or
broken output is a logged warning, never a crash, and never adds latency to the
live outputs.

Run:  python3 brain.py
"""
import asyncio
import json
import logging
import signal
from pathlib import Path

import mido  # python-rtmidi backend

from adapters import build_adapters
from server import UIServer

log = logging.getLogger("brain")

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
SCENES_PATH = HERE / "scenes.json"


class Brain:
    def __init__(self, config: dict, scenes: dict):
        self.config = config
        self.load_scenes(scenes)
        self.live = None                       # currently-playing scene id
        self.armed = self.order[0] if self.order else None
        self.adapters = []                     # output + state-subscriber modules
        self.loop = None
        self.last_event = "armed · waiting for trigger"

    # ---- scene table ------------------------------------------------------
    def load_scenes(self, scenes: dict):
        self.scenes = {s["id"]: s for s in scenes["scenes"]}
        # setlist order excludes the blackout scene (id 0) from stepping
        self.order = [s["id"] for s in scenes["scenes"] if s["id"] != 0]
        self.meta = scenes.get("meta", {})

    def save_scenes(self):
        data = {"meta": self.meta,
                "scenes": [self.scenes[i] for i in sorted(self.scenes)]}
        SCENES_PATH.write_text(json.dumps(data, indent=2))
        log.info("scenes.json saved")

    # ---- actions (called from MIDI or the UI) -----------------------------
    def handle(self, action: str, scene: int = None):
        if action == "arm_next":  self._arm_step(+1)
        elif action == "arm_prev": self._arm_step(-1)
        elif action == "go":       self._commit(self.armed)
        elif action == "goto":     self._commit(scene, rearm=True)
        elif action == "blackout": self._commit(0, rearm=False)
        else: log.warning("unknown action: %s", action)

    def _arm_step(self, d):
        if not self.order:
            return
        i = self.order.index(self.armed) if self.armed in self.order else 0
        self.armed = self.order[max(0, min(len(self.order) - 1, i + d))]
        self.last_event = f"armed → {self._label(self.armed)}"
        self._push_state()                     # ARM changes are display-only

    def _commit(self, scene_id, rearm=True):
        if scene_id not in self.scenes:
            log.warning("commit to missing scene %s", scene_id)
            return
        self.live = scene_id
        scene = self.scenes[scene_id]
        # fan out to outputs, each isolated so one failure can't touch the rest
        for a in self.adapters:
            try:
                a.apply(scene)
            except Exception as e:
                log.warning("output %s failed: %s", a.name, e)
        # auto-arm the next scene so a linear set is just GO, GO, GO
        if rearm and scene_id in self.order:
            i = self.order.index(scene_id)
            self.armed = self.order[min(len(self.order) - 1, i + 1)]
        self.last_event = f"LIVE → {self._label(scene_id)} · dispatched"
        self._push_state()

    # ---- state broadcast --------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "type": "state",
            "live": self.live,
            "armed": self.armed,
            "last_event": self.last_event,
            "outputs": {a.name: a.status() for a in self.adapters},
            "scenes": [self.scenes[i] for i in sorted(self.scenes)],
            "meta": self.meta,
        }

    def _push_state(self):
        snap = self.snapshot()
        for a in self.adapters:                # e.g. the OLED subscribes here
            try:
                a.on_state(snap)
            except Exception as e:
                log.warning("state-sub %s failed: %s", a.name, e)
        if self.ui:
            self.ui.broadcast(snap)

    def _label(self, sid):
        s = self.scenes.get(sid)
        return f"{sid:02d} {s['name']}" if s else str(sid)

    # ---- MIDI intake ------------------------------------------------------
    def match_trigger(self, msg) -> tuple | None:
        """Return (action, scene) for an incoming mido message, or None."""
        for t in self.config["triggers"]:
            m = t["midi"]
            k = m["kind"]
            if k == "note" and msg.type == "note_on" and msg.note == m["note"] and msg.velocity > 0:
                return t["do"], t.get("scene")
            if k == "pc" and msg.type == "program_change" and msg.program == m["program"]:
                return t["do"], t.get("scene")
            if k == "cc" and msg.type == "control_change" and msg.control == m["cc"] \
               and msg.value == m.get("value", msg.value):
                return t["do"], t.get("scene")
        return None

    def _on_midi(self, msg, source=""):
        hit = self.match_trigger(msg)
        if not hit:
            return
        action, scene = hit
        log.info("MIDI %s (%s) → %s", msg, source, action)
        # hop from the MIDI thread onto the asyncio loop before touching state
        self.loop.call_soon_threadsafe(self.handle, action, scene)


async def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = json.loads(CONFIG_PATH.read_text())
    scenes = json.loads(SCENES_PATH.read_text())

    brain = Brain(config, scenes)
    brain.loop = asyncio.get_running_loop()
    brain.adapters = build_adapters(config["outputs"])
    brain.ui = UIServer(brain)
    await brain.ui.start(config.get("ui", {}).get("port", 8080))

    # open every configured MIDI input; route all of them into the brain
    open_ports = []
    wanted = config.get("midi_inputs", [])      # substrings, e.g. ["Chocolate", "FM3"]
    for name in mido.get_input_names():
        if not wanted or any(w.lower() in name.lower() for w in wanted):
            try:
                p = mido.open_input(name, callback=lambda m, n=name: brain._on_midi(m, n))
                open_ports.append(p)
                log.info("listening on MIDI: %s", name)
            except Exception as e:
                log.warning("could not open %s: %s", name, e)
    if not open_ports:
        log.warning("no MIDI inputs open — UI still works, footswitches won't")

    brain._push_state()                          # prime the OLED + any UI clients

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        brain.loop.add_signal_handler(sig, stop.set)
    log.info("show brain up. LIVE=%s ARMED=%s", brain.live, brain.armed)
    await stop.wait()

    for p in open_ports:
        p.close()
    for a in brain.adapters:
        a.close()


if __name__ == "__main__":
    asyncio.run(main())
