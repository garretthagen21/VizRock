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

    _arm_is_display_only()
    _blackout_is_a_toggle()
    _boots_dark_with_main_queued()

    snapshot = brain.snapshot()
    assert 'addresses' in snapshot and 'output_config' in snapshot


def _arm_is_display_only():
    """
    Tapping a cue arms it — it must never dispatch. A mis-tap that only changes
    what is queued costs nothing; one that fires a visual costs the song.
    """
    brain = Brain()
    fired = []

    class Spy:
        name = 'spy'

        def apply(self, scene):
            fired.append(scene['id'])

        def on_state(self, snapshot):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    brain.outputs = [Spy()]

    brain.handle('arm', 3)
    assert brain.armed == 3, brain.armed
    assert brain.live is None, 'arming must not change LIVE'
    assert not fired, 'arming must not reach the outputs'

    brain.handle('go')
    assert brain.live == 3 and fired == [3], (brain.live, fired)

    brain.handle('arm', 99)
    assert brain.armed == 3, 'arming a missing scene must be a no-op'


def _blackout_is_a_toggle():
    """
    Blackout is a held state, not a one-way trip: turning it off must put back what
    was playing, or killing the screen mid-song also loses your place.
    """
    brain = Brain()
    brain.handle('goto', 3)
    assert brain.live == 3 and brain.blackout is False

    brain.handle('blackout')
    assert brain.blackout is True, 'should be held on'
    assert brain.live is None, 'nothing is playing during blackout'

    brain.handle('blackout')
    assert brain.blackout is False, 'should toggle off'
    assert brain.live == 3, f'should restore what was playing, got {brain.live}'

    # firing anything means you want visuals again
    brain.handle('blackout')
    assert brain.blackout is True
    brain.handle('go')
    assert brain.blackout is False, 'committing a scene must clear blackout'

    # nothing live beforehand falls back to home rather than staying dark
    fresh = Brain()
    fresh.handle('blackout')
    fresh.handle('blackout')
    assert fresh.live == fresh.scene_library.home, f'should land on home, got {fresh.live}'
    assert fresh.blackout is False


def _boots_dark_with_main_queued():
    """
    Powering on must not throw a visual at a screen nobody is ready for, but
    releasing blackout has to land on the main loop rather than nothing.
    """
    brain = Brain()
    sent = []

    class Spy:
        name = 'spy'

        def apply(self, scene):
            sent.append(scene.get('name'))

        def on_state(self, snapshot):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    brain.outputs = [Spy()]
    brain.boot()

    assert brain.blackout is True, 'should come up dark'
    assert brain.live == brain.scene_library.home, \
        'the main loop should be loaded so you can see what you will get back'
    assert sent == ['Blackout'], f'outputs must still get all-off, got {sent}'
    assert brain.armed == brain.scene_library.order[0], 'first special should be queued'

    brain.handle('blackout')
    assert brain.blackout is False
    assert brain.live == brain.scene_library.home, \
        f'releasing blackout should land on the main loop, got {brain.live}'
