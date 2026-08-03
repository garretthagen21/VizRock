"""
Output adapters. Every adapter has the same shape:

    apply(scene)      -> reflect a committed scene on this output (fired on GO)
    on_state(snap)    -> react to any state change (fired on ARM moves too)
    status()          -> "ok" | "retrying" | "off"
    close()

Most adapters only need one of apply/on_state; the base makes both no-ops.
UDP outputs (Resolume, Art-Net) are fire-and-forget and always report "ok" — if
nothing is listening the packets harmlessly vanish. The ring adapter is the one
real connection, so it owns a background thread that reconnects and re-broadcasts.
"""
import logging
import socket
import threading
import time

log = logging.getLogger("adapters")


class Output:
    name = "base"
    def apply(self, scene): ...
    def on_state(self, snap): ...
    def status(self): return "ok"
    def close(self): ...


# ---------------------------------------------------------------- Resolume (OSC)
class ResolumeOSC(Output):
    """UDP OSC to Resolume. /composition/layers/{L}/clips/{C}/connect 1"""
    name = "resolume"

    def __init__(self, host, port, **_):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def apply(self, scene):
        r = scene.get("resolume")
        if not r:
            return
        if r.get("clear"):
            self._send("/composition/disconnectall", 1)
        else:
            path = f"/composition/layers/{r['layer']}/clips/{r['clip']}/connect"
            self._send(path, 1)

    def _send(self, path, arg_int):
        # minimal OSC 1.0 encoder: address + ",i" typetag + int32 arg
        def pad(b): return b + b"\x00" * (4 - len(b) % 4)
        msg = pad(path.encode()) + pad(b",i") + int(arg_int).to_bytes(4, "big", signed=True)
        try:
            self.sock.sendto(msg, self.addr)
        except OSError as e:
            log.warning("osc send failed: %s", e)

    def close(self): self.sock.close()


# ---------------------------------------------------------------- DMX (Art-Net)
class ArtNetDMX(Output):
    """UDP Art-Net DMX. Cues are named channel maps in config."""
    name = "dmx"
    PORT = 0x1936

    def __init__(self, host, universe=0, cues=None, **_):
        self.addr = (host, self.PORT)
        self.universe = universe
        self.cues = cues or {}                 # {"warm_low": {1:180, 2:60}, ...}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def apply(self, scene):
        cue = (scene.get("dmx") or {}).get("cue", "off")
        levels = self.cues.get(cue, {})        # unknown/off -> all zero
        frame = bytearray(512)
        for ch, val in levels.items():
            frame[int(ch) - 1] = max(0, min(255, int(val)))
        self._send(frame)

    def _send(self, frame):
        hdr = b"Art-Net\x00" + (0x5000).to_bytes(2, "little") + b"\x00\x0e"
        hdr += b"\x00\x00" + bytes([self.universe & 0xff, (self.universe >> 8) & 0xff])
        hdr += (len(frame)).to_bytes(2, "big")
        try:
            self.sock.sendto(hdr + bytes(frame), self.addr)
        except OSError as e:
            log.warning("artnet send failed: %s", e)

    def close(self): self.sock.close()


# ---------------------------------------------------------------- Rings (serial)
class RingSerial(Output):
    """
    Serial line to the USB->ESP-NOW transmitter. Owns a background thread that:
      - keeps the port open, reopening it on a timer if it disappears
      - re-broadcasts the latest ring payload every ~250ms so a dropped
        ESP-NOW packet self-heals on the next tick
    apply() just updates the latest payload — instant, never blocks.
    """
    name = "rings"

    def __init__(self, port="auto", baud=115200, **_):
        self.port_hint = port
        self.baud = baud
        self._latest = "RING off 0 0 0\n"
        self._ser = None
        self._alive = True
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def apply(self, scene):
        r = scene.get("ring") or {"mode": "off"}
        self._latest = "RING {} {} {} {}\n".format(
            r.get("mode", "off"), r.get("hue", 0),
            r.get("bright", 0), r.get("speed", 0))

    def status(self):
        return "ok" if self._ser and self._ser.is_open else "retrying"

    def _find_port(self):
        import serial.tools.list_ports as lp
        if self.port_hint != "auto":
            return self.port_hint
        for p in lp.comports():
            if any(k in (p.description or "") for k in ("CP210", "CH340", "USB", "ESP")):
                return p.device
        return None

    def _run(self):
        import serial
        while self._alive:
            if not (self._ser and self._ser.is_open):
                dev = self._find_port()
                if dev:
                    try:
                        self._ser = serial.Serial(dev, self.baud, timeout=1)
                        log.info("ring transmitter on %s", dev)
                    except Exception as e:
                        log.warning("ring open failed: %s", e); time.sleep(1)
                else:
                    time.sleep(1); continue
            try:
                self._ser.write(self._latest.encode())     # heartbeat re-broadcast
            except Exception as e:
                log.warning("ring write failed, will reconnect: %s", e)
                try: self._ser.close()
                except Exception: pass
                self._ser = None
            time.sleep(0.25)

    def close(self):
        self._alive = False
        if self._ser: self._ser.close()


# ---------------------------------------------------------------- OLED display
class OledDisplay(Output):
    """
    Pedalboard readout. Subscribes to state (LIVE / ARMED / output dots) and
    renders on every change. If the panel isn't present it degrades to a no-op
    so the brain runs fine on a dev machine.  I2C SSD1306, 128x64.
    """
    name = "oled"

    def __init__(self, width=128, height=64, **_):
        self.ok = False
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            from PIL import ImageFont
            self.dev = ssd1306(i2c(port=1, address=0x3C), width=width, height=height)
            self.font = ImageFont.load_default()
            self.ok = True
        except Exception as e:
            log.warning("OLED not available (%s) — running headless", e)

    def on_state(self, snap):
        if not self.ok:
            return
        from luma.core.render import canvas
        live = self._label(snap, snap["live"], "—")
        nxt = self._label(snap, snap["armed"], "—")
        dots = snap["outputs"]
        with canvas(self.dev) as d:
            d.text((0, 0),  f"LIVE {live}", font=self.font, fill=255)
            d.text((0, 16), f"NEXT {nxt}", font=self.font, fill=255)
            d.text((0, 40), self._dotline(dots), font=self.font, fill=255)

    def _label(self, snap, sid, dflt):
        for s in snap["scenes"]:
            if s["id"] == sid:
                return f"{sid:02d} {s['name'][:14]}"
        return dflt

    def _dotline(self, outs):
        sym = {"ok": "*", "retrying": "?", "off": "."}
        keys = [("resolume", "VIS"), ("dmx", "DMX"), ("rings", "RNG")]
        return "  ".join(f"{lbl}{sym.get(outs.get(k,'off'),'.')}" for k, lbl in keys)

    def status(self):
        return "ok" if self.ok else "off"


# ---------------------------------------------------------------- factory
_KINDS = {"osc": ResolumeOSC, "artnet": ArtNetDMX,
          "serial": RingSerial, "oled": OledDisplay}

def build_adapters(cfg: dict):
    out = []
    for name, spec in cfg.items():
        if not spec.get("enabled", True):
            continue
        cls = _KINDS.get(spec["type"])
        if not cls:
            log.warning("unknown output type: %s", spec.get("type")); continue
        a = cls(**{k: v for k, v in spec.items() if k not in ("type", "enabled")})
        a.name = name
        out.append(a)
        log.info("adapter up: %s (%s)", name, spec["type"])
    return out
