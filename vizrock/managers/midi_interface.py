#!/usr/bin/python3
#
# @file    midi_interface.py
#
# @brief   MIDI intake; matches incoming messages to show actions
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging

import mido

from vizrock.configurations.settings import vizrock_settings

logger = logging.getLogger(__name__)


class MidiInterface:
    """
    Opens every configured MIDI input and routes matched triggers to a handler.
    Messages arrive on a rtmidi callback thread, so the handler is responsible
    for hopping back onto the asyncio loop before touching state.
    """

    def __init__(self, handler):
        self.handler = handler
        self.open_ports = []

    def open(self):
        wanted = vizrock_settings.midi_inputs
        for name in mido.get_input_names():
            if wanted and not any(w.lower() in name.lower() for w in wanted):
                continue
            try:
                self.open_ports.append(
                    mido.open_input(name, callback=lambda m, n=name: self._on_message(m, n)))
                logger.info('listening on MIDI: %s', name)
            except Exception as error:
                logger.warning('could not open %s: %s', name, error)
        if not self.open_ports:
            logger.warning('no MIDI inputs open — UI still works, footswitches will not')

    def close(self):
        for port in self.open_ports:
            port.close()

    def match_trigger(self, message):
        """Return (action, scene) for an incoming mido message, or None."""
        for trigger in vizrock_settings.triggers:
            midi = trigger['midi']
            kind = midi['kind']
            if kind == 'note' and message.type == 'note_on' \
                    and message.note == midi['note'] and message.velocity > 0:
                return trigger['do'], trigger.get('scene')
            if kind == 'pc' and message.type == 'program_change' \
                    and message.program == midi['program']:
                return trigger['do'], trigger.get('scene')
            if kind == 'cc' and message.type == 'control_change' \
                    and message.control == midi['cc'] \
                    and message.value == midi.get('value', message.value):
                return trigger['do'], trigger.get('scene')
        return None

    def _on_message(self, message, source=''):
        match = self.match_trigger(message)
        if not match:
            return
        action, scene = match
        logger.info('MIDI %s (%s) -> %s', message, source, action)
        self.handler(action, scene)
