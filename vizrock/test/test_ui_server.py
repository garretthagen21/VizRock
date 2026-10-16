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
    _addresses_are_reported()
    asyncio.run(_first_snapshot_carries_the_build())


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


def _addresses_are_reported():
    """The UI must be able to tell you where to point a phone."""
    import vizrock.utilities.system as vizrock_system

    assert isinstance(vizrock_system.hostname(), str) and vizrock_system.hostname()
    addresses = vizrock_system.local_addresses()
    assert isinstance(addresses, list), addresses
    assert all(':' not in a for a in addresses), 'ipv6 should be filtered out'

    # cached: a state push happens on every ARM move, so this must not fork per call
    before = vizrock_system._cache['at']
    vizrock_system.local_addresses()
    assert vizrock_system._cache['at'] == before or not addresses, 'result was not cached'


async def _first_snapshot_carries_the_build():
    """
    The snapshot sent on connect must carry the UI stamp too.

    Only broadcasts did, so a kiosk sitting idle through a deploy took its first stamp
    from the *new* build and never reloaded the old page it was still showing.
    """
    import json

    class _Brain:
        def snapshot(self):
            return {'type': 'state'}

    class _Socket(_Client):
        async def prepare(self, request):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    import vizrock.interface.ui_server as module
    server = UiServer.__new__(UiServer)
    server.brain, server.clients = _Brain(), set()
    socket = _Socket()
    real = module.web.WebSocketResponse
    module.web.WebSocketResponse = lambda: socket
    try:
        await server._websocket(None)
    finally:
        module.web.WebSocketResponse = real
    assert 'ui_build' in json.loads(socket.sent[0]), socket.sent[0]

