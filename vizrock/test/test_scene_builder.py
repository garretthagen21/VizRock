#!/usr/bin/python3
#
# @file    test_scene_builder.py
#
# @brief   Generating scenes from clips must not wipe tuned cues
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-16
#


import json
import shutil
import tempfile
from pathlib import Path

import vizrock.constants.paths as vizrock_paths
from vizrock.managers import scene_builder


def _clips(folder, names):
    for name in names:
        (Path(folder) / name).touch()


def run():
    _scan_and_report()
    _duplicates_are_reported()
    _merge_preserves_tuning()
    _write_is_opt_in()


def _scan_and_report():
    folder = tempfile.mkdtemp()
    _clips(folder, ['01_Intro.mov', '02_Song A - verse.mov', '04_Interlude.mov',
                    'notes.txt', 'random.mov'])
    clips, ignored, duplicates = scene_builder.scan(folder)

    assert set(clips) == {1, 2, 4}, clips
    assert clips[2][0] == 'Song A - verse', clips[2]
    assert sorted(ignored) == ['notes.txt', 'random.mov'], ignored
    assert not duplicates, duplicates

    existing = {'scenes': [{'id': 3, 'name': 'Orphan', 'resolume': {'layer': 1, 'clip': 3}}]}
    issues = ' | '.join(scene_builder.problems(existing, clips, ignored, duplicates))
    assert 'gap: no file for clip 3' in issues, issues
    assert 'points at a clip with no file' in issues, issues
    assert 'notes.txt' in issues, issues


def _duplicates_are_reported():
    """Two files claiming one slot must not silently resolve to whichever sorts last."""
    folder = tempfile.mkdtemp()
    _clips(folder, ['03_take one.mov', '03_take two.mov'])
    clips, _, duplicates = scene_builder.scan(folder)

    assert len(clips) == 1, 'both files map to clip 3'
    assert duplicates, 'the collision was swallowed'
    assert duplicates[0][0] == 3, duplicates
    issues = ' | '.join(scene_builder.problems({}, clips, [], duplicates))
    assert 'duplicate: clip 3' in issues, issues


def _merge_preserves_tuning():
    """Regenerating must never wipe ring or DMX settings someone tuned in the UI."""
    existing = {'meta': {'show': 'THC'}, 'scenes': [
        {'id': 3, 'name': 'Old name', 'resolume': {'layer': 1, 'clip': 3},
         'ring': {'mode': 'strobe', 'hue': 150, 'bright': 200, 'speed': 8},
         'dmx': {'cue': 'strobe_cool'}, 'audio': True}]}
    clips = {1: ('Intro', '01_Intro.mov'), 3: ('Drop', '03_Drop.mov')}
    # slots are assigned in scene order: scene 1 -> clip 1, scene 3 -> clip 2

    merged = scene_builder.merge(existing, clips, layer=1)
    scenes = {scene['id']: scene for scene in merged['scenes']}

    assert scenes[3]['name'] == 'Drop', 'name should follow the file'
    assert scenes[3]['ring']['mode'] == 'strobe', 'ring tuning was wiped'
    assert scenes[3]['ring']['hue'] == 150
    assert scenes[3]['dmx']['cue'] == 'strobe_cool', 'dmx cue was wiped'
    assert scenes[3]['audio'] is True, 'audio flag was wiped'
    assert scenes[3]['resolume'] == {'layer': 1, 'clip': 2}, \
        'Resolume slots are assigned 1-based in scene order, not copied from the id'
    assert scenes[1]['name'] == 'Intro', 'new scene not added'
    assert merged['meta']['show'] == 'THC', 'meta must survive'
    assert merged['meta']['home_scene'] == 0, 'home_scene should default to 0'


def _write_is_opt_in():
    """Without --write nothing on disk may change."""
    scenes_file = vizrock_paths.ensure_seeded(vizrock_paths.Files.SCENES_FILE)
    backup = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name
    shutil.copy(scenes_file, backup)
    folder = tempfile.mkdtemp()
    _clips(folder, ['01_Only.mov'])
    try:
        before = scenes_file.read_text()
        scene_builder.main([folder])
        assert scenes_file.read_text() == before, 'a dry run wrote to disk'

        scene_builder.main([folder, '--write'])
        after = json.loads(scenes_file.read_text())
        assert any(s['id'] == 1 and s['name'] == 'Only' for s in after['scenes'])
    finally:
        shutil.copy(backup, scenes_file)
