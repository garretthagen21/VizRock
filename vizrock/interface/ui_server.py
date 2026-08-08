#!/usr/bin/python3
#
# @file    ui_server.py
#
# @brief   Serves the web UI and streams live state over websocket
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import asyncio
import json
import logging

from aiohttp import WSMsgType, web

import vizrock.constants.paths as vizrock_paths

logger = logging.getLogger(__name__)


class UiServer:
    """
    server -> client : {type:'state', live, armed, outputs, scenes, ...}
    client -> server : {type:'action', action:'go'|'arm_next'|..., scene?}
                       {type:'edit_scene', scene:{...}}
                       {type:'edit_config', name:'resolume', spec:{...}}
                       {type:'update', to:'<sha>'}
    """

    def __init__(self, brain):
        self.brain = brain
        self.clients = set()
        self.app = web.Application()
        self.app.add_routes([
            web.get('/ws', self._websocket),
            web.get('/', lambda request: web.HTTPFound('/index.html')),
            web.static('/', vizrock_paths.Directories.WEB_DIR),
        ])

    async def start(self, port):
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', port).start()
        logger.info('UI on http://0.0.0.0:%s  (open :%s from your phone)', port, port)

    def broadcast(self, snapshot):
        """
        send_str is a coroutine, so calling it from this synchronous caller only
        creates one — it has to be scheduled on the loop or nothing is ever sent.
        push_state is sync by design, so scheduling is the only option.
        """
        payload = json.dumps(snapshot)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                                  # no loop (tests) — nothing to send on
        for client in list(self.clients):
            loop.create_task(self._send(client, payload))

    async def _send(self, client, payload):
        try:
            await client.send_str(payload)
        except Exception:
            self.clients.discard(client)

    async def _websocket(self, request):
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        self.clients.add(websocket)
        await websocket.send_str(json.dumps(self.brain.snapshot()))
        try:
            async for message in websocket:
                if message.type != WSMsgType.TEXT:
                    continue
                self._handle_message(json.loads(message.data))
        finally:
            self.clients.discard(websocket)
        return websocket

    def _handle_message(self, data):
        if data.get('type') == 'action':
            self.brain.handle(data['action'], data.get('scene'))
        elif data.get('type') == 'edit_scene':
            self.brain.scene_library.upsert(data['scene'])
            self.brain.push_state()
        elif data.get('type') == 'edit_config':
            self.brain.apply_output_config(data['name'], data['spec'])
        elif data.get('type') == 'update' and self.brain.updater:
            started, message = self.brain.updater.apply(data.get('to'))
            logger.info('update requested: %s', message)
            if not started:
                self.brain.updater.message = message
                self.brain.push_state()
