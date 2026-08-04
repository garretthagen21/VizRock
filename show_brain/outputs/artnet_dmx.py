#!/usr/bin/python3
#
# @file    artnet_dmx.py
#
# @brief   Art-Net DMX output; cues are named channel maps
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging
import socket

from show_brain.outputs.output import Output

logger = logging.getLogger(__name__)

ARTNET_PORT = 0x1936
DMX_FRAME_SIZE = 512


class ArtNetDmx(Output):
    """An unknown or missing cue resolves to an all-zero frame, so a typo blacks out."""

    name = 'dmx'

    def __init__(self, host, universe=0, cues=None, **_):
        self.address = (host, ARTNET_PORT)
        self.universe = universe
        self.cues = cues or {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def apply(self, scene):
        cue = (scene.get('dmx') or {}).get('cue', 'off')
        frame = bytearray(DMX_FRAME_SIZE)
        for channel, value in self.cues.get(cue, {}).items():
            frame[int(channel) - 1] = max(0, min(255, int(value)))
        self._send(frame)

    def close(self):
        self.socket.close()

    def _send(self, frame):
        packet = b'Art-Net\x00' + (0x5000).to_bytes(2, 'little') + b'\x00\x0e'
        packet += b'\x00\x00' + bytes([self.universe & 0xff, (self.universe >> 8) & 0xff])
        packet += len(frame).to_bytes(2, 'big') + bytes(frame)
        try:
            self.socket.sendto(packet, self.address)
        except OSError as error:
            logger.warning('artnet send failed: %s', error)
