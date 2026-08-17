#!/usr/bin/python3
#
# @file    system.py
#
# @brief   Host identity and addresses, for showing on the UI and OLED
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-17
#


import socket
import subprocess
import time

CACHE_SECONDS = 15

_cache = {'at': 0.0, 'addresses': []}


def hostname():
    return socket.gethostname()


def local_addresses():
    """
    IPv4 addresses this box answers on, so the UI can tell you where to point a
    phone without SSHing in to find out.

    Cached: state is pushed on every ARM move, and forking a process per button
    press would be silly.
    """
    now = time.monotonic()
    if _cache['addresses'] and now - _cache['at'] < CACHE_SECONDS:
        return _cache['addresses']
    try:
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=2)
        addresses = [a for a in result.stdout.split() if ':' not in a]
    except Exception:
        addresses = []
    _cache['at'], _cache['addresses'] = now, addresses
    return addresses
