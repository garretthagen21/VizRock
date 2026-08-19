#!/usr/bin/python3
#
# @file    migrate.py
#
# @brief   Fold new keys from the committed examples into the live configs
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-19
#


import json

import vizrock.constants.paths as vizrock_paths

PAIRS = [
    (vizrock_paths.Files.SHOW_CONFIG_FILE, 'show_config'),
    (vizrock_paths.Files.SCENES_FILE, 'scenes'),
]


def merge_missing(live, example, path=''):
    """
    Add keys the example has and the live config lacks. Never overwrite a value
    that is already set — the live config holds hosts, ports and cues someone tuned,
    and clobbering those would be worse than missing a new setting.

    Returns the list of dotted keys that were added.
    """
    added = []
    for key, value in example.items():
        here = f'{path}.{key}' if path else key
        if key not in live:
            live[key] = value
            added.append(here)
        elif isinstance(value, dict) and isinstance(live[key], dict):
            added += merge_missing(live[key], value, here)
    return added


def main():
    """
    Run on install. The live configs are untracked so they survive updates — which
    also means a new setting added upstream would never reach an existing box
    without this.
    """
    for live_path, name in PAIRS:
        example_path = live_path.with_name(f'{live_path.stem}.example.json')
        if not example_path.exists():
            continue
        if not live_path.exists():
            live_path.write_text(example_path.read_text())
            print(f'  {name}: seeded from example')
            continue
        live = json.loads(live_path.read_text())
        added = merge_missing(live, json.loads(example_path.read_text()))
        if added:
            live_path.write_text(json.dumps(live, indent=2))
            print(f'  {name}: added {", ".join(added)}')
        else:
            print(f'  {name}: up to date')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
