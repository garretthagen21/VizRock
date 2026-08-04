#!/usr/bin/python3
#
# @file    __main__.py
#
# @brief   Console entrypoints for the show brain
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import asyncio
import logging
import signal

import show_brain.configurations.logger  # configures logging on import
from show_brain.configurations.settings import show_settings
from show_brain.interface.ui_server import UiServer
from show_brain.managers.midi_interface import MidiInterface
from show_brain.outputs import build_outputs
from show_brain.show_brain import ShowBrain

logger = logging.getLogger(__name__)


async def _serve():
    brain = ShowBrain()
    loop = asyncio.get_running_loop()
    brain.outputs = build_outputs()
    brain.ui_server = UiServer(brain)
    await brain.ui_server.start(show_settings.ui_port)

    # hop from the MIDI thread onto the asyncio loop before touching state
    midi = MidiInterface(lambda action, scene: loop.call_soon_threadsafe(brain.handle, action, scene))
    midi.open()

    brain.push_state()

    stop = asyncio.Event()
    for received in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(received, stop.set)
    logger.info('show brain up. LIVE=%s ARMED=%s', brain.live, brain.armed)
    await stop.wait()

    midi.close()
    for output in brain.outputs:
        output.close()


def run():
    asyncio.run(_serve())


if __name__ == '__main__':
    run()
