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

import vizrock.configurations.logger  # configures logging on import
from vizrock.configurations.settings import show_settings
from vizrock.interface.ui_server import UiServer
from vizrock.managers.midi_interface import MidiInterface
from vizrock.outputs import build_outputs
from vizrock.brain import ShowBrain

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
