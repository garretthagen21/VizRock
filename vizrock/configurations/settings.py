#!/usr/bin/python3
#
# @file    settings.py
#
# @brief   Show configuration; singleton vizrock_settings
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import json
import logging

import vizrock.constants.paths as vizrock_paths

logger = logging.getLogger(__name__)


class VizRockSettings:
    """
    show_config.json, editable at runtime. The raw document is kept so unknown
    keys survive a round-trip — we only ever rewrite what the UI edited.
    """

    def __init__(self):
        self.raw = json.loads(vizrock_paths.ensure_seeded(vizrock_paths.Files.SHOW_CONFIG_FILE).read_text())
        ui = self.raw.get('ui', {})
        self.ui_port = ui.get('port', 8080)
        # tapping a cue arms it by default; firing straight away is opt-in
        self.tap_fires = bool(ui.get('tap_fires', False))
        self.midi_inputs = self.raw.get('midi_inputs', [])
        self.triggers = self.raw.get('triggers', [])
        self.outputs = self.raw.setdefault('outputs', {})

    def set_tap_fires(self, value):
        self.tap_fires = bool(value)
        self.raw.setdefault('ui', {})['tap_fires'] = self.tap_fires
        self.save()

    def update_output(self, name, spec):
        """Merge into one output. The caller must rebuild it for this to take effect."""
        self.outputs.setdefault(name, {}).update(spec)

    def save(self):
        vizrock_paths.Files.SHOW_CONFIG_FILE.write_text(json.dumps(self.raw, indent=2))
        logger.info('show_config.json saved')


vizrock_settings = VizRockSettings()
