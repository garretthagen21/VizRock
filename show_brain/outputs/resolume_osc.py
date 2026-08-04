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
import threading
import time

from show_brain.outputs.output import Output

logger = logging.getLogger(__name__)

RESOLVE_INTERVAL_SECONDS = 15


class ResolumeOsc(Output):
    """
    Fire-and-forget UDP OSC to every configured host — typically THC's machine plus
    a local laptop for testing. Nothing listening means packets harmlessly vanish,
    so an absent target costs nothing and needs no switching.

    Hosts may be IPs or mDNS names ('my-laptop.local'). Names matter on a direct
    ethernet cable, where both ends take random link-local 169.254.x.x addresses
    that cannot be hardcoded.
    """

    name = 'resolume'

    def __init__(self, hosts, port, **_):
        self.hosts = list(hosts)
        self.port = port
        self.resolved = {}                 # host -> (ip, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_running = True
        self.thread = threading.Thread(target=self._resolve_loop, daemon=True)
        self.thread.start()

    def apply(self, scene):
        resolume = scene.get('resolume')
        if not resolume:
            return
        if resolume.get('clear'):
            self._send('/composition/disconnectall', 1)
        else:
            self._send(f"/composition/layers/{resolume['layer']}/clips/{resolume['clip']}/connect", 1)

    def status(self):
        # nothing resolved means we cannot even address a target — say so
        return 'sending' if self.resolved else 'retrying'

    def address_label(self):
        return ', '.join(
            f'{host}→{self.resolved[host][0]}' if host in self.resolved else f'{host} (unresolved)'
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
                    was_missing = host not in self.resolved
                    self.resolved[host] = info[0][4]
                    if host in reported or was_missing:
                        logger.info('resolved %s to %s', host, self.resolved[host][0])
                        reported.discard(host)
                except OSError as error:
                    # report the transition, not the state — a typo'd name would
                    # otherwise warn on every pass for the length of the show
                    if host not in reported:
                        logger.warning('cannot resolve %s: %s', host, error)
                        reported.add(host)
            time.sleep(RESOLVE_INTERVAL_SECONDS)

    def _send(self, path, argument):
        """Minimal OSC 1.0 encoder: address + ',i' typetag + int32 argument."""
        def pad(raw):
            return raw + b'\x00' * (4 - len(raw) % 4)

        message = pad(path.encode()) + pad(b',i') + int(argument).to_bytes(4, 'big', signed=True)
        for address in list(self.resolved.values()):
            try:
                self.socket.sendto(message, address)
            except OSError as error:
                logger.warning('osc send to %s failed: %s', address, error)
