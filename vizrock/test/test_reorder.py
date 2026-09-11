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
        _mains_and_migration()
        _reorder_is_flat()
    finally:
        shutil.copy(backup, vizrock_paths.Files.SCENES_FILE)


def _renumbers_and_keeps_clips():
    brain = Brain()
    library = brain.scene_library
    before = {s['id']: s['resolume']['clip'] for s in library.sorted_scenes()}
    assert before == {1: 1, 2: 2, 3: 3}, before

    # put the last scene first; anything the caller omits keeps its relative
    # position at the end, so 1 lands last
    brain.reorder([3, 2])

    after = {s['id']: s for s in library.sorted_scenes()}
    assert sorted(after) == [1, 2, 3], sorted(after)
    assert after[1]['resolume']['clip'] == 3, 'the video travels with the scene'
    assert after[2]['resolume']['clip'] == 2
    assert after[3]['resolume']['clip'] == 1, 'nothing is pinned any more'
    assert after[1]['name'] == 'Interlude', 'name travels too'
    assert after[1]['lights']['default']['mode'] == 'chase', 'light settings travel'
    assert library.order == [1, 2, 3], library.order


def _follows_live_and_armed():
    brain = Brain()
    brain.handle('goto', 3)
    assert brain.live == 3
    brain.armed = 2                   # a cue tap fires now, so ARMED is set by stepping

    brain.reorder([3, 2])            # flat: 3 -> 1, 2 -> 2, and the omitted 1 -> 3

    assert brain.live == 1, f'LIVE should follow the scene, not the number: {brain.live}'
    assert brain.armed == 2, f'ARMED should follow the scene: {brain.armed}'


def _generator_does_not_undo_it():
    """Re-running the generator must not silently restore the old numbering."""
    brain = Brain()
    brain.reorder([3, 2])
    existing = json.loads(vizrock_paths.Files.SCENES_FILE.read_text())

    clips = {1: ('Main loop', '01.mov'), 2: ('Song A - drop', '02.mov'),
             3: ('Interlude', '03.mov')}
    merged = scene_builder.merge(existing, clips, layer=1)
    by_id = {s['id']: s for s in merged['scenes']}

    assert by_id[1]['resolume']['clip'] == 3, 'the generator renumbered back'
    assert by_id[2]['resolume']['clip'] == 2
    assert by_id[3]['resolume']['clip'] == 1
    assert len(merged['scenes']) == 3, 'it should not have invented duplicates'


def _mains_and_migration():
    """
    Mains are a per-scene flag, several are allowed, and the long-press cycles them.
    A pre-2026-09 `meta.home_scene` must become a flag rather than being dropped.
    """
    from vizrock.managers.scene_library import SceneLibrary

    library = SceneLibrary()
    library.load({'meta': {}, 'scenes': [
        {'id': 1, 'name': 'Walkout'},
        {'id': 2, 'name': 'Drift', 'main': True},
        {'id': 3, 'name': 'Chop Suey'},
        {'id': 4, 'name': 'Red haze', 'main': True}]})

    assert library.mains == [2, 4], library.mains
    assert library.order == [1, 2, 3, 4], 'every scene steps now, mains included'

    # cycles forward from wherever you are, wrapping
    assert library.next_main(1) == 2
    assert library.next_main(2) == 4, 'from a main, advance to the next one'
    assert library.next_main(3) == 4
    assert library.next_main(4) == 2, 'wraps to the first'

    # no mains at all: a dead button, not an arbitrary jump
    library.load({'meta': {}, 'scenes': [{'id': 1, 'name': 'Only'}]})
    assert library.mains == []
    assert library.next_main(1) is None, 'must not invent a scene to jump to'

    # the old single-home config becomes a flag on that scene
    library.load({'meta': {'home_scene': 2, 'show': 'THC'}, 'scenes': [
        {'id': 1, 'name': 'A'}, {'id': 2, 'name': 'B'}]})
    assert library.scenes[2].get('main') is True, 'home_scene should migrate to a flag'
    assert library.mains == [2]
    assert 'home_scene' not in library.meta, 'the old key should not linger'
    assert library.meta['show'] == 'THC', 'the rest of meta must survive'


def _reorder_is_flat():
    """Mains renumber alongside specials — a main is a set position like any other."""
    from vizrock.managers.scene_library import SceneLibrary

    library = SceneLibrary()
    library.load({'meta': {}, 'scenes': [
        {'id': 1, 'name': 'A', 'resolume': {'layer': 1, 'clip': 1}},
        {'id': 2, 'name': 'B', 'main': True, 'resolume': {'layer': 1, 'clip': 2}},
        {'id': 3, 'name': 'C', 'resolume': {'layer': 1, 'clip': 3}}]})
    mapping = library.reorder([3, 1, 2])

    assert mapping == {3: 1, 1: 2, 2: 3}, mapping
    assert library.scenes[1]['name'] == 'C'
    assert library.scenes[3]['name'] == 'B', 'the main moved with the drag'
    assert library.scenes[3].get('main') is True, 'the flag travels with the scene'
    assert library.mains == [3], library.mains
    assert library.scenes[3]['resolume']['clip'] == 2, 'clips travel with the scene'
