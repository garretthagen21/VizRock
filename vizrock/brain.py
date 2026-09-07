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
        self.loop = None                 # set by __main__; timers hop back onto it
        self.ui_server = None
        self.updater = None
        # Blackout is the panic control and kills everything. Lights are a separate
        # switch, because "rings off, visuals running" is a real ask and the reverse
        # never is. Both are pure output mutes: LIVE stays set throughout, so
        # releasing either reveals the scene rather than restoring a remembered one.
        self.blackout = False
        self.lights_off = False
        self.color_index = None          # None = the scene's own hue
        self._burst_until = 0.0          # light burst expiry, monotonic
        self._burst_timer = None
        self._light_step = 0             # position in a scene's looping light sequence
        self._light_timer = None
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
        elif action == 'cycle_color':
            self._cycle_color()
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
        # LIVE shows the scene so you can see what you will get back; every output is
        # muted, so nothing actually reaches the stage until blackout is released
        self.live = first_main
        self._render()
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
            'color_index': self.color_index,
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
                    replacement.apply(self._effective_scene())
                except Exception as error:
                    logger.warning('output %s failed: %s', name, error)
        self.push_state()
        return replacement is not None

    # MARK: - Private
    def _toggle_blackout(self):
        """
        The panic control: every output off, held until pressed again.

        A pure mute — LIVE keeps pointing at whatever is loaded, so releasing it
        reveals the scene instead of the brain having to remember and restore one.
        """
        self.blackout = not self.blackout
        self.last_event = 'blackout · press again to restore' if self.blackout else 'blackout off'
        logger.info(self.last_event)
        self._render()
        self.push_state()

    def _toggle_lights(self):
        """Mute the lights alone, leaving the visuals running."""
        self.lights_off = not self.lights_off
        self.last_event = 'lights off' if self.lights_off else 'lights on'
        logger.info(self.last_event)
        self._render()
        self.push_state()

    def _cycle_color(self):
        """
        Step the light colour through the palette, and back to the scene's own hue.

        The scene's colour is one of the stops rather than something you can only
        get back to by cycling all the way round — after fiddling mid-set you need a
        way home that does not depend on counting presses.
        """
        palette = vizrock_settings.palette
        if not palette:
            return
        if self.color_index is None:
            self.color_index = 0
        elif self.color_index + 1 >= len(palette):
            self.color_index = None
        else:
            self.color_index += 1
        hue = 'scene' if self.color_index is None else palette[self.color_index]
        self.last_event = f'light colour · {hue}'
        self._render()
        self.push_state()

    def _arm(self, scene_id):
        """Queue a specific scene. Display-only, exactly like arm_prev/arm_next."""
        if scene_id not in self.scene_library.scenes:
            logger.warning('arm to missing scene %s', scene_id)
            return
        self.armed = scene_id
        self.last_event = f'armed → {self.scene_library.label(scene_id)}'
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
        self._burst_timer = threading.Timer(seconds, lambda: self._from_thread(self._end_burst))
        self._burst_timer.daemon = True
        self._burst_timer.start()
        self.last_event = f"{self._burst_spec().get('mode', 'strobe')} burst · {seconds:g}s"
        self._render()
        self.push_state()

    def _from_thread(self, function):
        """
        Hop a timer callback back onto the asyncio loop before it touches state.

        `UiServer.broadcast` looks up the running loop and gives up if there isn't
        one, so a push from a Timer thread would be silently dropped — the UI would
        never learn the burst ended.
        """
        if self.loop is not None:
            self.loop.call_soon_threadsafe(function)
        else:
            function()                    # tests and dev runs without a loop

    def _light_summary(self, scene):
        """How the lights read in a log line, across every peripheral."""
        parts = []
        for name, steps in self._light_configs(scene).items():
            modes = '/'.join(s.get('mode', 'off') for s in steps)
            parts.append(modes if name == 'default' else f'{name}:{modes}')
        return ' '.join(parts) or 'off'

    def _light_configs(self, scene):
        """
        A scene's lighting as {peripheral name: [steps]}.

        Lights are keyed by peripheral — `default`, `CabA`, `CabB` — so one scene can
        light two stacks differently. Each entry is a single dict or a list of steps
        that loops. `default` covers every peripheral without its own entry.
        """
        lights = scene.get('lights')
        if not isinstance(lights, dict) or not lights:
            return {'default': [{'mode': 'off'}]}
        return {name: self._as_steps(value) for name, value in lights.items()}

    @staticmethod
    def _as_steps(value):
        if isinstance(value, list):
            steps = [s for s in value if isinstance(s, dict)]
            return steps or [{'mode': 'off'}]
        return [value if isinstance(value, dict) else {'mode': 'off'}]

    def _default_config_name(self, configs):
        """`default` if present, otherwise whichever entry was written first."""
        return 'default' if 'default' in configs else next(iter(configs))

    def _light_steps(self, scene):
        """The default peripheral's steps — what drives the loop timing."""
        configs = self._light_configs(scene)
        return configs[self._default_config_name(configs)]

    def _restart_light_loop(self):
        """Back to the first step and re-time. Called whenever LIVE changes."""
        if self._light_timer:
            self._light_timer.cancel()
            self._light_timer = None
        self._light_step = 0
        self._schedule_light_step()

    def _schedule_light_step(self):
        scene = self.scene_library.scenes.get(self.live) or {}
        steps = self._light_steps(scene)
        if len(steps) < 2:
            return                        # nothing to cycle through
        step = steps[self._light_step % len(steps)]
        seconds = float(step.get('seconds', vizrock_settings.light_step_seconds) or 0)
        if seconds <= 0:
            return                        # 0 means hold here rather than advance
        self._light_timer = threading.Timer(
            seconds, lambda: self._from_thread(self._advance_light_step))
        self._light_timer.daemon = True
        self._light_timer.start()

    def _advance_light_step(self):
        steps = self._light_steps(self.scene_library.scenes.get(self.live) or {})
        self._light_step = (self._light_step + 1) % len(steps)
        self._render()
        self.push_state()
        self._schedule_light_step()

    def _end_burst(self):
        self._burst_until = 0.0
        self._render()
        self.push_state()

    def _lights_for(self, scene):
        """
        Resolve a scene to {group number: light dict}, one entry per configured
        peripheral, with the colour override and any burst applied.

        Every group in `light_groups` gets a line, falling back to the default
        config. Nodes match their group exactly, so no node is ever addressed twice
        in a tick and none is left unaddressed.
        """
        configs = self._light_configs(scene)
        fallback = configs[self._default_config_name(configs)]
        resolved = {}
        for name, group in vizrock_settings.light_groups.items():
            resolved[group] = self._one_light(configs.get(name, fallback))
        return resolved

    def _one_light(self, steps):
        """
        One peripheral's light dict for the current step.

        Precedence is blackout > lights off > burst > colour override > the scene.
        The burst never sets hue, so a colour chosen by hand survives one.
        """
        ring = dict(steps[self._light_step % len(steps)])
        ring.pop('seconds', None)         # timing is ours, not the wire's
        if self.color_index is not None and vizrock_settings.palette:
            ring['hue'] = vizrock_settings.palette[self.color_index]
        if self._burst_until > time.monotonic():
            # the burst changes how the lights move, never what colour they are, so
            # hue is pointedly not taken from the spec
            burst = self._burst_spec()
            ring['mode'] = burst.get('mode', 'strobe')
            for key in ('speed', 'bright'):
                if key in burst:
                    ring[key] = burst[key]
        return ring

    def _all_off(self):
        return {group: {'mode': 'off'} for group in vizrock_settings.light_groups.values()}

    def _effective_scene(self):
        """
        The live scene as the outputs should see it, with every mute and override
        applied. Outputs only ever receive a single ring dict — the step sequence is
        resolved here so nothing downstream has to know it exists.
        """
        if self.blackout:
            return {**BLACKOUT_SCENE, 'lights': self._all_off()}
        scene = self.scene_library.scenes.get(self.live)
        if scene is None:
            return None
        effective = dict(scene)
        effective['lights'] = self._all_off() if self.lights_off else self._lights_for(scene)
        return effective

    def _render(self):
        """
        Push current state out. Precedence: blackout > lights off > burst > colour >
        the scene, in one place so the UI and the outputs cannot disagree.
        """
        effective = self._effective_scene()
        if effective is not None:
            self._dispatch(effective)

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
        self._restart_light_loop()
        scene = self.scene_library.scenes[scene_id]
        # say what was actually targeted — "which clip did it fire?" is the first
        # question when visuals look wrong, and the action alone does not answer it
        resolume = scene.get('resolume') or {}
        target = 'clear' if resolume.get('clear') else \
            f"layer {resolume.get('layer')} clip {resolume.get('clip')}"
        logger.info('LIVE -> %s  (resolume: %s, ring: %s)%s',
                    self.scene_library.label(scene_id), target,
                    self._light_summary(scene),
                    ' [held dark]' if self.blackout else '')
        # Blackout is a master mute: you can load and change scenes underneath it, and
        # _render drops whichever half is muted. GO must not silently undo a blackout
        # someone put on deliberately.
        self._render()
        # auto-arm the next scene so a linear set is just GO, GO, GO
        if rearm and scene_id in self.scene_library.order:
            self.armed = self.scene_library.step_from(scene_id, +1)
        # "dispatched" while blacked out sends you hunting for a broken output, which
        # is exactly the wrong place to look — say which one it was.
        self.last_event = f'LIVE → {self.scene_library.label(scene_id)} · ' + \
            ('HELD DARK · blackout is on' if self.blackout else 'dispatched')
        self.push_state()
