#!/usr/bin/python3
#
# @file    test_reorder.py
#
# @brief   Renumbering the setlist keeps clips, settings and LIVE/ARMED
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-17
#


import json
import shutil
import tempfile

import vizrock.constants.paths as vizrock_paths
from vizrock.brain import Brain
from vizrock.managers import scene_builder


def run():
    """Reordering writes scenes.json, so the real file is restored afterwards."""
    backup = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name
    shutil.copy(vizrock_paths.Files.SCENES_FILE, backup)
    try:
        _renumbers_and_keeps_clips()
        _follows_live_and_armed()
        _generator_does_not_undo_it()
        _home_always_resolves()
    finally:
        shutil.copy(backup, vizrock_paths.Files.SCENES_FILE)


def _renumbers_and_keeps_clips():
    brain = Brain()
    library = brain.scene_library
    before = {s['id']: s['resolume']['clip'] for s in library.sorted_scenes()}
    assert before == {1: 1, 2: 2, 3: 3}, before

    # put the last special first
    brain.reorder([3, 2])

    after = {s['id']: s for s in library.sorted_scenes()}
    assert sorted(after) == [1, 2, 3], sorted(after)
    assert after[1]['resolume']['clip'] == 1, 'home must stay id 1 with its clip'
    assert after[2]['resolume']['clip'] == 3, 'the video travels with the scene'
    assert after[3]['resolume']['clip'] == 2
    assert after[2]['name'] == 'Interlude', 'name travels too'
    assert after[2]['ring']['mode'] == 'chase', 'ring settings travel'
    assert library.order == [2, 3], library.order


def _follows_live_and_armed():
    brain = Brain()
    brain.handle('goto', 3)
    assert brain.live == 3
    brain.handle('arm', 2)

    brain.reorder([3, 2])            # scene 3 becomes 2, scene 2 becomes 3

    assert brain.live == 2, f'LIVE should follow the scene, not the number: {brain.live}'
    assert brain.armed == 3, f'ARMED should follow the scene: {brain.armed}'


def _generator_does_not_undo_it():
    """Re-running the generator must not silently restore the old numbering."""
    brain = Brain()
    brain.reorder([3, 2])
    existing = json.loads(vizrock_paths.Files.SCENES_FILE.read_text())

    clips = {1: ('Main loop', '01.mov'), 2: ('Song A - drop', '02.mov'),
             3: ('Interlude', '03.mov')}
    merged = scene_builder.merge(existing, clips, layer=1)
    by_id = {s['id']: s for s in merged['scenes']}

    assert by_id[2]['resolume']['clip'] == 3, 'the generator renumbered back'
    assert by_id[3]['resolume']['clip'] == 2
    assert len(merged['scenes']) == 3, 'it should not have invented duplicates'


def _home_always_resolves():
    """
    A dead HOME button is the worst failure available — it is the one thing you
    press to get out of trouble. If meta names a scene that does not exist, fall
    back rather than leaving it inert.
    """
    from vizrock.managers.scene_library import SceneLibrary

    library = SceneLibrary()
    library.load({'meta': {'home_scene': 99}, 'scenes': [
        {'id': 4, 'name': 'Main loop', 'resolume': {'layer': 1, 'clip': 1}},
        {'id': 5, 'name': 'Special', 'resolume': {'layer': 1, 'clip': 2}}]})
    assert library.home == 4, f'should fall back to the lowest id, got {library.home}'
    assert library.order == [5], 'home must still be excluded from stepping'

    library.load({'meta': {}, 'scenes': [
        {'id': 1, 'name': 'Main loop', 'resolume': {'layer': 1, 'clip': 1}}]})
    assert library.home == 1, 'default is 1'
