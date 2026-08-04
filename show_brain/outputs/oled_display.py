#!/usr/bin/python3
#
# @file    oled_display.py
#
# @brief   Pedalboard OLED readout of LIVE, NEXT and output health
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging

from show_brain.outputs.output import Output

logger = logging.getLogger(__name__)

STATUS_SYMBOLS = {'ok': '*', 'sending': '>', 'retrying': '?', 'off': '.'}
OUTPUT_LABELS = (('resolume', 'VIS'), ('dmx', 'DMX'), ('rings', 'RNG'))


class OledDisplay(Output):
    """I2C SSD1306. Absent panel degrades to a no-op so the brain runs on a dev machine."""

    name = 'oled'

    def __init__(self, width=128, height=64, **_):
        self.is_available = False
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            from PIL import ImageFont

            self.device = ssd1306(i2c(port=1, address=0x3C), width=width, height=height)
            self.font = ImageFont.load_default()
            self.is_available = True
        except Exception as error:
            logger.warning('OLED not available (%s) — running headless', error)

    def on_state(self, snapshot):
        if not self.is_available:
            return
        from luma.core.render import canvas

        with canvas(self.device) as draw:
            draw.text((0, 0), f"LIVE {self._label(snapshot, snapshot['live'])}", font=self.font, fill=255)
            draw.text((0, 16), f"NEXT {self._label(snapshot, snapshot['armed'])}", font=self.font, fill=255)
            draw.text((0, 40), self._status_line(snapshot['outputs']), font=self.font, fill=255)

    def status(self):
        return 'ok' if self.is_available else 'off'

    def address_label(self):
        return 'i2c 0x3C'

    def _label(self, snapshot, scene_id):
        for scene in snapshot['scenes']:
            if scene['id'] == scene_id:
                return f"{scene_id:02d} {scene['name'][:14]}"
        return '—'

    def _status_line(self, outputs):
        return '  '.join(f"{label}{STATUS_SYMBOLS.get(outputs.get(key, 'off'), '.')}"
                         for key, label in OUTPUT_LABELS)
