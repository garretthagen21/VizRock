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

import json
import logging

from aiohttp import WSMsgType, web

import vizrock.constants.paths as show_paths

logger = logging.getLogger(__name__)


class UiServer:
    """
    server -> client : {type:'state', live, armed, outputs, scenes, ...}
    client -> server : {type:'action', action:'go'|'arm_next'|..., scene?}
                       {type:'edit_scene', scene:{...}}
                       {type:'edit_config', name:'resolume', spec:{...}}
    """

    def __init__(self, brain):
        self.brain = brain
        self.clients = set()
        self.app = web.Application()
        self.app.add_routes([
            web.get('/ws', self._websocket),
            web.get('/', lambda request: web.HTTPFound('/index.html')),
            web.static('/', show_paths.Directories.WEB_DIR),
        ])

    async def start(self, port):
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', port).start()
        logger.info('UI on http://0.0.0.0:%s  (open :%s from your phone)', port, port)

    def broadcast(self, snapshot):
        payload = json.dumps(snapshot)
        for client in list(self.clients):
            try:
                client.send_str(payload)
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
