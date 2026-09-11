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

# Every action `handle` understands. Exposed to the UI so a trigger mapped to an
# action that no longer exists shows up as dead rather than as silently doing nothing
# — which is how `home` survived in the pedal config after the action was removed.
KNOWN_ACTIONS = (
    'go', 'goto', 'arm', 'arm_prev', 'arm_next', 'next_main', 'restart_scene',
    'blackout', 'clear_effects', 'light_burst', 'cycle_color',
    'audition_scene', 'audition_lights', 'audition_end',
)

# OSC has no delivery confirmation and no heartbeat the way the lights do, so a
# reset is sent more than once rather than trusted to land.
EFFECT_RESET_REPEAT = 3


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
        # switch, because "lights off, visuals running" is a real ask and the reverse
        # never is. Both are pure output mutes: LIVE stays set throughout, so
        # releasing either reveals the scene rather than restoring a remembered one.
        self.blackout = False
        self.color_index = None          # None = the scene's own hue
        self._burst_until = 0.0          # light burst expiry, monotonic
        self._restart_visuals = False    # re-fire the clip on the next dispatch
        self._scene_effect_timer = None  # clears a timed scene effect
        self._burst_timer = None
        self._light_step = 0             # position in a scene's looping light sequence
        self._light_timer = None
        self._auditioning = False        # holding a preview of a scene being edited
        self.last_action = None
        self._action_seq = 0
        self.last_event = 'armed · waiting for trigger'

    # MARK: - Actions (called from MIDI or the UI)
    def handle(self, action, scene=None):
        # The UI flashes the matching transport button, so it needs to know an action
        # fired even when the resulting state is identical — a counter, not a value,
        # or two GOs in a row look like one.
        self.last_action = action
        self._action_seq += 1
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
                # Restart means the scene as authored: clip from the top, light
                # sequence from step 1, the scene's own hue, no burst running. A
                # color picked by hand mid-set must not survive a restart, or the
                # button does not actually get you back to a known state.
                self._cancel_burst()
                # the only thing that re-fires a clip that is already playing
                self._restart_visuals = True
                self._commit(self.live, rearm=False)
        elif action == 'clear_effects':
            self._clear_effects()
        elif action == 'cycle_color':
            self._cycle_color()
        elif action == 'audition_scene':
            self._audition(scene, lights_only=False)
        elif action == 'audition_lights':
            self._audition(scene, lights_only=True)
        elif action == 'audition_end':
            self._end_audition()
        elif action == 'light_burst':
            self._light_burst()
        elif action == 'blackout':
            self._toggle_blackout()
        else:
            logger.warning('unknown action: %s (known: %s)', action, ', '.join(KNOWN_ACTIONS))

    def boot(self):
        """
        Come up dark with the main loop queued.

        Powering on should never throw a visual at a screen nobody is ready for — but
        releasing blackout should land on the main loop rather than nothing, so the
        restore target is primed rather than left empty. Call once outputs exist.
        """
        # The set opens on scene 1, so that is what boots loaded — the first main is
        # where you go when something breaks, not where the night starts.
        opener = self.scene_library.order[0] if self.scene_library.order else None
        self.blackout = True
        # LIVE shows the scene so you can see what you will get back; every output is
        # muted, so nothing actually reaches the stage until blackout is released
        self.live = opener
        if opener is not None:
            self.armed = self.scene_library.step_from(opener, +1)
        self._render()
        self.last_event = 'booted blacked out · opener loaded'
        logger.info('booted blacked out with scene %s loaded, %s armed', opener, self.armed)

    def snapshot(self):
        return {
            'type': 'state',
            'live': self.live,
            'armed': self.armed,
            'last_event': self.last_event,
            'last_action': self.last_action,
            'action_seq': self._action_seq,
            'outputs': {output.name: output.status() for output in self.outputs},
            'addresses': {output.name: output.address_label() for output in self.outputs},
            'output_config': vizrock_settings.outputs,
            'tap_fires': vizrock_settings.tap_fires,
            'triggers': vizrock_settings.triggers,
            'burst': vizrock_settings.burst,
            'known_actions': list(KNOWN_ACTIONS),
            'blackout': self.blackout,
            'color_index': self.color_index,
            'palette': vizrock_settings.palette,
            'live_light': self._live_light(),
            'auditioning': self._auditioning,
            'light_groups': vizrock_settings.light_groups,
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
        if self.blackout:
            # every output off has to mean effects too — otherwise a blackout hides
            # the clip and leaves the effect running on nothing
            self._cancel_scene_effect()
            self._send_effects('osc_end', repeat=EFFECT_RESET_REPEAT, scene_override=False)
        self.last_event = 'blackout · press again to restore' if self.blackout else 'blackout off'
        logger.info(self.last_event)
        self._render()
        self.push_state()

    def _cycle_color(self):
        """
        Step the light color through the palette, and back to the scene's own hue.

        The scene's color is one of the stops rather than something you can only
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
        self.last_event = f'light color · {hue}'
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
        than what color the stage is.

        LightSerial re-sends the last payload every ~250ms and holds no timer of its
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
        self._send_effects('osc')
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

        Lights are keyed by peripheral — `default`, `cabA`, `cabB` — so one scene can
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
        # Monotonic, not wrapped to the default's length: every peripheral indexes it
        # with its own modulo, so one with three steps driven by a two-step default
        # used to cycle 0,1,0,1 and never reach its third. Reset to 0 on every cue,
        # so it never grows.
        self._light_step += 1
        self._render()
        self.push_state()
        self._schedule_light_step()

    def _audition(self, scene_id, lights_only):
        """
        Show a scene while a button is held, without committing it.

        Never touches LIVE or ARMED — this is a preview of something being edited,
        not a cue. It shows the scene **as authored**: step 1, its own hue, no burst,
        because the question being asked is "what did I just write".

        Blackout blocks it: nothing but blackout clears blackout, and a preview
        lighting up a stage someone deliberately killed would be the worst kind of
        surprise. A muted lights output does not block it either — you are plainly
        asking to see the lights, and the mute is a convenience, not a safety.
        """
        if self.blackout:
            self.last_event = 'audition blocked · blackout is on'
            self.push_state()
            return
        scene = self.scene_library.scenes.get(scene_id)
        if scene is None:
            logger.warning('audition of missing scene %s', scene_id)
            return
        preview = dict(scene)
        configs = self._light_configs(scene)
        fallback = configs[self._default_config_name(configs)]
        preview['lights'] = {
            group: self._authored_light(configs.get(name, fallback))
            for name, group in vizrock_settings.light_groups.items()}
        if lights_only:
            # keep whatever is actually on screen; only the lights change
            live = self.scene_library.scenes.get(self.live) or {}
            preview['resolume'] = live.get('resolume') or {'clear': True}
            preview['dmx'] = live.get('dmx') or {'cue': 'off'}
        self._auditioning = True
        self._dispatch(preview)
        self.last_event = f'auditioning {self.scene_library.label(scene_id)}'
        self.push_state()

    @staticmethod
    def _authored_light(steps):
        light = dict(steps[0])
        light.pop('seconds', None)
        return light

    def _end_audition(self):
        if not self._auditioning:
            return
        self._auditioning = False
        self._render()
        self.last_event = 'audition ended'
        self.push_state()

    def _cancel_burst(self):
        if self._burst_timer:
            self._burst_timer.cancel()
            self._burst_timer = None
        self._burst_until = 0.0

    def _send_effects(self, key, repeat=1, scene_override=True):
        """
        Fire the burst's OSC at whichever output can carry it.

        `scene_override=False` reads the global spec only. The commit-time reset needs
        that: by then LIVE is already the *incoming* scene, so a per-scene `osc_end`
        would send the new scene's reset for an effect the old one turned on.

        Duck-typed on `send_messages` rather than looking for the visuals output by
        name — brain.py must not special-case a particular output.
        """
        spec = self._burst_spec() if scene_override else vizrock_settings.burst
        self._send_osc(spec.get(key), repeat=repeat)

    def _send_osc(self, messages, repeat=1):
        """
        Send a list of OSC messages to whichever output can carry them.

        Duck-typed on `send_messages` rather than looking for the visuals output by
        name — brain.py must not special-case a particular output.
        """
        if not messages:
            return
        for output in self.outputs:
            sender = getattr(output, 'send_messages', None)
            if not sender:
                continue
            try:
                sender(messages, repeat=repeat)
            except Exception as error:
                logger.warning('effect send via %s failed: %s', output.name, error)

    def _clear_effects(self):
        """
        Force every effect off, without touching the clip, the lights or LIVE.

        OSC is fire-and-forget with no acknowledgement and no heartbeat, so a reset
        packet that gets dropped leaves an effect stuck on for the rest of the night.
        A scene change or `restart_scene` would also clear it, but both move the show;
        this is the one that does nothing else, so it is safe to hit mid-song.
        """
        self._cancel_scene_effect()
        self._send_effects('osc_end', repeat=EFFECT_RESET_REPEAT, scene_override=False)
        self.last_event = 'effects cleared'
        logger.info(self.last_event)
        self.push_state()

    def _cancel_scene_effect(self):
        if self._scene_effect_timer:
            self._scene_effect_timer.cancel()
            self._scene_effect_timer = None

    def _end_scene_effect(self):
        """
        Take down a timed scene effect.

        Uses the global reset rather than anything the scene carries: the scene says
        what to turn on, and only the global list knows how to turn everything off.
        """
        self._scene_effect_timer = None
        self._send_effects('osc_end', repeat=EFFECT_RESET_REPEAT, scene_override=False)

    def _end_burst(self):
        self._send_effects('osc_end', repeat=EFFECT_RESET_REPEAT)
        self._burst_until = 0.0
        self._render()
        self.push_state()

    def _lights_for(self, scene):
        """
        Resolve a scene to {group number: light dict}, one entry per configured
        peripheral, with the color override and any burst applied.

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

        Precedence is blackout > lights off > burst > color override > the scene.
        The burst never sets hue, so a color chosen by hand survives one.
        """
        light = dict(steps[self._light_step % len(steps)])
        light.pop('seconds', None)        # timing is ours, not the wire's
        if self.color_index is not None and vizrock_settings.palette:
            light['hue'] = vizrock_settings.palette[self.color_index]
        if self._burst_until > time.monotonic():
            # A burst is a whole light command interjected for a moment, so it can
            # carry colour as well as movement. It only does so when the spec says
            # to — with no colour of its own it leaves the scene's alone, which is
            # what makes the common case a change of movement rather than of look.
            burst = self._burst_spec()
            light['mode'] = burst.get('mode', 'strobe')
            for key in ('speed', 'bright', 'sat'):
                if key in burst:
                    light[key] = burst[key]
            if 'hue' in burst or 'colors' in burst:
                # replace the colour outright. Leaving a scene palette in place would
                # silently outrank a burst hue, since a palette overrides hue downstream.
                light.pop('colors', None)
                for key in ('hue', 'colors'):
                    if key in burst:
                        light[key] = burst[key]
        return light

    def _live_light(self):
        """
        The default group's light as the strip actually has it — colour override,
        burst and light step all applied.

        The UI previews this rather than the authored value. Deriving it there would
        mean re-implementing the precedence rules in JS, and the UI had no palette to
        resolve a colour index against, so a colour cycled from the pedal changed the
        lights and never appeared on screen.
        """
        lights = (self._effective_scene() or {}).get('lights')
        if not isinstance(lights, dict) or not lights:
            return None
        group = vizrock_settings.light_groups.get('default')
        return lights.get(group if group in lights else min(lights))

    def _all_off(self):
        return {group: {'mode': 'off'} for group in vizrock_settings.light_groups.values()}

    def _effective_scene(self):
        """
        The live scene as the outputs should see it, with every mute and override
        applied. Outputs only ever receive one light dict per group — the step sequence
        resolved here so nothing downstream has to know it exists.
        """
        if self.blackout:
            return {**BLACKOUT_SCENE, 'lights': self._all_off()}
        scene = self.scene_library.scenes.get(self.live)
        if scene is None:
            return None
        effective = dict(scene)
        effective['lights'] = self._lights_for(scene)
        return effective

    def _render(self):
        """
        Push current state out. Precedence: blackout > lights off > burst > color >
        the scene, in one place so the UI and the outputs cannot disagree.
        """
        effective = self._effective_scene()
        if effective is not None:
            if self._restart_visuals:
                effective['restart'] = True
            self._dispatch(effective)
        self._restart_visuals = False

    def _output_enabled(self, name):
        return bool(vizrock_settings.outputs.get(name, {}).get('enabled', True))

    def set_output_enabled(self, name, enabled):
        """
        Mute or unmute an output for the rest of the show.

        Muting sends that output's safe-off first and then stops dispatching to it, so
        the stage goes dark rather than freezing on the last cue. The connection stays
        open on purpose: the light transmitter has to keep holding "off" on the wire,
        because a receiver that hears nothing for four seconds falls back to its idle
        pattern and would glow rather than go dark.
        """
        if name not in vizrock_settings.outputs:
            logger.warning('no such output: %s', name)
            return
        vizrock_settings.update_output(name, {'enabled': bool(enabled)})
        vizrock_settings.save()
        if enabled:
            self._render()                      # catch up on whatever it missed
        else:
            for output in self.outputs:
                if output.name != name:
                    continue
                silence = getattr(output, 'silence', None)
                if not silence:
                    continue
                try:
                    silence()
                except Exception as error:
                    logger.warning('silencing %s failed: %s', name, error)
        self.last_event = f"{name} {'on' if enabled else 'muted'}"
        logger.info('output %s %s', name, 'enabled' if enabled else 'muted')
        self.push_state()

    def _dispatch(self, scene):
        """Fan a scene out to every output, each isolated so one failure cannot spread."""
        for output in self.outputs:
            if not self._output_enabled(output.name):
                continue
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
        # A colour cycled by hand is a momentary fiddle, not a setting: it dies at the
        # next cue so every scene comes up the colour it was authored. Without this a
        # colour picked during one song quietly repainted the rest of the set.
        self.color_index = None
        # Every cue starts from a clean composition. OSC is fire-and-forget, so an
        # effect left on because its reset was dropped would be a stuck visual for
        # the rest of the song — cheaper to re-assert than to hope.
        self._send_effects('osc_end', repeat=EFFECT_RESET_REPEAT, scene_override=False)
        self._restart_light_loop()
        scene = self.scene_library.scenes[scene_id]
        # say what was actually targeted — "which clip did it fire?" is the first
        # question when visuals look wrong, and the action alone does not answer it
        resolume = scene.get('resolume') or {}
        target = 'clear' if resolume.get('clear') else \
            f"layer {resolume.get('layer')} clip {resolume.get('clip')}"
        logger.info('LIVE -> %s  (resolume: %s, lights: %s)%s',
                    self.scene_library.label(scene_id), target,
                    self._light_summary(scene),
                    ' [held dark]' if self.blackout else '')
        # Blackout is a master mute: you can load and change scenes underneath it, and
        # _render drops whichever half is muted. GO must not silently undo a blackout
        # someone put on deliberately.
        self._render()
        # The scene's own effects, after the reset above cleared the previous scene's
        # and after the clip is connected. This is what makes a scene change visible
        # when the clip does not change: several scenes share one video and differ by
        # the effect laid over it. Skipped under blackout — an effect on a composition
        # nobody can see is just a stuck parameter waiting to surprise someone.
        # Cancelled unconditionally, outside the blackout guard: a timer left running
        # from the previous scene would fire later and clear *this* scene's effect.
        self._cancel_scene_effect()
        if not self.blackout:
            self._send_osc(scene.get('osc'))
            # `osc_seconds` makes it a burst that clears itself; without it the effect
            # holds for the whole scene and the next cue's reset takes it down.
            seconds = float(scene.get('osc_seconds') or 0)
            if seconds > 0:
                self._scene_effect_timer = threading.Timer(
                    seconds, lambda: self._from_thread(self._end_scene_effect))
                self._scene_effect_timer.daemon = True
                self._scene_effect_timer.start()
        # auto-arm the next scene so a linear set is just GO, GO, GO
        if rearm and scene_id in self.scene_library.order:
            self.armed = self.scene_library.step_from(scene_id, +1)
        # "dispatched" while blacked out sends you hunting for a broken output, which
        # is exactly the wrong place to look — say which one it was.
        self.last_event = f'LIVE → {self.scene_library.label(scene_id)} · ' + \
            ('HELD DARK · blackout is on' if self.blackout else 'dispatched')
        self.push_state()
