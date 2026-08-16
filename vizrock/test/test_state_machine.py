#!/usr/bin/python3
#
# @file    test_state_machine.py
#
# @brief   LIVE/ARMED transitions and MIDI trigger matching
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#

from vizrock.test.stubs import message
from vizrock.managers.midi_interface import MidiInterface
from vizrock.brain import Brain


def run():
    brain = Brain()
    # scene 0 is the main loop and sits outside the stepping order
    assert brain.scene_library.home == 0, brain.scene_library.home
    assert brain.scene_library.order == [1, 2], brain.scene_library.order
    assert brain.armed == 1

    brain.handle('go')
    assert (brain.live, brain.armed) == (1, 2), (brain.live, brain.armed)
    brain.handle('arm_next')
    assert (brain.live, brain.armed) == (1, 2), 'must clamp at the end of the setlist'
    brain.handle('arm_prev')
    assert brain.armed == 1

    # HOME bounces to the main loop without disturbing what is queued
    brain.handle('home')
    assert brain.live == 0, brain.live
    assert brain.armed == 1, 'home must not re-arm — the queued special stays queued'
    brain.handle('go')
    assert (brain.live, brain.armed) == (1, 2), 'resume exactly where we left off'

    # blackout is an action, not a scene: nothing is playing afterwards
    brain.handle('blackout')
    assert brain.live is None, brain.live
    assert brain.armed == 2, 'blackout must not re-arm either'
    assert 0 not in [s['id'] for s in brain.snapshot()['scenes'] if s.get('resolume', {}).get('clear')], \
        'blackout should not appear in the setlist'

    brain.handle('goto', 2)
    assert (brain.live, brain.armed) == (2, 2)
    brain.handle('bogus')                       # unknown action must not raise
    brain.handle('goto', 99)
    assert brain.live == 2, 'commit to a missing scene must be a no-op'

    midi = MidiInterface(lambda action, scene: None)
    assert midi.match_trigger(message(type='note_on', note=60, velocity=100)) == ('go', None)
    assert midi.match_trigger(message(type='note_on', note=61, velocity=100)) == ('arm_prev', None)
    assert midi.match_trigger(message(type='note_on', note=62, velocity=100)) == ('arm_next', None)
    assert midi.match_trigger(message(type='note_on', note=63, velocity=100)) == ('home', None)
    assert midi.match_trigger(message(type='note_on', note=60, velocity=0)) is None, \
        'note-off must not fire'
    assert midi.match_trigger(message(type='program_change', program=1)) == ('goto', 2)
    assert midi.match_trigger(message(type='note_on', note=99, velocity=100)) is None

    snapshot = brain.snapshot()
    assert 'addresses' in snapshot and 'output_config' in snapshot
