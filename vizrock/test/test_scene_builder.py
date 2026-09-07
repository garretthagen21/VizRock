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
    _shared_clips_are_not_renamed()
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
    assert 'plays clip 3, which has no file' in issues, issues
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
    """
    Regenerating must never wipe light or DMX settings someone tuned in the UI, and
    must match on the clip a scene plays rather than its id — ids are set positions
    and drift once the setlist is reordered.
    """
    existing = {'meta': {'show': 'THC'}, 'scenes': [
        {'id': 3, 'name': 'Old name', 'resolume': {'layer': 1, 'clip': 2},
         'lights': {'default': {'mode': 'strobe', 'hue': 150, 'bright': 200, 'speed': 8}},
         'dmx': {'cue': 'strobe_cool'}, 'audio': True}]}
    clips = {2: ('Drop', '02_Drop.mov'), 5: ('New thing', '05_New thing.mov')}

    merged = scene_builder.merge(existing, clips, layer=1)
    scenes = {scene['id']: scene for scene in merged['scenes']}

    # matched by clip 2, not by id
    assert scenes[3]['name'] == 'Drop', 'name should follow the file'
    assert scenes[3]['resolume']['clip'] == 2, 'the scene keeps the clip it plays'
    assert scenes[3]['lights']['default']['mode'] == 'strobe', 'light tuning was wiped'
    assert scenes[3]['lights']['default']['hue'] == 150
    assert scenes[3]['dmx']['cue'] == 'strobe_cool', 'dmx cue was wiped'
    assert scenes[3]['audio'] is True, 'audio flag was wiped'

    # an unseen clip becomes a new scene appended after the highest id
    added = [s for s in merged['scenes'] if s['resolume']['clip'] == 5]
    assert len(added) == 1 and added[0]['name'] == 'New thing', merged['scenes']
    assert added[0]['id'] == 4, f"should append, not reuse a position: {added[0]['id']}"

    assert merged['meta']['show'] == 'THC', 'meta must survive'
    assert 'home_scene' not in merged['meta'], 'home_scene is replaced by a per-scene main flag'


def _shared_clips_are_not_renamed():
    """
    Several scenes on one clip is the normal case — an intro, a drop and an outro
    sharing one video with different light looks. The filename cannot say which
    name belongs to which, so regenerating must leave all of them alone rather
    than renaming whichever sorted last.
    """
    existing = {'meta': {}, 'scenes': [
        {'id': 1, 'name': 'Suey Intro', 'resolume': {'layer': 1, 'clip': 2},
         'lights': {'default': {'mode': 'solid', 'hue': 0}}},
        {'id': 2, 'name': 'Suey Drop', 'resolume': {'layer': 1, 'clip': 2},
         'lights': {'default': {'mode': 'strobe', 'hue': 0}}},
        {'id': 3, 'name': 'Machine Intro', 'resolume': {'layer': 1, 'clip': 3},
         'lights': {'default': {'mode': 'solid', 'hue': 96}}}]}

    merged = scene_builder.merge(existing, {2: ('Renamed On Disk', '02_x.mov'),
                                            3: ('Machine Renamed', '03_y.mov')}, layer=1)
    by_id = {s['id']: s for s in merged['scenes']}

    assert by_id[1]['name'] == 'Suey Intro', by_id[1]['name']
    assert by_id[2]['name'] == 'Suey Drop', 'a shared clip must not rename either scene'
    assert by_id[3]['name'] == 'Machine Renamed', 'a clip with one scene still follows the file'
    assert len(merged['scenes']) == 3, 'no duplicate scene invented for a shared clip'
    assert by_id[2]['lights']['default']['mode'] == 'strobe', 'light tuning survives'

    reported = scene_builder.problems(existing, {2: ('x', 'a.mov')}, [])
    assert any('shared by 2 scenes' in issue for issue in reported), reported


def _write_is_opt_in():
    """Without --write nothing on disk may change."""
    scenes_file = vizrock_paths.ensure_seeded(vizrock_paths.Files.SCENES_FILE)
    folder = tempfile.mkdtemp()
    _clips(folder, ['01_Only.mov'])

    before = scenes_file.read_text()
    scene_builder.main([folder])
    assert scenes_file.read_text() == before, 'a dry run wrote to disk'

    scene_builder.main([folder, '--write'])
    after = json.loads(scenes_file.read_text())
    assert any(s['name'] == 'Only' for s in after['scenes']), after['scenes']
