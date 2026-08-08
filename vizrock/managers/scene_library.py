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

BLACKOUT_SCENE_ID = 0


class SceneLibrary:
    """Scene lookup plus the steppable setlist order, which excludes Blackout."""

    def __init__(self):
        self.load(json.loads(vizrock_paths.ensure_seeded(vizrock_paths.Files.SCENES_FILE).read_text()))

    def load(self, data):
        self.scenes = {scene['id']: scene for scene in data['scenes']}
        self.order = [scene['id'] for scene in data['scenes'] if scene['id'] != BLACKOUT_SCENE_ID]
        self.meta = data.get('meta', {})

    def save(self):
        data = {'meta': self.meta,
                'scenes': [self.scenes[i] for i in sorted(self.scenes)]}
        vizrock_paths.Files.SCENES_FILE.write_text(json.dumps(data, indent=2))
        logger.info('scenes.json saved')

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
