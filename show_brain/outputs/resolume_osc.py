#!/usr/bin/python3
#
# @file    resolume_osc.py
#
# @brief   OSC output driving Resolume clip playback
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging
import socket

from show_brain.outputs.output import Output

logger = logging.getLogger(__name__)


class ResolumeOsc(Output):
    """Fire-and-forget UDP OSC. Nothing listening means packets harmlessly vanish."""

    name = 'resolume'

    def __init__(self, host, port, **_):
        self.address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def apply(self, scene):
        resolume = scene.get('resolume')
        if not resolume:
            return
        if resolume.get('clear'):
            self._send('/composition/disconnectall', 1)
        else:
            self._send(f"/composition/layers/{resolume['layer']}/clips/{resolume['clip']}/connect", 1)

    def close(self):
        self.socket.close()

    def _send(self, path, argument):
        """Minimal OSC 1.0 encoder: address + ',i' typetag + int32 argument."""
        def pad(raw):
            return raw + b'\x00' * (4 - len(raw) % 4)

        message = pad(path.encode()) + pad(b',i') + int(argument).to_bytes(4, 'big', signed=True)
        try:
            self.socket.sendto(message, self.address)
        except OSError as error:
            logger.warning('osc send failed: %s', error)
