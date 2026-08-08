#!/usr/bin/python3
#
# @file    test_config_edit.py
#
# @brief   Live output config edits: rebuild, persist, roll back
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

import json
import shutil
import tempfile

import vizrock.constants.paths as vizrock_paths
from vizrock.outputs import build_outputs
from vizrock.brain import Brain


def run():
    """Edits write show_config.json, so the real file is restored afterwards."""
    backup = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name
    shutil.copy(vizrock_paths.Files.SHOW_CONFIG_FILE, backup)
    try:
        _edits_apply_and_persist()
        _bad_edits_roll_back()
    finally:
        shutil.copy(backup, vizrock_paths.Files.SHOW_CONFIG_FILE)


def _on_disk():
    return json.loads(vizrock_paths.Files.SHOW_CONFIG_FILE.read_text())


def _edits_apply_and_persist():
    brain = Brain()
    brain.outputs = build_outputs()
    names_before = [output.name for output in brain.outputs]
    assert 'resolume' in names_before, names_before

    assert brain.apply_output_config('resolume', {'hosts': ['127.0.0.1'], 'port': 9999})
    assert [o.name for o in brain.outputs] == names_before, 'position must be preserved'
    assert next(o for o in brain.outputs if o.name == 'resolume').port == 9999
    assert _on_disk()['outputs']['resolume']['port'] == 9999
    assert _on_disk()['triggers'], 'unrelated config must survive the round-trip'

    # replacing an output must not disturb show state
    brain.handle('go')
    live = brain.live
    assert brain.apply_output_config('resolume', {'hosts': ['127.0.0.1'], 'port': 9998})
    assert brain.live == live


def _bad_edits_roll_back():
    brain = Brain()
    brain.outputs = build_outputs()
    for bad in [{'hosts': 'a-bare-string'}, {'hosts': []}, {'hosts': ['']},
                {'hosts': ['ok.local'], 'port': 'nope'}, {'hosts': ['ok.local'], 'port': 0},
                {'hosts': [None]}]:
        before = _on_disk()['outputs']['resolume']
        assert not brain.apply_output_config('resolume', dict(bad)), f'{bad} was accepted'
        assert _on_disk()['outputs']['resolume'] == before, f'{bad} reached disk'
        assert any(o.name == 'resolume' for o in brain.outputs), f'{bad} lost the output'

    assert brain.apply_output_config('resolume', {'hosts': ['ok.local'], 'port': '7001'})
    assert next(o for o in brain.outputs if o.name == 'resolume').port == 7001
