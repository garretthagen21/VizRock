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
    assert brain.scene_library.order == [1, 2, 3, 4], brain.scene_library.order
    assert brain.armed == 1

    brain.handle('go')
    assert (brain.live, brain.armed) == (1, 2), (brain.live, brain.armed)
    brain.handle('go')
    assert (brain.live, brain.armed) == (2, 3)
    brain.handle('arm_next')
    assert (brain.live, brain.armed) == (2, 4), 'ARM must not change LIVE'
    brain.handle('arm_next')
    assert brain.armed == 4, 'must clamp at the end of the setlist'
    brain.handle('arm_prev')
    assert brain.armed == 3
    brain.handle('blackout')
    assert (brain.live, brain.armed) == (0, 3), 'blackout must not re-arm'
    brain.handle('go')
    assert (brain.live, brain.armed) == (3, 4), 'resume where we left off'
    brain.handle('goto', 1)
    assert (brain.live, brain.armed) == (1, 2)
    brain.handle('bogus')                       # unknown action must not raise
    brain.handle('goto', 99)
    assert brain.live == 1, 'commit to a missing scene must be a no-op'

    midi = MidiInterface(lambda action, scene: None)
    assert midi.match_trigger(message(type='note_on', note=62, velocity=100)) == ('go', None)
    assert midi.match_trigger(message(type='note_on', note=62, velocity=0)) is None, \
        'note-off must not fire'
    assert midi.match_trigger(message(type='program_change', program=1)) == ('goto', 2)
    assert midi.match_trigger(message(type='note_on', note=99, velocity=100)) is None

    snapshot = brain.snapshot()
    assert snapshot['scenes'][0]['id'] == 0 and len(snapshot['scenes']) == 5
    assert 'addresses' in snapshot and 'output_config' in snapshot
