#!/usr/bin/python3
#
# @file    test_runner.py
#
# @brief   Runs every suite; vizrock_test entry point
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

import json
import os
import shutil
import tempfile
import traceback
from pathlib import Path

# Point the config dir at a throwaway copy before anything imports it, so a test
# run can never touch the real scenes file. Seed it with the committed examples.
_REAL_CONFIGS = Path(__file__).parents[2] / 'configs'   # the redirect is read lazily
_TMP_CONFIGS = Path(tempfile.mkdtemp(prefix='vizrock-test-configs-'))
for _example in _REAL_CONFIGS.glob('*.example.json'):
    shutil.copy(_example, _TMP_CONFIGS / _example.name)

# The suites get their own setlist rather than the shipped one. scenes.example.json
# is the real show and changes whenever the set does — asserting against it means
# every setlist edit breaks the tests for no reason.
(_TMP_CONFIGS / 'scenes.example.json').write_text(json.dumps({
    'meta': {'show': 'TEST'},
    'scenes': [
        {'id': 1, 'name': 'Main loop', 'main': True,
         'resolume': {'layer': 1, 'clip': 1}, 'dmx': {'cue': 'off'},
         'lights': {'default': {'mode': 'pulse', 'hue': 200, 'bright': 80, 'speed': 2}},
         'audio': False},
        {'id': 2, 'name': 'Song A - drop',
         'resolume': {'layer': 1, 'clip': 2}, 'dmx': {'cue': 'off'},
         'lights': {'default': {'mode': 'strobe', 'hue': 0, 'bright': 220, 'speed': 8}},
         'audio': False},
        {'id': 3, 'name': 'Interlude',
         'resolume': {'layer': 1, 'clip': 3}, 'dmx': {'cue': 'off'},
         'lights': {'default': {'mode': 'chase', 'hue': 96, 'bright': 110, 'speed': 3}},
         'audio': False},
    ]}, indent=2))
os.environ['VIZROCK_CONFIG_DIR'] = str(_TMP_CONFIGS)

from vizrock.test import stubs

stubs.install()

SUITES = ['test_state_machine', 'test_outputs', 'test_resolver', 'test_config_edit', 'test_updater', 'test_ui_server', 'test_config_seed', 'test_scene_builder', 'test_reorder', 'test_migrate']


def main():
    import importlib

    failures = 0
    for name in SUITES:
        module = importlib.import_module(f'vizrock.test.{name}')
        try:
            module.run()
            print(f'  ok   {name}')
        except Exception:
            failures += 1
            print(f'  FAIL {name}')
            traceback.print_exc()
    print(f'\n{len(SUITES) - failures} passed, {failures} failed')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
