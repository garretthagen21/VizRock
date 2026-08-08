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

from pathlib import Path


class Directories:
    PACKAGE_DIR = Path(__file__).parents[1]
    REPO_DIR = PACKAGE_DIR.parent
    CONFIG_DIR = REPO_DIR / 'configs'
    WEB_DIR = PACKAGE_DIR / 'interface' / 'web'


class Files:
    SHOW_CONFIG_FILE = Directories.CONFIG_DIR / 'show_config.json'
    SCENES_FILE = Directories.CONFIG_DIR / 'scenes.json'
