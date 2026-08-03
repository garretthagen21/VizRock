"""
UI server: serves the web app and a websocket. The websocket streams live state
to every connected browser (laptop + phone stay in sync) and accepts edits +
actions back. The scene table is saved to scenes.json on every edit so it
survives a reboot.

Protocol:
  server -> client : {type:"state", live, armed, outputs, scenes, ...}
  client -> server : {type:"action", action:"go"|"arm_next"|... , scene?}
                     {type:"edit_scene", scene:{...}}   # upsert one scene
"""
import json
import logging
from pathlib import Path

from aiohttp import web, WSMsgType

log = logging.getLogger("server")
WEB = Path(__file__).parent / "web"


class UIServer:
    def __init__(self, brain):
        self.brain = brain
        self.clients = set()
        self.app = web.Application()
        self.app.add_routes([
            web.get("/ws", self._ws),
            web.get("/", lambda r: web.HTTPFound("/index.html")),
            web.static("/", WEB),
        ])

    async def start(self, port):
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        log.info("UI on http://0.0.0.0:%s  (open :%s from your phone)", port, port)

    def broadcast(self, snap: dict):
        dead = []
        for ws in self.clients:
            try:
                ws.send_str(json.dumps(snap))    # aiohttp allows sync enqueue
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps(self.brain.snapshot()))   # prime on connect
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data.get("type") == "action":
                    self.brain.handle(data["action"], data.get("scene"))
                elif data.get("type") == "edit_scene":
                    s = data["scene"]
                    self.brain.scenes[s["id"]] = s
                    self.brain.load_scenes({"meta": self.brain.meta,
                                            "scenes": list(self.brain.scenes.values())})
                    self.brain.save_scenes()
                    self.brain._push_state()
        finally:
            self.clients.discard(ws)
        return ws
