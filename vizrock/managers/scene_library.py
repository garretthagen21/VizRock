#!/usr/bin/python3
#
# @file    scene_library.py
#
# @brief   The scene table; loads and persists scenes.json
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import json
import logging

import vizrock.constants.paths as vizrock_paths

logger = logging.getLogger(__name__)

HOME_SCENE_ID = 1

# Blackout is not content — it is every output off, which needs no ring or dmx
# settings because they are zero by definition. Keeping it out of scenes.json frees
# id 0 for the main loop and keeps the setlist file purely about the show.
BLACKOUT_SCENE = {'name': 'Blackout',
                  'resolume': {'clear': True},
                  'dmx': {'cue': 'off'},
                  'ring': {'mode': 'off'},
                  'audio': False}


class SceneLibrary:
    """
    Scene lookup plus the steppable setlist order.

    The main loop named by `meta.home_scene` (default 1) sits outside that order: it
    is the default state you drop back into, not something to step onto by accident.
    """

    def __init__(self):
        self.load(json.loads(vizrock_paths.ensure_seeded(vizrock_paths.Files.SCENES_FILE).read_text()))

    def load(self, data):
        self.scenes = {scene['id']: scene for scene in data['scenes']}
        self.meta = data.get('meta', {})
        # the main loop is the default state, not a step in the set — like Blackout it
        # is reachable only by its own action, so PREV/NEXT never land on it
        # The main loop is always the home scene. If meta names one that does not
        # exist, fall back to the lowest id rather than leaving HOME inert — a dead
        # HOME button is the worst possible failure for the one thing you press to
        # get out of trouble.
        self.home = self.meta.get('home_scene', HOME_SCENE_ID)
        if self.home not in self.scenes and self.scenes:
            self.home = min(self.scenes)
            self.meta['home_scene'] = self.home
        # the main loop is the default state, not a step in the set — PREV/NEXT never land on it
        self.order = [scene['id'] for scene in data['scenes'] if scene['id'] != self.home]

    def save(self):
        data = {'meta': self.meta,
                'scenes': [self.scenes[i] for i in sorted(self.scenes)]}
        vizrock_paths.Files.SCENES_FILE.write_text(json.dumps(data, indent=2))
        logger.info('scenes.json saved')

    def reorder(self, ordered_ids):
        """
        Renumber the setlist to match a new running order.

        Scene ids are positions in the set, so reordering renumbers them — a grid you
        scan with your foot has to read 01, 02, 03. Each scene keeps its own
        `resolume.clip`, so the video it plays travels with it and id/clip diverge
        deliberately from here on.

        The home scene keeps id 1 and is never part of the order. Returns {old: new}
        so callers can follow LIVE and ARMED to the same scene rather than the same
        number.
        """
        home = self.home
        wanted = [i for i in ordered_ids if i in self.scenes and i != home]
        # anything the caller forgot keeps its relative position at the end
        wanted += [i for i in sorted(self.scenes) if i != home and i not in wanted]

        mapping = {home: home}
        for position, old_id in enumerate(wanted, start=home + 1):
            mapping[old_id] = position

        renumbered = {}
        for old_id, new_id in mapping.items():
            scene = dict(self.scenes[old_id])
            scene['id'] = new_id
            renumbered[new_id] = scene
        self.load({'meta': self.meta,
                   'scenes': [renumbered[i] for i in sorted(renumbered)]})
        self.save()
        return mapping

    def upsert(self, scene):
        self.scenes[scene['id']] = scene
        self.load({'meta': self.meta, 'scenes': list(self.scenes.values())})
        self.save()

    def sorted_scenes(self):
        return [self.scenes[i] for i in sorted(self.scenes)]

    def step_from(self, scene_id, delta):
        """Neighbouring scene in the setlist, clamped at both ends."""
        if not self.order:
            return None
        index = self.order.index(scene_id) if scene_id in self.order else 0
        return self.order[max(0, min(len(self.order) - 1, index + delta))]

    def label(self, scene_id):
        scene = self.scenes.get(scene_id)
        return f"{scene_id:02d} {scene['name']}" if scene else str(scene_id)
