#!/usr/bin/python3
#
# @file    paths.py
#
# @brief   Filesystem locations for configs and web assets
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import os
from pathlib import Path


class Directories:
    PACKAGE_DIR = Path(__file__).parents[1]
    REPO_DIR = PACKAGE_DIR.parent
    # VIZROCK_CONFIG_DIR keeps the tests off the live show config — running them on
    # the Pi would otherwise write to the scenes file the set depends on.
    CONFIG_DIR = Path(os.environ.get('VIZROCK_CONFIG_DIR') or REPO_DIR / 'configs')
    WEB_DIR = PACKAGE_DIR / 'interface' / 'web'


class Files:
    SHOW_CONFIG_FILE = Directories.CONFIG_DIR / 'show_config.json'
    SCENES_FILE = Directories.CONFIG_DIR / 'scenes.json'


def ensure_seeded(path):
    """
    Copy the committed .example alongside `path` if `path` is missing.

    The live configs are deliberately untracked: the UI rewrites them at runtime, and
    a tracked file carrying local edits makes `git pull` fail — which would break the
    self-update button the first time anyone edited a scene.
    """
    if not path.exists():
        example = path.with_name(f'{path.stem}.example.json')
        if example.exists():
            path.write_text(example.read_text())
    return path
