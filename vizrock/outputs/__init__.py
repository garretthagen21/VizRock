#!/usr/bin/python3
#
# @file    __init__.py
#
# @brief   Output factory; builds every enabled output from vizrock_settings
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging

from vizrock.configurations.settings import vizrock_settings
from vizrock.outputs.artnet_dmx import ArtNetDmx
from vizrock.outputs.oled_display import OledDisplay
from vizrock.outputs.resolume_osc import ResolumeOsc
from vizrock.outputs.light_serial import LightSerial

logger = logging.getLogger(__name__)

OUTPUT_KINDS = {'osc': ResolumeOsc, 'artnet': ArtNetDmx,
                'serial': LightSerial, 'oled': OledDisplay}


def build_output(name, spec):
    """
    One output, or None if it is malformed. Never raises.

    A disabled output is still built. `enabled` mutes dispatch rather than gating
    construction, so a disabled output holds its connection and its safe-off state —
    which the light transmitter in particular needs: stop sending entirely and the
    receivers fall back to their idle pattern after four seconds and glow instead of
    going dark.
    """
    output_class = OUTPUT_KINDS.get(spec.get('type'))
    if not output_class:
        logger.warning('unknown output type: %s', spec.get('type'))
        return None
    try:
        output = output_class(**{k: v for k, v in spec.items() if k not in ('type', 'enabled')})
    except Exception as error:
        # a malformed output must not take the show down, at startup or on edit
        logger.warning('output %s failed to build: %s', name, error)
        return None
    output.name = name
    logger.info('output up: %s (%s)', name, spec['type'])
    return output


def build_outputs():
    """Instantiate every output named in vizrock_settings, enabled or not."""
    return [output for output in
            (build_output(name, spec) for name, spec in vizrock_settings.outputs.items())
            if output is not None]
