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
    # scene 1 is the main loop and sits outside the stepping order
    assert brain.scene_library.home == 1, brain.scene_library.home
    assert brain.scene_library.order == [2, 3], brain.scene_library.order
    assert brain.armed == 2

    brain.handle('go')
    assert (brain.live, brain.armed) == (2, 3), (brain.live, brain.armed)
    brain.handle('arm_next')
    assert (brain.live, brain.armed) == (2, 3), 'must clamp at the end of the setlist'
    brain.handle('arm_prev')
    assert brain.armed == 2

    # HOME bounces to the main loop without disturbing what is queued
    brain.handle('home')
    assert brain.live == 1, brain.live
    assert brain.armed == 2, 'home must not re-arm — the queued special stays queued'
    brain.handle('go')
    assert (brain.live, brain.armed) == (2, 3), 'resume exactly where we left off'

    # blackout is an action, not a scene: nothing is playing afterwards
    brain.handle('blackout')
    assert brain.live is None, brain.live
    assert brain.armed == 3, 'blackout must not re-arm either'
    assert not [s for s in brain.snapshot()['scenes'] if s.get('resolume', {}).get('clear')], \
        'blackout should not appear in the setlist'

    brain.handle('goto', 3)
    assert (brain.live, brain.armed) == (3, 3)
    brain.handle('bogus')                       # unknown action must not raise
    brain.handle('goto', 99)
    assert brain.live == 3, 'commit to a missing scene must be a no-op'

    # The M-VAVE Chocolate ships sending Program Change 0-3, one per press, left to
    # right. Confirmed on hardware. Layout is HOME / PREV / NEXT / GO — GO sits under
    # the strong foot on the right, and HOME is furthest from it so the two committing
    # actions cannot be confused mid-song.
    midi = MidiInterface(lambda action, scene: None)
    assert midi.match_trigger(message(type='program_change', program=0)) == ('home', None)
    assert midi.match_trigger(message(type='program_change', program=1)) == ('arm_prev', None)
    assert midi.match_trigger(message(type='program_change', program=2)) == ('arm_next', None)
    assert midi.match_trigger(message(type='program_change', program=3)) == ('go', None)
    assert midi.match_trigger(message(type='program_change', program=9)) is None
    assert midi.match_trigger(message(type='note_on', note=60, velocity=100)) is None, \
        'notes are not mapped on this pedal'

    snapshot = brain.snapshot()
    assert 'addresses' in snapshot and 'output_config' in snapshot
