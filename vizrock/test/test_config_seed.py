#!/usr/bin/python3
#
# @file    test_config_seed.py
#
# @brief   Live configs seed from their committed .example
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#


import shutil
import tempfile

import vizrock.constants.paths as vizrock_paths
from vizrock.configurations.settings import VizRockSettings
from vizrock.managers.scene_library import SceneLibrary


def run():
    """
    The live configs are untracked — the UI rewrites them, and a tracked file with
    local edits makes `git pull` fail, which would break self-update the first time
    anyone changed a scene. So a fresh clone has to seed them from the examples.
    """
    _a_failed_save_leaves_the_old_file()
    live = [vizrock_paths.Files.SHOW_CONFIG_FILE, vizrock_paths.Files.SCENES_FILE]
    backups = {}
    for path in live:
        if path.exists():
            backups[path] = tempfile.NamedTemporaryFile(delete=False).name
            shutil.copy(path, backups[path])
            path.unlink()
    try:
        for path in live:
            assert not path.exists(), path.name
            assert path.with_name(f'{path.stem}.example.json').exists(), \
                f'{path.stem}.example.json must be committed'

        assert VizRockSettings().outputs, 'show config did not seed'
        assert SceneLibrary().order, 'scenes did not seed'
        for path in live:
            assert path.exists(), f'{path.name} was not created'
    finally:
        for path, backup in backups.items():
            shutil.copy(backup, path)


def _a_failed_save_leaves_the_old_file():
    """
    A save that dies part way must leave the previous config whole.

    write_text truncates first, so power pulled mid-save left half a JSON file — and a
    config that will not parse stops the box booting.
    """
    import os
    from pathlib import Path
    folder = Path(tempfile.mkdtemp())
    try:
        target = folder / 'show_config.json'
        target.write_text('{"intact": true}')
        real_fsync = os.fsync

        def power_cut(_):
            raise OSError('power cut')
        os.fsync = power_cut
        try:
            vizrock_paths.write_atomic(target, '{"half": ')
        except OSError:
            pass
        finally:
            os.fsync = real_fsync
        assert target.read_text() == '{"intact": true}', target.read_text()
        assert [p.name for p in folder.iterdir()] == ['show_config.json'], \
            'a failed save must not leave its temporary behind'

        vizrock_paths.write_atomic(target, '{"new": 1}')
        assert target.read_text() == '{"new": 1}'
        assert [p.name for p in folder.iterdir()] == ['show_config.json']
    finally:
        shutil.rmtree(folder)

