#!/usr/bin/python3
#
# @file    logger.py
#
# @brief   Logging setup
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-03
#

import logging as show_logging
import sys

show_logging.basicConfig(
    level=show_logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[show_logging.StreamHandler(sys.stdout)]
)
