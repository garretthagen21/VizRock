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
        self.last_event = 'armed · waiting for trigger'

    # MARK: - Actions (called from MIDI or the UI)
    def handle(self, action, scene=None):
        if action == 'arm_next':
            self._arm_step(+1)
        elif action == 'arm_prev':
            self._arm_step(-1)
        elif action == 'go':
            self._commit(self.armed)
        elif action == 'goto':
            self._commit(scene, rearm=True)
        elif action == 'home':
            if self.scene_library.home is None:
                logger.warning('no home_scene set in scenes.json meta')
            else:
                # like blackout, deliberately does not re-arm: bouncing out to the
                # main loop must leave whatever you had queued still queued
                self._commit(self.scene_library.home, rearm=False)
        elif action == 'blackout':
            self._dispatch(BLACKOUT_SCENE)
            self.live = None
            self.last_event = 'LIVE → blackout'
            self.push_state()
        else:
            logger.warning('unknown action: %s', action)

    def snapshot(self):
        return {
            'type': 'state',
            'live': self.live,
            'armed': self.armed,
            'last_event': self.last_event,
            'outputs': {output.name: output.status() for output in self.outputs},
            'addresses': {output.name: output.address_label() for output in self.outputs},
            'output_config': vizrock_settings.outputs,
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
        self._dispatch(self.scene_library.scenes[scene_id])
        # auto-arm the next scene so a linear set is just GO, GO, GO
        if rearm and scene_id in self.scene_library.order:
            self.armed = self.scene_library.step_from(scene_id, +1)
        self.last_event = f'LIVE → {self.scene_library.label(scene_id)} · dispatched'
        self.push_state()
