#!/usr/bin/python3
#
# @file    test_migrate.py
#
# @brief   Config migration adds new keys without clobbering tuned values
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-19
#


from vizrock.configurations.migrate import merge_missing


def run():
    _adds_without_clobbering()
    _leaves_a_current_config_alone()


def _adds_without_clobbering():
    """
    The live configs are untracked so they survive updates — which means a setting
    added upstream would never reach an existing box. Merging fixes that, but must
    never overwrite hosts, ports or cues someone tuned.
    """
    live = {'ui': {'port': 8080},
            'outputs': {'resolume': {'hosts': ['mine.local'], 'port': 38200}}}
    example = {'ui': {'port': 8080, 'tap_fires': False},
               'outputs': {'resolume': {'hosts': ['placeholder.local'], 'port': 7000,
                                        'enabled': True}},
               'midi_inputs': ['SINCO']}

    added = merge_missing(live, example)

    assert live['outputs']['resolume']['hosts'] == ['mine.local'], 'clobbered a tuned host'
    assert live['outputs']['resolume']['port'] == 38200, 'clobbered a tuned port'
    assert live['ui']['tap_fires'] is False, 'new nested key not added'
    assert live['outputs']['resolume']['enabled'] is True, 'new nested key not added'
    assert live['midi_inputs'] == ['SINCO'], 'new top-level key not added'
    assert sorted(added) == ['midi_inputs', 'outputs.resolume.enabled', 'ui.tap_fires'], added


def _leaves_a_current_config_alone():
    live = {'a': 1, 'b': {'c': 2}}
    assert merge_missing(live, {'a': 9, 'b': {'c': 9}}) == []
    assert live == {'a': 1, 'b': {'c': 2}}, 'an up-to-date config must not change'
