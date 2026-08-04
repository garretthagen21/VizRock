#!/usr/bin/python3
#
# @file    ring_serial.py
#
# @brief   Serial link to the USB to ESP-NOW ring transmitter
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging
import threading
import time

from show_brain.outputs.output import Output

logger = logging.getLogger(__name__)

REBROADCAST_INTERVAL_SECONDS = 0.25
USB_SERIAL_KEYWORDS = ('CP210', 'CH340', 'USB', 'ESP')


class RingSerial(Output):
    """
    Owns a background thread that keeps the port open and re-broadcasts the latest
    payload every ~250ms, so a dropped ESP-NOW packet self-heals on the next tick.
    apply() only updates the payload — instant, never blocks the dispatch path.
    """

    name = 'rings'

    def __init__(self, port='auto', baud=115200, **_):
        self.port_hint = port
        self.baud = baud
        self.latest_payload = 'RING off 0 0 0\n'
        self.serial_port = None
        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def apply(self, scene):
        ring = scene.get('ring') or {'mode': 'off'}
        self.latest_payload = 'RING {} {} {} {}\n'.format(
            ring.get('mode', 'off'), ring.get('hue', 0),
            ring.get('bright', 0), ring.get('speed', 0))

    def status(self):
        return 'ok' if self.serial_port and self.serial_port.is_open else 'retrying'

    def address_label(self):
        if self.serial_port and self.serial_port.is_open:
            return self.serial_port.port
        return f'{self.port_hint} (searching)'

    def close(self):
        self.is_running = False
        if self.serial_port:
            self.serial_port.close()

    def _find_port(self):
        if self.port_hint != 'auto':
            return self.port_hint
        import serial.tools.list_ports

        for port in serial.tools.list_ports.comports():
            if any(keyword in (port.description or '') for keyword in USB_SERIAL_KEYWORDS):
                return port.device
        return None

    def _run(self):
        try:
            import serial
        except ImportError as error:
            # match the other outputs: degrade to a no-op rather than killing the thread
            logger.warning('pyserial not available (%s) — ring output disabled', error)
            self.is_running = False
            return

        while self.is_running:
            if not (self.serial_port and self.serial_port.is_open):
                device = self._find_port()
                if not device:
                    time.sleep(1)
                    continue
                try:
                    self.serial_port = serial.Serial(device, self.baud, timeout=1)
                    logger.info('ring transmitter on %s', device)
                except Exception as error:
                    logger.warning('ring open failed: %s', error)
                    time.sleep(1)
                    continue
            try:
                self.serial_port.write(self.latest_payload.encode())
            except Exception as error:
                logger.warning('ring write failed, will reconnect: %s', error)
                try:
                    self.serial_port.close()
                except Exception:
                    pass
                self.serial_port = None
            time.sleep(REBROADCAST_INTERVAL_SECONDS)
