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
    # every scene steps now; mains are a flag, not a position outside the order
    assert brain.scene_library.mains == [1], brain.scene_library.mains
    assert brain.scene_library.order == [1, 2, 3], brain.scene_library.order
    assert brain.armed == 1

    brain.handle('go')
    assert (brain.live, brain.armed) == (1, 2), (brain.live, brain.armed)
    brain.handle('go')
    assert (brain.live, brain.armed) == (2, 3), (brain.live, brain.armed)
    brain.handle('arm_next')
    assert (brain.live, brain.armed) == (2, 3), 'must clamp at the end of the setlist'
    brain.handle('arm_prev')
    assert brain.armed == 2

    # the main button bounces to a looping visual without disturbing what is queued
    brain.handle('next_main')
    assert brain.live == 1, brain.live
    assert brain.armed == 2, 'next_main must not re-arm — the queued scene stays queued'
    brain.handle('go')
    assert (brain.live, brain.armed) == (2, 3), 'resume exactly where we left off'

    # blackout is a pure output mute: LIVE keeps pointing at what is loaded, so
    # releasing it reveals the scene rather than restoring a remembered one
    brain.handle('blackout')
    assert brain.blackout is True
    assert brain.live == 2, f'blackout must not unload the scene, got {brain.live}'
    assert brain.armed == 3, 'blackout must not re-arm either'
    brain.handle('blackout')
    assert (brain.blackout, brain.live) == (False, 2), 'releasing reveals what was loaded'
    brain.handle('blackout')
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
    assert midi.match_trigger(message(type='program_change', program=0)) == ('next_main', None)
    assert midi.match_trigger(message(type='program_change', program=1)) == ('arm_prev', None)
    assert midi.match_trigger(message(type='program_change', program=2)) == ('arm_next', None)
    assert midi.match_trigger(message(type='program_change', program=3)) == ('go', None)
    assert midi.match_trigger(message(type='program_change', program=9)) is None
    assert midi.match_trigger(message(type='note_on', note=60, velocity=100)) is None, \
        'notes are not mapped on this pedal'

    _arm_is_display_only()
    _blackout_is_a_toggle()
    _lights_are_a_separate_switch()
    _boots_dark_with_main_queued()
    _blackout_is_a_master_mute()
    _light_overrides_have_one_precedence()
    _light_sequences_loop()
    _peripherals_get_their_own_light_config()
    _restart_refires_without_rearming()
    _next_main_is_a_dead_button_with_no_mains()

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
    Blackout is a held state and a pure output mute. LIVE keeps pointing at whatever
    is loaded, so releasing it reveals the scene rather than the brain having to
    remember and restore one — killing the screen mid-song never loses your place.
    """
    brain = Brain()
    brain.handle('goto', 3)
    assert brain.live == 3 and brain.blackout is False

    brain.handle('blackout')
    assert brain.blackout is True, 'should be held on'
    assert brain.live == 3, 'the scene stays loaded underneath — this mutes outputs'

    brain.handle('blackout')
    assert brain.blackout is False, 'should toggle off'
    assert brain.live == 3, f'should reveal what was loaded, got {brain.live}'

    # blackout holds through a commit — see _blackout_is_a_master_mute
    brain.handle('blackout')
    assert brain.blackout is True
    brain.handle('go')
    assert brain.blackout is True, 'GO must not clear a deliberate blackout'
    brain.handle('blackout')


def _lights_are_a_separate_switch():
    """
    Lights off must leave the visuals running. Blackout is the panic control that
    kills everything; muting the lights during a quiet song is a different job.
    """
    sent = []

    class Spy:
        name = 'spy'

        def apply(self, scene):
            sent.append(scene)

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    brain = Brain()
    brain.outputs = [Spy()]
    brain.handle('goto', 2)
    sent.clear()

    brain.handle('toggle_lights')
    assert brain.lights_off is True
    assert sent[-1]['lights'][0]['mode'] == 'off', sent[-1]['lights']
    assert not sent[-1].get('resolume', {}).get('clear'), \
        'the visuals must keep running with the lights off'

    # a cue still fires visuals while the lights stay muted
    brain.handle('goto', 3)
    assert sent[-1]['lights'][0]['mode'] == 'off', 'lights stay off across a cue'
    assert sent[-1]['resolume']['clip'] == 3, sent[-1]['resolume']

    brain.handle('toggle_lights')
    assert brain.lights_off is False
    assert sent[-1]['lights'][0]['mode'] != 'off', 'lights come back'

    # blackout outranks the lights switch either way round
    brain.handle('blackout')
    assert sent[-1].get('resolume', {}).get('clear') is True, sent[-1]


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
    assert brain.live == brain.scene_library.next_main(0), \
        'the first main should be loaded so you can see what you will get back'
    assert sent == ['Blackout'], f'outputs must still get all-off, got {sent}'
    assert brain.armed == brain.scene_library.order[0], 'the first scene should be queued'

    brain.handle('blackout')
    assert brain.blackout is False
    assert brain.live == brain.scene_library.next_main(0), \
        f'releasing blackout should land on the first main, got {brain.live}'


def _light_overrides_have_one_precedence():
    """
    blackout > lights off > burst > the scene.

    An explicit mute must always outrank a momentary effect, and a burst must never
    change the colour on stage — only how the lights move.
    """
    from vizrock.configurations.settings import vizrock_settings

    sent = []

    class Spy:
        name = 'lights'

        def apply(self, scene):
            sent.append(dict((scene.get('lights') or {}).get(0) or {}))

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    brain = Brain()
    brain.outputs = [Spy()]
    brain.scene_library.scenes[2]['lights'] = {
        'default': {'mode': 'solid', 'hue': 200, 'bright': 90, 'speed': 2}}
    brain.handle('goto', 2)
    sent.clear()

    # burst swaps the mode and keeps the hue
    brain.handle('light_burst')
    assert sent[-1]['mode'] == 'strobe', sent[-1]
    assert sent[-1]['hue'] == 200, 'a burst must never change the colour'

    # an explicit mute outranks the running burst
    brain.handle('toggle_lights')
    assert brain.lights_off is True
    assert sent[-1]['mode'] == 'off', sent[-1]
    brain.handle('light_burst')
    assert sent[-1]['mode'] == 'off', 'lights off must outrank a burst'

    brain.handle('toggle_lights')
    assert brain.lights_off is False

    # blackout outranks everything, and the light block is the blackout scene's own
    brain.handle('blackout')
    sent.clear()
    brain.handle('light_burst')
    assert all(s.get('mode') == 'off' for s in sent), f'blackout must win: {sent}'
    brain.handle('blackout')

    # the burst ends by itself and the scene comes back
    brain._end_burst()
    assert sent[-1]['mode'] == 'solid', f'should revert to the scene: {sent[-1]}'

    # a scene may override what popping means
    brain.scene_library.scenes[2]['burst'] = {'mode': 'pulse', 'speed': 4}
    brain.handle('light_burst')
    assert sent[-1]['mode'] == 'pulse', sent[-1]
    assert sent[-1]['speed'] == 4, sent[-1]
    assert sent[-1]['hue'] == 200, 'still never the colour'
    del brain.scene_library.scenes[2]['burst']
    brain._end_burst()
    assert vizrock_settings.burst['mode'] == 'strobe', 'the global default is strobe'


def _light_sequences_loop():
    """
    A scene's lighting may be a list of steps that cycles, so a long stretch of
    looping visuals does not sit on one look. A single dict must keep working.
    """
    sent = []

    class Spy:
        name = 'lights'

        def apply(self, scene):
            sent.append(dict((scene.get('lights') or {}).get(0) or {}))

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    brain = Brain()
    brain.outputs = [Spy()]
    brain.scene_library.scenes[2]['lights'] = {'default': [
        {'mode': 'pulse', 'hue': 200, 'bright': 90, 'speed': 2, 'seconds': 4},
        {'mode': 'chase', 'hue': 160, 'bright': 110, 'speed': 4, 'seconds': 4}]}
    brain.handle('goto', 2)

    assert sent[-1]['mode'] == 'pulse', 'a cue starts at the first step'
    assert 'seconds' not in sent[-1], 'timing is ours, it must not reach the wire'

    brain._advance_light_step()
    assert sent[-1]['mode'] == 'chase', sent[-1]
    brain._advance_light_step()
    assert sent[-1]['mode'] == 'pulse', 'it loops'

    # re-cueing restarts at the first step rather than resuming mid-sequence
    brain._advance_light_step()
    brain.handle('goto', 2)
    assert sent[-1]['mode'] == 'pulse', f'a fresh cue restarts the loop: {sent[-1]}'

    # a plain dict is still a one-step scene, and never starts a timer
    brain.scene_library.scenes[3]['lights'] = {'default': {'mode': 'solid', 'hue': 10}}
    brain.handle('goto', 3)
    assert sent[-1]['mode'] == 'solid', sent[-1]
    assert brain._light_timer is None, 'a single-step scene needs no timer'

    # the colour override still applies on top of a sequenced scene
    brain.handle('goto', 2)
    brain.handle('cycle_color')
    from vizrock.configurations.settings import vizrock_settings
    assert sent[-1]['hue'] == vizrock_settings.palette[0], sent[-1]
    brain._restart_light_loop()


def _peripherals_get_their_own_light_config():
    """
    Lights are keyed by peripheral. `default` covers every group without its own
    entry, and each group is addressed exactly once per tick.
    """
    from vizrock.configurations.settings import vizrock_settings

    sent = []

    class Spy:
        name = 'lights'

        def apply(self, scene):
            sent.append(scene.get('lights') or {})

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    groups = dict(vizrock_settings.light_groups)
    vizrock_settings.light_groups = {'default': 0, 'cabA': 1, 'cabB': 2}
    try:
        brain = Brain()
        brain.outputs = [Spy()]
        brain.scene_library.scenes[2]['lights'] = {
            'default': {'mode': 'solid', 'hue': 10},
            'cabA': {'mode': 'chase', 'hue': 90}}
        brain.handle('goto', 2)

        lights = sent[-1]
        assert set(lights) == {0, 1, 2}, f'every group needs a line: {sorted(lights)}'
        assert lights[1]['mode'] == 'chase', 'cabA takes its own config'
        assert lights[0]['mode'] == 'solid', 'group 0 takes the default'
        assert lights[2]['mode'] == 'solid', 'cabB has no entry, so it falls back'

        # with no `default` key the first entry written becomes the fallback
        brain.scene_library.scenes[2]['lights'] = {'cabA': {'mode': 'pulse', 'hue': 5}}
        brain.handle('goto', 2)
        assert sent[-1][0]['mode'] == 'pulse', sent[-1]
        assert sent[-1][2]['mode'] == 'pulse', 'everything falls back to the first entry'

        # muting still covers every group
        brain.handle('toggle_lights')
        assert all(l['mode'] == 'off' for l in sent[-1].values()), sent[-1]
    finally:
        vizrock_settings.light_groups = groups


def _restart_refires_without_rearming():
    brain = Brain()
    brain.handle('goto', 2)
    armed_before = brain.armed
    brain.handle('restart_scene')
    assert brain.live == 2, brain.live
    assert brain.armed == armed_before, 'restart must not disturb what is queued'

    # nothing live is a no-op, not a crash
    fresh = Brain()
    fresh.live = None
    fresh.handle('restart_scene')
    assert fresh.live is None


def _next_main_is_a_dead_button_with_no_mains():
    brain = Brain()
    for scene in brain.scene_library.scenes.values():
        scene.pop('main', None)
    brain.scene_library.load({'meta': brain.scene_library.meta,
                              'scenes': list(brain.scene_library.scenes.values())})
    brain.live = 2
    brain.handle('next_main')
    assert brain.live == 2, 'must not invent a scene to jump to'


def _blackout_is_a_master_mute():
    """
    Blackout holds until released. You can load and change scenes underneath it, but
    nothing reaches an output — and GO must never silently undo a blackout someone
    put on deliberately.
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
    sent.clear()

    brain.handle('go')
    assert brain.blackout is True, 'GO must not clear blackout'
    assert brain.live == 1, f'the scene should still load, got {brain.live}'
    # A cue under blackout re-asserts all-off rather than sending nothing at all, so
    # an output that came up late is still muted. What must never happen is a real
    # scene reaching the stage.
    assert set(sent) <= {'Blackout'}, f'a scene leaked while blacked out: {sent}'

    brain.handle('arm', 3)
    brain.handle('go')
    assert brain.blackout is True and brain.live == 3
    assert set(sent) <= {'Blackout'}, f'a scene leaked while blacked out: {sent}'

    brain.handle('blackout')
    assert brain.blackout is False
    assert brain.live == 3, 'release should reveal what was loaded'
    assert sent and sent[-1] == 'Interlude', f'release should dispatch it, got {sent}'
