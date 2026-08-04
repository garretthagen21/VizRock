#!/usr/bin/python3
#
# @file    __init__.py
#
# @brief   Output factory; builds every enabled output from show_settings
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging

from show_brain.configurations.settings import show_settings
from show_brain.outputs.artnet_dmx import ArtNetDmx
from show_brain.outputs.oled_display import OledDisplay
from show_brain.outputs.resolume_osc import ResolumeOsc
from show_brain.outputs.ring_serial import RingSerial

logger = logging.getLogger(__name__)

OUTPUT_KINDS = {'osc': ResolumeOsc, 'artnet': ArtNetDmx,
                'serial': RingSerial, 'oled': OledDisplay}


def build_outputs():
    """Instantiate every enabled output named in show_settings."""
    outputs = []
    for name, spec in show_settings.outputs.items():
        if not spec.get('enabled', True):
            continue
        output_class = OUTPUT_KINDS.get(spec['type'])
        if not output_class:
            logger.warning('unknown output type: %s', spec.get('type'))
            continue
        try:
            output = output_class(**{k: v for k, v in spec.items() if k not in ('type', 'enabled')})
        except Exception as error:
            # a malformed output must not take the show down at startup
            logger.warning('output %s failed to build: %s', name, error)
            continue
        output.name = name
        outputs.append(output)
        logger.info('output up: %s (%s)', name, spec['type'])
    return outputs
