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
    """
    I2C OLED. Absent panel degrades to a no-op so the brain runs on a dev machine.

    driver/address are configurable because the cheap modules vary: 0.96" panels are
    usually SSD1306 at 0x3C, while many 1.3" ones are SH1106, and some boards strap
    0x3D. Getting the wrong one is a config change, not a re-order.
    """

    name = 'oled'

    def __init__(self, width=128, height=64, driver='ssd1306', address=0x3C, **_):
        self.is_available = False
        self.address = int(address, 0) if isinstance(address, str) else int(address)
        self.driver = driver
        try:
            from luma.core.interface.serial import i2c
            import luma.oled.device
            from PIL import ImageFont

            device_class = getattr(luma.oled.device, driver)
            self.device = device_class(i2c(port=1, address=self.address),
                                       width=width, height=height)
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
        return f'i2c {self.address:#04x} {self.driver}'

    def _label(self, snapshot, scene_id):
        for scene in snapshot['scenes']:
            if scene['id'] == scene_id:
                return f"{scene_id:02d} {scene['name'][:14]}"
        return '—'

    def _status_line(self, outputs):
        return '  '.join(f"{label}{STATUS_SYMBOLS.get(outputs.get(key, 'off'), '.')}"
                         for key, label in OUTPUT_LABELS)
