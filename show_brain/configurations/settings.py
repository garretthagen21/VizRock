#!/usr/bin/python3
#
# @file    settings.py
#
# @brief   Show configuration; singleton show_settings
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import json

import show_brain.constants.paths as show_paths


class ShowSettings:
    """Read-only view of show_config.json."""

    def __init__(self):
        config = json.loads(show_paths.Files.SHOW_CONFIG_FILE.read_text())
        self.ui_port = config.get('ui', {}).get('port', 8080)
        self.midi_inputs = config.get('midi_inputs', [])
        self.triggers = config.get('triggers', [])
        self.outputs = config.get('outputs', {})


show_settings = ShowSettings()
