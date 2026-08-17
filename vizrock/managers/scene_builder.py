#!/usr/bin/python3
#
# @file    scene_builder.py
#
# @brief   Build and validate scenes.json from a folder of numbered clips
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-16
#


import argparse
import json
import re
import sys
from pathlib import Path

import vizrock.constants.paths as vizrock_paths
from vizrock.managers.scene_library import HOME_SCENE_ID

VIDEO_SUFFIXES = {'.mov', '.mp4', '.m4v', '.avi', '.mkv'}
CLIP_PATTERN = re.compile(r'^(\d+)[\s_-]+(.+)$')

DEFAULT_RING = {'mode': 'off', 'hue': 0, 'bright': 0, 'speed': 0}


def scan(folder):
    """
    Return ({clip_number: (name, filename)}, ignored, duplicates).

    Two files claiming the same number is the quiet failure this tool exists to
    catch — one silently wins and the wrong visual fires on stage.
    """
    found = {}
    ignored = []
    duplicates = []
    for path in sorted(Path(folder).iterdir()):
        if path.is_dir() or path.name.startswith('.'):
            continue
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            ignored.append(path.name)
            continue
        match = CLIP_PATTERN.match(path.stem)
        if not match:
            ignored.append(path.name)
            continue
        number = int(match.group(1))
        name = match.group(2).replace('_', ' ').strip()
        if number in found:
            duplicates.append((number, found[number][1], path.name))
        found[number] = (name, path.name)
    return found, ignored, duplicates


def merge(existing, clips, layer):
    """
    Fold scanned clips into the current scene table.

    Existing scenes keep their ring, dmx and audio settings — regenerating must
    never wipe cues someone tuned in the UI. Only the name and clip number follow
    the files.
    """
    by_id = {scene['id']: dict(scene) for scene in existing.get('scenes', [])}
    # Match on the clip a scene already plays, not on its id. Ids are set positions
    # and drift once the setlist is reordered, so keying on them would silently undo
    # someone's running order the next time this ran.
    by_clip = {s.get('resolume', {}).get('clip'): s['id']
               for s in by_id.values() if s.get('resolume', {}).get('clip')}
    next_id = max(by_id, default=0) + 1
    for number, (name, _) in sorted(clips.items()):
        existing_id = by_clip.get(number)
        if existing_id is not None:
            by_id[existing_id]['name'] = name
            continue
        scene = {'id': next_id, 'name': name, 'ring': dict(DEFAULT_RING),
                 'dmx': {'cue': 'off'}, 'audio': False,
                 'resolume': {'layer': layer, 'clip': number}}
        by_id[next_id] = scene
        next_id += 1
    meta = dict(existing.get('meta', {}))
    meta.setdefault('home_scene', HOME_SCENE_ID)
    return {'meta': meta, 'scenes': [by_id[i] for i in sorted(by_id)]}


def problems(existing, clips, ignored, duplicates=()):
    """Everything that would bite at showtime, as plain sentences."""
    issues = []
    for number, first, second in duplicates:
        issues.append(f'duplicate: clip {number} claimed by both {first} and {second} '
                      f'— {second} wins, which may not be what you meant')
    for name in ignored:
        issues.append(f'ignored (does not look like NN_name.mov): {name}')
    if clips:
        expected = set(range(1, max(clips) + 1))
        for missing in sorted(expected - set(clips)):
            issues.append(f'gap: no file for clip {missing} — Resolume slot {missing} is empty')
    for scene in existing.get('scenes', []):
        number = scene['id']
        if scene.get('resolume', {}).get('clear'):
            continue
        clip = scene.get('resolume', {}).get('clip')
        if clip is not None and clip not in clips:
            issues.append(f'scene {number} "{scene.get("name", "?")}" plays clip {clip}, '
                          f'which has no file')
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Build scenes.json from a folder of clips named NN_name.mov')
    parser.add_argument('folder', help='folder of exported clips')
    parser.add_argument('--layer', type=int, default=1, help='Resolume layer (default 1)')
    parser.add_argument('--write', action='store_true',
                        help='apply the changes; without it nothing is written')
    args = parser.parse_args(argv)

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f'not a folder: {folder}', file=sys.stderr)
        return 1

    clips, ignored, duplicates = scan(folder)
    scenes_file = vizrock_paths.ensure_seeded(vizrock_paths.Files.SCENES_FILE)
    existing = json.loads(scenes_file.read_text())

    print(f'{len(clips)} clip(s) in {folder}')
    for number, (name, filename) in sorted(clips.items()):
        home = '  (home)' if number == HOME_SCENE_ID else ''
        print(f'  {number:02d}  {name:<26} {filename}{home}')

    issues = problems(existing, clips, ignored, duplicates)
    for issue in issues:
        print(f'  ! {issue}')

    merged = merge(existing, clips, args.layer)
    if not args.write:
        print(f'\n{len(merged["scenes"])} scene(s) would be written — re-run with --write')
        return 1 if issues else 0

    scenes_file.write_text(json.dumps(merged, indent=2))
    print(f'\nwrote {scenes_file} ({len(merged["scenes"])} scenes)')
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
