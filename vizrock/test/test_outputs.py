#!/usr/bin/python3
#
# @file    test_outputs.py
#
# @brief   Output fan-out, honest status, and panel variants
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

import socket

from vizrock.outputs.artnet_dmx import ArtNetDmx
from vizrock.outputs.oled_display import OledDisplay
from vizrock.outputs.resolume_osc import ResolumeOsc


def _listeners(count):
    made = []
    for _ in range(count):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        sock.settimeout(2)
        made.append(sock)
    return made


def run():
    _many_hosts()
    _one_host_many_addresses()
    _honest_status()
    _oled_variants()


def _many_hosts():
    """THC's machine and the laptop both get every cue."""
    socks = _listeners(2)
    ports = [s.getsockname()[1] for s in socks]
    osc = ResolumeOsc(hosts=['127.0.0.1'], port=ports[0])
    osc.is_running = False
    osc.resolved = {'thc': [('127.0.0.1', ports[0])], 'laptop': [('127.0.0.1', ports[1])]}

    osc.apply({'resolume': {'layer': 1, 'clip': 3}})
    got = [s.recvfrom(512)[0] for s in socks]
    assert got[0] == got[1], 'both hosts must receive identical bytes'
    assert b'/composition/layers/1/clips/3/connect' in got[0], got[0]

    osc.apply({'resolume': {'clear': True}})
    assert all(b'/composition/disconnectall' in s.recvfrom(512)[0] for s in socks)
    for s in socks:
        s.close()
    osc.close()


def _one_host_many_addresses():
    """A laptop on both a cable and WiFi is cued on both — failover with no switching."""
    socks = _listeners(2)
    ports = [s.getsockname()[1] for s in socks]
    osc = ResolumeOsc(hosts=['127.0.0.1'], port=ports[0])
    osc.is_running = False
    osc.hosts = ['laptop']
    osc.resolved = {'laptop': [('127.0.0.1', port) for port in ports]}

    osc.apply({'resolume': {'layer': 2, 'clip': 5}})
    both = [s.recvfrom(512)[0] for s in socks]
    assert both[0] == both[1] and b'/clips/5/connect' in both[0], both
    assert osc.address_label() == 'laptop→127.0.0.1+127.0.0.1', osc.address_label()
    for s in socks:
        s.close()
    osc.close()


def _honest_status():
    """Only outputs with a real connection may claim 'ok'."""
    osc = ResolumeOsc(hosts=['127.0.0.1'], port=7000)
    osc.is_running = False
    osc.resolved = {'x': [('127.0.0.1', 7000)]}
    assert osc.status() == 'ready', 'addressable, but delivery is unknowable'
    osc.resolved = {}
    assert osc.status() == 'retrying', 'nothing resolved cannot claim to be ready'
    osc.close()

    dmx = ArtNetDmx(host='127.0.0.1', universe=0, cues={'warm': {'1': 180}})
    assert dmx.status() == 'ready'
    assert dmx.address_label() == '127.0.0.1:6454 u0', dmx.address_label()
    dmx.close()

    for bad in ['', '   ', None, 5]:
        try:
            ArtNetDmx(host=bad)
        except (ValueError, AttributeError):
            continue
        raise AssertionError(f'artnet accepted host={bad!r}')


def _oled_variants():
    """Every panel variant must degrade to a no-op rather than raise."""
    for kwargs in [{}, {'driver': 'sh1106'}, {'address': '0x3D'}, {'address': 0x3D},
                   {'driver': 'nonexistent_driver'}]:
        panel = OledDisplay(**kwargs)
        assert panel.status() in ('ok', 'off'), kwargs
        assert panel.address_label().startswith('i2c 0x3'), panel.address_label()
        panel.on_state({'live': 1, 'armed': 2, 'outputs': {}, 'scenes': []})
    assert OledDisplay(address='0x3D').address_label() == 'i2c 0x3d ssd1306'
    assert OledDisplay(driver='sh1106').address_label() == 'i2c 0x3c sh1106'
