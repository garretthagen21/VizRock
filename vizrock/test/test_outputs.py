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
import time

from vizrock.outputs.artnet_dmx import ArtNetDmx
from vizrock.outputs.oled_display import OledDisplay
from vizrock.outputs.resolume_osc import ResolumeOsc
from vizrock.outputs.light_serial import LightSerial


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
    _osc_floats_and_effect_messages()
    _null_port_means_autodetect()
    _ring_wire_format()


def _osc_floats_and_effect_messages():
    """
    Effect parameters are 0.0-1.0 floats. Sending an int where Resolume expects a
    float is silently ignored rather than rejected, so the typetag has to be right.
    """
    listener = _listeners(1)[0]
    port = listener.getsockname()[1]
    osc = ResolumeOsc(hosts=['127.0.0.1'], port=port)
    try:
        for _ in range(40):
            if osc.resolved.get('127.0.0.1'):
                break
            time.sleep(0.05)

        osc.send_messages([{'address': '/composition/layers/1/video/opacity', 'value': 0.5}])
        packet, _ = listener.recvfrom(2048)
        assert b'/composition/layers/1/video/opacity' in packet, packet
        assert b',f' in packet, f'a float parameter must use the ,f typetag: {packet}'

        osc.send_messages([{'address': '/x/bypassed', 'value': 1}])
        packet, _ = listener.recvfrom(2048)
        assert b',i' in packet, f'an int should still use ,i: {packet}'

        # repeat exists because a dropped reset means a stuck effect all song
        osc.send_messages([{'address': '/x/bypassed', 'value': 1}], repeat=3)
        seen = 0
        listener.settimeout(1)
        for _ in range(3):
            listener.recvfrom(2048)
            seen += 1
        assert seen == 3, seen

        osc.send_messages([{'novalue': 1}])   # malformed entries are skipped, not raised
        osc.send_messages(None)
    finally:
        osc.close()
        listener.close()


def _null_port_means_autodetect():
    """
    A config that says nothing about the port must search for one.

    `"port": null` was treated as an explicit path, so the output reported
    `retrying` forever with a working transmitter attached — the single symptom
    that is indistinguishable from dead hardware.
    """
    for hint in (None, '', 'auto'):
        serial_out = LightSerial(port=hint)
        try:
            assert serial_out.port_hint == hint
            # _find_port must go looking rather than hand back the empty hint
            found = serial_out._find_port()
            assert found != hint or found is None, (hint, found)
            assert 'None' not in serial_out.address_label(), serial_out.address_label()
        finally:
            serial_out.close()

    # every other output raises on nonsense so the factory can reject it; this one
    # silently accepted anything, which is how "port": null reached the running system
    for bad in ({'port': 5}, {'port': ['/dev/x']}, {'baud': 'fast'},
                {'baud': 0}, {'baud': True}):
        try:
            LightSerial(**bad).close()
        except ValueError:
            pass
        else:
            raise AssertionError(f'should have been refused: {bad}')

    from vizrock.outputs import build_output
    assert build_output('lights', {'type': 'serial', 'port': 5}) is None, \
        'the factory must reject what the output refuses'

    explicit = LightSerial(port='/dev/light_tx')
    try:
        assert explicit._find_port() == '/dev/light_tx', 'an explicit path is still honoured'
    finally:
        explicit.close()


def _ring_wire_format():
    """The LIGHT line is parsed by firmware in the other repo — pin its shape."""
    serial = LightSerial(port='/dev/null')
    try:
        # the brain hands outputs {group: light}, already resolved
        serial.apply({'lights': {0: {'mode': 'pulse', 'hue': 200, 'bright': 90, 'speed': 3}}})
        assert serial.latest_payload == 'LIGHT 0 pulse 200 90 3 - 255\n', serial.latest_payload

        # one line per peripheral group, every tick, sorted so it is stable
        serial.apply({'lights': {0: {'mode': 'solid', 'hue': 10, 'bright': 20, 'speed': 1},
                               2: {'mode': 'chase', 'hue': 90, 'bright': 30, 'speed': 5}}})
        assert serial.latest_payload == ('LIGHT 0 solid 10 20 1 - 255\n'
                                       'LIGHT 2 chase 90 30 5 - 255\n'), serial.latest_payload

        # a scene with no light block must still be a well-formed line
        serial.apply({})
        assert serial.latest_payload == 'LIGHT 0 off 0 0 0 - 255\n', serial.latest_payload

        # the palette field: absent, random, an explicit list, and capped at five
        for colors, expected in [(None, '-'), ('random', 'random'), ([96, 0], '96,0'),
                                 ([1, 2, 3, 4, 5, 6, 7, 8, 9], '1,2,3,4,5,6,7,8'),
                                 ([], '-'), ('nonsense', '-'), ([300], '44')]:
            light = {'mode': 'confetti', 'hue': 96, 'bright': 200, 'speed': 5}
            if colors is not None:
                light['colors'] = colors
            serial.apply({'lights': {0: light}})
            assert serial.latest_payload == f'LIGHT 0 confetti 96 200 5 {expected} 255\n', (
                colors, serial.latest_payload)
        # saturation: absent is full colour, 0 is white, junk degrades rather than raises
        for sat, expected in [(None, 255), (0, 0), (128, 128), (999, 255), (-5, 0), ('x', 255)]:
            light = {'mode': 'solid', 'hue': 96, 'bright': 200, 'speed': 0}
            if sat is not None:
                light['sat'] = sat
            serial.apply({'lights': {0: light}})
            assert serial.latest_payload == f'LIGHT 0 solid 96 200 0 - {expected}\n', (
                sat, serial.latest_payload)
    finally:
        serial.close()


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
