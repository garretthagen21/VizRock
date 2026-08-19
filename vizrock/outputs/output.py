#!/usr/bin/python3
#
# @file    output.py
#
# @brief   Base class shared by every show output
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

class Output:
    """
    apply(scene)    reflect a committed scene on this output (fired on GO)
    on_state(snap)  react to any state change (fired on ARM moves too)
    status()        'ok' | 'ready' | 'retrying' | 'off'
    address_label() where this output points, for the UI

    'ready' means addressable and able to send, with no delivery confirmation —
    fire-and-forget. Only outputs with a real connection may claim 'ok'.
    """

    name = 'base'

    def apply(self, scene): ...

    def on_state(self, snapshot): ...

    def status(self):
        return 'ok'

    def address_label(self):
        return ''

    def close(self): ...
