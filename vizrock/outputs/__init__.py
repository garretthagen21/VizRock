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
from vizrock.outputs.ring_serial import RingSerial

logger = logging.getLogger(__name__)

OUTPUT_KINDS = {'osc': ResolumeOsc, 'artnet': ArtNetDmx,
                'serial': RingSerial, 'oled': OledDisplay}


def build_output(name, spec):
    """One output, or None if it is disabled or malformed. Never raises."""
    if not spec.get('enabled', True):
        return None
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
    """Instantiate every enabled output named in vizrock_settings."""
    return [output for output in
            (build_output(name, spec) for name, spec in vizrock_settings.outputs.items())
            if output is not None]
