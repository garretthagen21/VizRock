#!/usr/bin/python3
#
# @file    vizrock.py
#
# @brief   Core state machine: LIVE, ARMED, and dispatch to every output
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging
import threading
import time

from vizrock.configurations.settings import vizrock_settings
from vizrock.managers.scene_library import BLACKOUT_SCENE, SceneLibrary
from vizrock.outputs import build_output
import vizrock.utilities.system as vizrock_system
from vizrock.managers.updater import Updater

logger = logging.getLogger(__name__)


class Brain:
    """
    Holds two pieces of state: LIVE (what is currently playing) and ARMED (what GO
    will fire next). Triggers move ARMED; GO commits ARMED to LIVE and fans the scene
    out to every output. Nothing is a hard dependency: a broken output is a logged
    warning, never a crash, and never adds latency to the live outputs.
    """

    def __init__(self):
        self.scene_library = SceneLibrary()
        self.live = None
        self.armed = self.scene_library.order[0] if self.scene_library.order else None
        self.outputs = []
        self.ui_server = None
        self.updater = None
        self.blackout = False
        self._restore_to = None          # what was live when blackout went on
        self.lights_off = False          # lights muted on their own, without blackout
        self._burst_until = 0.0          # strobe burst expiry, monotonic
        self._burst_timer = None
        self.last_event = 'armed · waiting for trigger'

    # MARK: - Actions (called from MIDI or the UI)
    def handle(self, action, scene=None):
        if action == 'arm_next':
            self._arm_step(+1)
        elif action == 'arm_prev':
            self._arm_step(-1)
        elif action == 'arm':
            self._arm(scene)
        elif action == 'go':
            self._commit(self.armed)
        elif action == 'goto':
            self._commit(scene, rearm=True)
        elif action == 'next_main':
            target = self.scene_library.next_main(self.live)
            if target is None:
                # a dead button is honest; jumping to an arbitrary clip is not
                logger.warning('no scene is marked main, so there is nowhere to go')
                self.last_event = 'no main scene is set'
                self.push_state()
            else:
                # like blackout, deliberately does not re-arm: bouncing out to a
                # looping visual must leave whatever you had queued still queued
                self._commit(target, rearm=False)
        elif action == 'restart_scene':
            if self.live is None:
                logger.warning('nothing is live, so there is nothing to restart')
            else:
                self._commit(self.live, rearm=False)
        elif action == 'toggle_lights':
            self._toggle_lights()
        elif action == 'light_burst':
            self._light_burst()
        elif action == 'blackout':
            self._toggle_blackout()
        else:
            logger.warning('unknown action: %s', action)

    def boot(self):
        """
        Come up dark with the main loop queued.

        Powering on should never throw a visual at a screen nobody is ready for — but
        releasing blackout should land on the main loop rather than nothing, so the
        restore target is primed rather than left empty. Call once outputs exist.
        """
        first_main = self.scene_library.next_main(0)
        if first_main is None and self.scene_library.order:
            first_main = self.scene_library.order[0]
        self.blackout = True
        self._restore_to = first_main
        # LIVE shows the scene so you can see what you will get back; the outputs get
        # all-off, so nothing actually reaches the screen until blackout is released
        self.live = first_main
        self._dispatch(BLACKOUT_SCENE)
        self.last_event = 'booted blacked out · main loaded'
        logger.info('booted blacked out with main scene %s loaded', first_main)

    def snapshot(self):
        return {
            'type': 'state',
            'live': self.live,
            'armed': self.armed,
            'last_event': self.last_event,
            'outputs': {output.name: output.status() for output in self.outputs},
            'addresses': {output.name: output.address_label() for output in self.outputs},
            'output_config': vizrock_settings.outputs,
            'tap_fires': vizrock_settings.tap_fires,
            'blackout': self.blackout,
            'lights_off': self.lights_off,
            'burst_active': self._burst_until > time.monotonic(),
            'mains': self.scene_library.mains,
            'update': self.updater.snapshot() if self.updater else None,
            'network': {'hostname': vizrock_system.hostname(),
                        'addresses': vizrock_system.local_addresses()},
            'scenes': self.scene_library.sorted_scenes(),
            'meta': self.scene_library.meta,
        }

    def push_state(self):
        snapshot = self.snapshot()
        for output in self.outputs:
            try:
                output.on_state(snapshot)
            except Exception as error:
                logger.warning('state-sub %s failed: %s', output.name, error)
        if self.ui_server:
            self.ui_server.broadcast(snapshot)

    def reorder(self, ordered_ids):
        """Renumber the setlist, keeping LIVE and ARMED on the same scenes."""
        mapping = self.scene_library.reorder(ordered_ids)
        self.live = mapping.get(self.live, self.live)
        self.armed = mapping.get(self.armed, self.armed)
        if self.armed not in self.scene_library.scenes:
            self.armed = self.scene_library.order[0] if self.scene_library.order else None
        self.last_event = 'setlist reordered'
        self.push_state()

    def apply_output_config(self, name, spec):
        """
        Rebuild before persisting: a spec that cannot come up is rolled back and
        never reaches disk, so a bad edit can't also break the next boot.
        """
        previous = dict(vizrock_settings.outputs.get(name, {}))
        vizrock_settings.update_output(name, spec)
        if self.replace_output(name):
            vizrock_settings.save()
            return True
        logger.warning('config for %s rejected, rolling back', name)
        vizrock_settings.outputs[name] = previous
        self.replace_output(name)
        return False

    def replace_output(self, name):
        """
        Rebuild one output from current settings and swap it in, so a config edit
        takes effect without a restart. Returns False if the replacement would not
        come up, leaving the old one closed and removed.
        """
        replacement = build_output(name, vizrock_settings.outputs.get(name, {}))
        existing = next((i for i, o in enumerate(self.outputs) if o.name == name), None)
        if existing is not None:
            try:
                self.outputs[existing].close()
            except Exception as error:
                logger.warning('closing %s failed: %s', name, error)
            self.outputs.pop(existing)
        if replacement:
            self.outputs.insert(existing if existing is not None else len(self.outputs), replacement)
            # a new output starts blank — bring it up to whatever is already on stage
            if self.live in self.scene_library.scenes:
                try:
                    replacement.apply(self.scene_library.scenes[self.live])
                except Exception as error:
                    logger.warning('output %s failed: %s', name, error)
        self.push_state()
        return replacement is not None

    # MARK: - Private
    def _toggle_blackout(self):
        """
        Blackout is a held state, not a one-way trip. Turning it off puts back
        whatever was playing, so killing the screen mid-song does not also lose your
        place. If nothing was live, fall back to the main loop rather than staying
        dark — a button that appears to do nothing is worse than one that overshoots.
        """
        if not self.blackout:
            self._restore_to = self.live
            self.blackout = True
            logger.info('LIVE -> blackout (all outputs off, will restore %s)', self._restore_to)
            self._dispatch(BLACKOUT_SCENE)
            self.live = None
            self.last_event = 'blackout · press again to restore'
            self.push_state()
            return

        self.blackout = False
        target = self._restore_to if self._restore_to in self.scene_library.scenes else self.live
        if target not in self.scene_library.scenes:
            target = self.scene_library.next_main(0)
        self._restore_to = None
        if target in self.scene_library.scenes:
            logger.info('blackout off -> restoring %s', self.scene_library.label(target))
            self._commit(target, rearm=False)
        else:
            self.last_event = 'blackout off'
            self.push_state()

    def _arm(self, scene_id):
        """Queue a specific scene. Display-only, exactly like arm_prev/arm_next."""
        if scene_id not in self.scene_library.scenes:
            logger.warning('arm to missing scene %s', scene_id)
            return
        self.armed = scene_id
        self.last_event = f'armed → {self.scene_library.label(scene_id)}'
        self.push_state()

    def _toggle_lights(self):
        """Mute the lights on their own. Narrower than blackout, which mutes everything."""
        self.lights_off = not self.lights_off
        self.last_event = 'lights off' if self.lights_off else 'lights on'
        logger.info(self.last_event)
        self._render()
        self.push_state()

    def _burst_spec(self):
        """Global burst settings with the live scene's override folded in."""
        scene = self.scene_library.scenes.get(self.live) or {}
        return {**vizrock_settings.burst, **(scene.get('burst') or {})}

    def _light_burst(self):
        """
        Make the lights pop for a few seconds, then revert to the scene.

        Strobe is only the default — a scene can override the mode, speed, brightness
        or duration. Hue never changes, so a burst alters how the lights move rather
        than what colour the stage is.

        RingSerial re-sends the last payload every ~250ms and holds no timer of its
        own, so the brain has to push a fresh payload when the burst ends. The timer
        runs on its own thread — nothing here may block the dispatch path.
        """
        seconds = float(self._burst_spec().get('seconds', 5))
        self._burst_until = time.monotonic() + seconds
        if self._burst_timer:
            self._burst_timer.cancel()
        self._burst_timer = threading.Timer(seconds, self._end_burst)
        self._burst_timer.daemon = True
        self._burst_timer.start()
        self.last_event = f"{self._burst_spec().get('mode', 'strobe')} burst · {seconds:g}s"
        self._render()
        self.push_state()

    def _end_burst(self):
        self._burst_until = 0.0
        self._render()
        self.push_state()

    def _with_light_overrides(self, scene):
        """
        Apply the light mutes and the burst to a scene's ring block.

        Precedence is blackout > lights off > burst > the scene, so an explicit mute
        always outranks a momentary effect. Blackout is handled a level up in
        `_render`, because it silences every output rather than only the lights.
        """
        ring = dict(scene.get('ring') or {'mode': 'off'})
        if self.lights_off:
            ring['mode'] = 'off'
        elif self._burst_until > time.monotonic():
            # the burst changes how the lights move, never what colour they are, so
            # hue is pointedly not taken from the spec
            burst = self._burst_spec()
            ring['mode'] = burst.get('mode', 'strobe')
            for key in ('speed', 'bright'):
                if key in burst:
                    ring[key] = burst[key]
        return {**scene, 'ring': ring}

    def _render(self):
        """Push current state to the outputs, honouring every mute in precedence order."""
        if self.blackout:
            self._dispatch(BLACKOUT_SCENE)
            return
        scene = self.scene_library.scenes.get(self.live)
        if scene is not None:
            self._dispatch(self._with_light_overrides(scene))

    def _dispatch(self, scene):
        """Fan a scene out to every output, each isolated so one failure cannot spread."""
        for output in self.outputs:
            try:
                output.apply(scene)
            except Exception as error:
                logger.warning('output %s failed: %s', output.name, error)

    def _arm_step(self, delta):
        stepped = self.scene_library.step_from(self.armed, delta)
        if stepped is None:
            return
        self.armed = stepped
        self.last_event = f'armed → {self.scene_library.label(self.armed)}'
        self.push_state()

    def _commit(self, scene_id, rearm=True):
        if scene_id not in self.scene_library.scenes:
            logger.warning('commit to missing scene %s', scene_id)
            return
        self.live = scene_id
        scene = self.scene_library.scenes[scene_id]
        # say what was actually targeted — "which clip did it fire?" is the first
        # question when visuals look wrong, and the action alone does not answer it
        resolume = scene.get('resolume') or {}
        target = 'clear' if resolume.get('clear') else \
            f"layer {resolume.get('layer')} clip {resolume.get('clip')}"
        logger.info('LIVE -> %s  (resolume: %s, ring: %s)%s',
                    self.scene_library.label(scene_id), target,
                    (scene.get('ring') or {}).get('mode', 'off'),
                    ' [held dark]' if self.blackout else '')
        if self.blackout:
            # Blackout is a master mute: you can load and change scenes underneath it,
            # but nothing reaches an output until it is released. GO must not silently
            # undo a blackout someone put on deliberately.
            self._restore_to = scene_id
        else:
            self._render()
        # auto-arm the next scene so a linear set is just GO, GO, GO
        if rearm and scene_id in self.scene_library.order:
            self.armed = self.scene_library.step_from(scene_id, +1)
        # "dispatched" while blacked out sends you hunting for a broken output, which
        # is exactly the wrong place to look — say which one it was.
        self.last_event = f'LIVE → {self.scene_library.label(scene_id)} · ' + \
            ('HELD DARK · blackout is on' if self.blackout else 'dispatched')
        self.push_state()
