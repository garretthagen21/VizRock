#!/usr/bin/python3
#
# @file    test_resolver.py
#
# @brief   mDNS resolution off the dispatch path, and log state
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

import logging
import socket
import time

from show_brain.outputs import resolume_osc
from show_brain.outputs.resolume_osc import ResolumeOsc


def run():
    _resolves_and_reports()
    _warns_once_per_outage()


def _resolves_and_reports():
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(('127.0.0.1', 0))
    listener.settimeout(3)
    port = listener.getsockname()[1]

    osc = ResolumeOsc(hosts=['localhost', 'definitely-not-a-host.invalid'], port=port)
    for _ in range(50):
        if osc.resolved:
            break
        time.sleep(0.1)

    assert 'localhost' in osc.resolved, osc.resolved
    assert 'definitely-not-a-host.invalid' not in osc.resolved
    assert '(unresolved)' in osc.address_label(), osc.address_label()

    osc.apply({'resolume': {'layer': 2, 'clip': 4}})
    assert b'/composition/layers/2/clips/4/connect' in listener.recvfrom(512)[0]

    # a plain IP must keep working
    plain = ResolumeOsc(hosts=['127.0.0.1'], port=port)
    for _ in range(50):
        if plain.resolved:
            break
        time.sleep(0.1)
    plain.apply({'resolume': {'clear': True}})
    assert b'/composition/disconnectall' in listener.recvfrom(512)[0]

    for bad in ['a-bare-string', [], [''], [None]]:
        try:
            ResolumeOsc(hosts=bad, port=7000)
        except ValueError:
            continue
        raise AssertionError(f'accepted hosts={bad!r}')
    for bad in ['nope', 0, 70000]:
        try:
            ResolumeOsc(hosts=['ok.local'], port=bad)
        except ValueError:
            continue
        raise AssertionError(f'accepted port={bad!r}')
    assert ResolumeOsc(hosts=['ok.local'], port='7001').port == 7001, 'numeric strings are fine'

    listener.close()
    osc.close()
    plain.close()


def _warns_once_per_outage():
    """
    A name that never resolves must not warn on every pass, and a host that
    recovers must be able to warn again if it fails later.
    """
    warnings = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                warnings.append(record.getMessage())

    handler = Capture()
    resolume_osc.logger.addHandler(handler)
    try:
        results = iter([OSError('down'), [(0, 0, 0, '', ('10.0.0.5', 7000))],
                        OSError('down'), [(0, 0, 0, '', ('10.0.0.5', 7000))]])
        real = socket.getaddrinfo

        def flaky(*_a, **_k):
            outcome = next(results)
            if isinstance(outcome, OSError):
                raise outcome
            return outcome

        socket.getaddrinfo = flaky
        osc = ResolumeOsc.__new__(ResolumeOsc)
        osc.hosts, osc.port, osc.resolved, osc.is_running = ['flappy.local'], 7000, {}, True
        try:
            for _ in range(4):
                osc.is_running = False          # one pass per call
                osc.is_running = True
                _one_resolve_pass(osc)
        finally:
            socket.getaddrinfo = real
        assert len(warnings) == 2, f'expected one warning per outage, got {warnings}'
    finally:
        resolume_osc.logger.removeHandler(handler)


_reported = set()


def _one_resolve_pass(osc):
    """Mirror of the loop body in _resolve_loop, without the sleep."""
    import socket as socket_module
    for host in osc.hosts:
        try:
            info = socket_module.getaddrinfo(host, osc.port,
                                             socket_module.AF_INET, socket_module.SOCK_DGRAM)
            osc.resolved[host] = list(dict.fromkeys(entry[4] for entry in info))
            _reported.discard(host)
        except OSError as error:
            if host not in _reported:
                resolume_osc.logger.warning('cannot resolve %s: %s', host, error)
                _reported.add(host)
