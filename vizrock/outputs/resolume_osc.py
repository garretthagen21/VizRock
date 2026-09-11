#!/usr/bin/python3
#
# @file    resolume_osc.py
#
# @brief   OSC output driving Resolume clip playback
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging
import socket
import struct
import threading
import time

from vizrock.outputs.output import Output

logger = logging.getLogger(__name__)

RESOLVE_INTERVAL_SECONDS = 15


def _valid_port(port):
    port = int(port)                       # rejects '' and 'nope'; accepts '7000'
    if not 1 <= port <= 65535:
        raise ValueError(f'port out of range: {port}')
    return port


class ResolumeOsc(Output):
    """
    Fire-and-forget UDP OSC to every configured host — typically THC's machine plus
    a local laptop for testing. Nothing listening means packets harmlessly vanish,
    so an absent target costs nothing and needs no switching.

    Hosts may be IPs or mDNS names ('my-laptop.local'). Names matter on a direct
    ethernet cable, where both ends take random link-local 169.254.x.x addresses
    that cannot be hardcoded.

    A name that resolves to several addresses — a laptop on both a cable and WiFi —
    is cued on all of them. The OSC verbs are idempotent, so the duplicate costs one
    UDP packet and buys automatic failover if the cable is pulled mid-show.
    """

    name = 'resolume'

    def __init__(self, hosts, port, **_):
        # validate here: the factory turns a raise into a rejection, and a live
        # config edit is only persisted if the output actually came up
        if isinstance(hosts, str) or not isinstance(hosts, (list, tuple)) or not hosts:
            raise ValueError(f'hosts must be a non-empty list, got {hosts!r}')
        if not all(isinstance(host, str) and host.strip() for host in hosts):
            raise ValueError(f'every host must be a non-empty string, got {hosts!r}')
        self.hosts = [host.strip() for host in hosts]
        self.port = _valid_port(port)
        self.resolved = {}
        self.connected = None    # (layer, clip) currently playing                 # host -> [(ip, port), ...]
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_running = True
        self.thread = threading.Thread(target=self._resolve_loop, daemon=True)
        self.thread.start()

    def apply(self, scene):
        """
        Connect the scene's clip, but only when it is not the one already playing.

        `/connect` on a running clip restarts it from the top, and the brain
        re-dispatches on far more than scene changes — every light-step advance,
        every burst, every color cycle. Without this guard a scene whose lights
        step every 12 seconds would restart its video every 12 seconds.

        It also makes sharing a clip free: several scenes can point at one video and
        differ only in their lights, and moving between them leaves the video running.
        `restart_scene` is the one thing that re-fires it deliberately.
        """
        resolume = scene.get('resolume')
        if not resolume:
            return
        if resolume.get('clear'):
            self._send('/composition/disconnectall', 1)
            self.connected = None
            return
        target = (resolume['layer'], resolume['clip'])
        if target == self.connected and not scene.get('restart'):
            return
        self.connected = target
        self._send(f"/composition/layers/{target[0]}/clips/{target[1]}/connect", 1)

    def silence(self):
        """Disconnect everything, so muting the output leaves a black screen."""
        self._send('/composition/disconnectall', 1)
        self.connected = None

    def status(self):
        # nothing resolved means we cannot even address a target — say so
        return 'ready' if self.resolved else 'retrying'

    def address_label(self):
        return ', '.join(
            f"{host}→{'+'.join(ip for ip, _ in self.resolved[host])}"
            if host in self.resolved else f'{host} (unresolved)'
            for host in self.hosts)

    def close(self):
        self.is_running = False
        self.socket.close()

    def _resolve_loop(self):
        """
        Names are resolved here, never in apply() — a blocking mDNS lookup in the
        dispatch path would stall GO. A host that stops resolving keeps its last
        known address rather than disappearing mid-show.
        """
        reported = set()
        while self.is_running:
            for host in self.hosts:
                try:
                    info = socket.getaddrinfo(host, self.port, socket.AF_INET, socket.SOCK_DGRAM)
                    addresses = list(dict.fromkeys(entry[4] for entry in info))
                    if self.resolved.get(host) != addresses:
                        logger.info('resolved %s to %s', host, ', '.join(ip for ip, _ in addresses))
                    self.resolved[host] = addresses
                    reported.discard(host)      # recovered: a later failure must warn again
                except OSError as error:
                    # report the transition, not the state — a typo'd name would
                    # otherwise warn on every pass for the length of the show
                    if host not in reported:
                        logger.warning('cannot resolve %s: %s', host, error)
                        reported.add(host)
            time.sleep(RESOLVE_INTERVAL_SECONDS)

    def send_messages(self, messages, repeat=1):
        """
        Send arbitrary OSC, for effect parameters and anything else Resolume exposes.

        `repeat` exists because OSC is fire-and-forget: an effect left on because its
        reset packet was dropped is a stuck visual for the rest of the song, and the
        lights' 250ms heartbeat has no equivalent here. Repeating a reset costs three
        UDP packets and removes the failure mode.
        """
        for _ in range(max(1, repeat)):
            for message in messages or ():
                address = message.get('address')
                if not address:
                    continue
                self._send(address, message.get('value', 1))
                logger.info('osc %s %s', address, message.get('value', 1))

    def _send(self, path, argument):
        """
        Minimal OSC 1.0 encoder: address, typetag, one argument.

        Floats matter — Resolume's effect parameters are 0.0-1.0, and sending an int
        where a float is expected is silently ignored rather than rejected.
        """
        def pad(raw):
            return raw + b'\x00' * (4 - len(raw) % 4)

        if isinstance(argument, float):
            message = pad(path.encode()) + pad(b',f') + struct.pack('>f', argument)
        else:
            message = pad(path.encode()) + pad(b',i') + int(argument).to_bytes(4, 'big', signed=True)
        for addresses in list(self.resolved.values()):
            for address in addresses:
                try:
                    self.socket.sendto(message, address)
                except OSError as error:
                    logger.warning('osc send to %s failed: %s', address, error)
