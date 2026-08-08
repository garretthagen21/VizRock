#!/usr/bin/python3
#
# @file    stubs.py
#
# @brief   Import stubs so the suite runs without hardware or deps
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

import sys
import types


def install():
    """Stand in for packages that are only present on the Pi."""
    if 'mido' not in sys.modules:
        mido = types.ModuleType('mido')
        mido.get_input_names = lambda: []
        mido.open_input = lambda *a, **k: None
        sys.modules['mido'] = mido
    if 'aiohttp' not in sys.modules:
        aiohttp = types.ModuleType('aiohttp')
        aiohttp.WSMsgType = types.SimpleNamespace(TEXT=1)
        aiohttp.web = types.SimpleNamespace(
            Application=object, get=lambda *a, **k: None, static=lambda *a, **k: None,
            HTTPFound=object, WebSocketResponse=object, AppRunner=object, TCPSite=object)
        sys.modules['aiohttp'] = aiohttp


def message(**fields):
    """A stand-in for a mido message."""
    return types.SimpleNamespace(**fields)
