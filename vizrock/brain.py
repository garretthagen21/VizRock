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
        elif action == 'home':
            if self.scene_library.home is None:
                logger.warning('no scenes, so nowhere to go home to')
            else:
                # like blackout, deliberately does not re-arm: bouncing out to the
                # main loop must leave whatever you had queued still queued
                self._commit(self.scene_library.home, rearm=False)
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
        self.blackout = True
        self._restore_to = self.scene_library.home
        self.live = None
        self._dispatch(BLACKOUT_SCENE)
        self.last_event = 'booted dark · main loop queued'
        logger.info('booted with blackout on, main loop (%s) queued', self._restore_to)

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
        target = self._restore_to
        if target not in self.scene_library.scenes:
            target = self.scene_library.home
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
        self.blackout = False
        scene = self.scene_library.scenes[scene_id]
        # say what was actually targeted — "which clip did it fire?" is the first
        # question when visuals look wrong, and the action alone does not answer it
        resolume = scene.get('resolume') or {}
        target = 'clear' if resolume.get('clear') else \
            f"layer {resolume.get('layer')} clip {resolume.get('clip')}"
        logger.info('LIVE -> %s  (resolume: %s, ring: %s)',
                    self.scene_library.label(scene_id), target,
                    (scene.get('ring') or {}).get('mode', 'off'))
        self._dispatch(scene)
        # auto-arm the next scene so a linear set is just GO, GO, GO
        if rearm and scene_id in self.scene_library.order:
            self.armed = self.scene_library.step_from(scene_id, +1)
        self.last_event = f'LIVE → {self.scene_library.label(scene_id)} · dispatched'
        self.push_state()
