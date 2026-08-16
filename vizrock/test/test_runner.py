#!/usr/bin/python3
#
# @file    test_runner.py
#
# @brief   Runs every suite; vizrock_test entry point
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

import traceback

from vizrock.test import stubs

stubs.install()

SUITES = ['test_state_machine', 'test_outputs', 'test_resolver', 'test_config_edit', 'test_updater', 'test_ui_server', 'test_config_seed', 'test_scene_builder']


def main():
    import importlib

    failures = 0
    for name in SUITES:
        module = importlib.import_module(f'vizrock.test.{name}')
        try:
            module.run()
            print(f'  ok   {name}')
        except Exception:
            failures += 1
            print(f'  FAIL {name}')
            traceback.print_exc()
    print(f'\n{len(SUITES) - failures} passed, {failures} failed')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
