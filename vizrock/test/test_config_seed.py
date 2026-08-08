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
