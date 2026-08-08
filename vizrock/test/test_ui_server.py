#!/usr/bin/python3
#
# @file    test_ui_server.py
#
# @brief   Websocket broadcast actually reaches clients
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#


import asyncio

from vizrock.interface.ui_server import UiServer


class _Client:
    def __init__(self):
        self.sent = []

    async def send_str(self, payload):
        self.sent.append(payload)


class _DeadClient:
    async def send_str(self, payload):
        raise ConnectionResetError('gone')


def run():
    asyncio.run(_delivers())
    _outside_a_loop_is_safe()


async def _delivers():
    """
    send_str is a coroutine. The original code called it without awaiting, so
    every push after the initial snapshot silently went nowhere.
    """
    server = UiServer.__new__(UiServer)
    server.brain = None
    live, dead = _Client(), _DeadClient()
    server.clients = {live, dead}

    server.broadcast({'type': 'state', 'live': 3})
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert live.sent, 'nothing was delivered'
    assert '"live": 3' in live.sent[0], live.sent
    assert dead not in server.clients, 'a client that raised must be dropped'


def _outside_a_loop_is_safe():
    server = UiServer.__new__(UiServer)
    server.clients = {_Client()}
    server.broadcast({'x': 1})          # must not raise
