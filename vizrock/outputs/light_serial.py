#!/usr/bin/python3
#
# @file    light_serial.py
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

from vizrock.outputs.output import Output

logger = logging.getLogger(__name__)

REBROADCAST_INTERVAL_SECONDS = 0.25
USB_SERIAL_KEYWORDS = ('CP210', 'CH340', 'USB', 'ESP')


class LightSerial(Output):
    """
    Owns a background thread that keeps the port open and re-broadcasts the latest
    payload every ~250ms, so a dropped ESP-NOW packet self-heals on the next tick.
    apply() only updates the payload — instant, never blocks the dispatch path.
    """

    name = 'lights'

    def __init__(self, port='auto', baud=115200, **_):
        # Every other output validates here and raises; the factory turns that into a
        # visible rejection and refuses to persist the edit. This one validated nothing,
        # which is how `"port": null` reached the running system and sat on `retrying`
        # forever. A null or empty port is legitimate and means auto-detect; anything
        # that is not a string is a mistake worth refusing.
        if port is not None and not isinstance(port, str):
            raise ValueError(f'port must be a string or null, got {port!r}')
        if not isinstance(baud, int) or isinstance(baud, bool) or not 1200 <= baud <= 2000000:
            raise ValueError(f'baud out of range: {baud!r}')
        self.port_hint = port
        self.baud = baud
        self.latest_payload = 'LIGHT 0 off 0 0 0\n'   # one line per group, joined
        self.serial_port = None
        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def apply(self, scene):
        """
        One LIGHT line per peripheral group, sent together every tick.

        The brain resolves `lights` to {group: dict} — every configured group gets a
        line, so a node matching its group exactly is addressed once and only once.
        """
        lights = scene.get('lights')
        if not isinstance(lights, dict) or not lights:
            lights = {0: {'mode': 'off'}}
        self.latest_payload = ''.join(
            'LIGHT {} {} {} {} {} {}\n'.format(
                group, light.get('mode', 'off'), light.get('hue', 0),
                light.get('bright', 0), light.get('speed', 0), _palette(light))
            for group, light in sorted(lights.items()))

    def status(self):
        return 'ok' if self.serial_port and self.serial_port.is_open else 'retrying'

    def address_label(self):
        if self.serial_port and self.serial_port.is_open:
            return self.serial_port.port
        return f'{self.port_hint or "auto"} (searching)'

    def close(self):
        self.is_running = False
        if self.serial_port:
            self.serial_port.close()

    def _find_port(self):
        # A null or empty port means "find it", not "use nothing". Treating null as an
        # explicit path made the output sit on `retrying` forever with a transmitter
        # plugged in and working — the one symptom indistinguishable from dead hardware.
        if self.port_hint and self.port_hint != 'auto':
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


def _palette(light):
    """
    The palette field of a LIGHT line: '-', 'random', or up to five hues.

    Scatter modes take their colour from here rather than from `hue`. Anything
    unparseable degrades to '-' (the scene's own hue) rather than raising — this
    runs in the dispatch path, and a malformed colour list must not stop the show.
    """
    colors = light.get('colors')
    if colors == 'random':
        return 'random'
    if not isinstance(colors, (list, tuple)) or not colors:
        return '-'
    hues = [int(c) & 0xFF for c in colors[:5] if isinstance(c, (int, float))]
    return ','.join(str(h) for h in hues) if hues else '-'
