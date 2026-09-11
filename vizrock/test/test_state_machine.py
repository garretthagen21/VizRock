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
    _scene_effects()
    brain = Brain()
    # every scene steps now; mains are a flag, not a position outside the order
    assert brain.scene_library.mains == [1], brain.scene_library.mains
    assert brain.scene_library.order == [1, 2, 3], brain.scene_library.order
    assert brain.armed == 1

    brain.handle('go')
    assert (brain.live, brain.armed) == (1, 2), (brain.live, brain.armed)
    brain.handle('go')
    assert (brain.live, brain.armed) == (2, 3), (brain.live, brain.armed)
    # the setlist is circular in both directions — a step that appears to do nothing
    # reads as a dead button, and the show is a loop anyway
    brain.handle('arm_next')
    assert (brain.live, brain.armed) == (2, 1), 'NEXT past the end wraps to the first'
    brain.handle('arm_prev')
    assert brain.armed == 3, 'PREV from the first wraps to the last'
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
    assert (brain.live, brain.armed) == (3, 1), 'auto-arm wraps past the last scene'
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
    _boots_dark_with_the_opener_loaded()
    _blackout_is_a_master_mute()
    _light_overrides_have_one_precedence()
    _light_sequences_loop()
    _peripherals_get_their_own_light_config()
    _audition_is_a_held_preview()
    _boot_mutes_outputs_even_with_no_scenes()
    _every_peripheral_reaches_all_its_steps()
    _commit_reset_ignores_the_incoming_scene_override()
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

    # whatever the auto-arm landed on, a missing scene must not move it
    armed_before = brain.armed
    brain.handle('arm', 99)
    assert brain.armed == armed_before, 'arming a missing scene must be a no-op'


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


def _boots_dark_with_the_opener_loaded():
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
    opener = brain.scene_library.order[0]
    assert brain.live == opener, \
        f'the set opens on scene 1, so that is what boots loaded, got {brain.live}'
    assert sent == ['Blackout'], f'outputs must still get all-off, got {sent}'
    assert brain.armed == brain.scene_library.step_from(opener, +1), \
        'the scene after the opener should be queued, not the opener itself'

    brain.handle('blackout')
    assert brain.blackout is False
    assert brain.live == opener, \
        f'releasing blackout should reveal the opener, got {brain.live}'


def _light_overrides_have_one_precedence():
    """
    blackout > lights off > burst > the scene.

    An explicit mute must always outrank a momentary effect, and a burst must never
    change the color on stage — only how the lights move.
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

    # burst swaps the mode and, with no colour of its own, leaves the scene's alone
    brain.handle('light_burst')
    assert sent[-1]['mode'] == 'strobe', sent[-1]
    assert sent[-1]['hue'] == 200, 'a burst with no colour must not change the color'

    # ...but a burst that names a colour interjects it, because a pop is a whole
    # light command and not only a change of movement
    brain.scene_library.scenes[2]['burst'] = {'mode': 'solid', 'hue': 0, 'seconds': 1}
    brain.handle('light_burst')
    assert sent[-1]['hue'] == 0, ('a burst that names a hue must win', sent[-1])

    # a scene palette would otherwise outrank the burst hue downstream, since the
    # receiver takes its colour from the palette and ignores hue when one is set
    brain.scene_library.scenes[2]['lights'] = {
        'default': {'mode': 'confetti', 'hue': 200, 'bright': 90, 'speed': 2,
                    'colors': [96, 160]}}
    brain.handle('goto', 2)
    brain.handle('light_burst')
    assert 'colors' not in sent[-1], ('a burst colour must clear the scene palette', sent[-1])
    assert sent[-1]['hue'] == 0, sent[-1]
    del brain.scene_library.scenes[2]['burst']
    brain.scene_library.scenes[2]['lights'] = {
        'default': {'mode': 'solid', 'hue': 200, 'bright': 90, 'speed': 2}}
    brain.handle('goto', 2)
    brain.handle('light_burst')

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
    assert sent[-1]['hue'] == 200, 'still never the color'
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

    # the color override still applies on top of a sequenced scene
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


def _audition_is_a_held_preview():
    """
    Auditioning shows a scene without cueing it: LIVE and ARMED never move, and
    releasing puts back exactly what was on stage.
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
    live_before, armed_before = brain.live, brain.armed
    sent.clear()

    brain.handle('audition_scene', 3)
    assert (brain.live, brain.armed) == (live_before, armed_before), 'a preview is not a cue'
    assert sent[-1]['resolume']['clip'] == 3, 'the audited scene reaches the outputs'

    brain.handle('audition_end')
    assert sent[-1]['resolume']['clip'] == 2, 'release puts back what was on stage'
    assert (brain.live, brain.armed) == (live_before, armed_before)

    # lights-only leaves the visuals alone
    brain.scene_library.scenes[3]['lights'] = {'default': {'mode': 'chase', 'hue': 90}}
    brain.handle('audition_lights', 3)
    assert sent[-1]['lights'][0]['mode'] == 'chase', sent[-1]['lights']
    assert sent[-1]['resolume']['clip'] == 2, 'the visuals must not change'
    brain.handle('audition_end')

    # it shows the scene as authored, not whatever was fiddled with mid-set
    brain.handle('cycle_color')
    brain.handle('audition_lights', 3)
    assert sent[-1]['lights'][0]['hue'] == 90, 'authored hue, not the override'
    brain.handle('audition_end')

    # blackout blocks it — nothing but blackout clears blackout
    brain.handle('blackout')
    sent.clear()
    brain.handle('audition_scene', 3)
    assert not any(s.get('resolume', {}).get('clip') == 3 for s in sent), \
        f'a preview must not light a stage someone killed: {sent}'
    brain.handle('blackout')


def _boot_mutes_outputs_even_with_no_scenes():
    """
    A fresh Pi with an empty scenes.json must still come up dark. `_render` returns
    early when nothing is live, so blackout has to be asserted before that guard.
    """
    sent = []

    class Spy:
        name = 'spy'

        def apply(self, scene):
            sent.append(scene.get('name'))

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    brain = Brain()
    brain.scene_library.load({'meta': {}, 'scenes': []})
    brain.live = brain.armed = None
    brain.outputs = [Spy()]
    brain.boot()

    assert brain.blackout is True
    assert sent == ['Blackout'], f'an empty setlist must still mute the outputs: {sent}'


def _every_peripheral_reaches_all_its_steps():
    """
    The step counter is shared but monotonic, and each peripheral indexes it with
    its own modulo. Wrapped to the default's length, a peripheral with more steps
    than the default would cycle 0,1,0,1 and never reach its third.
    """
    from vizrock.configurations.settings import vizrock_settings

    sent = []

    class Spy:
        name = 'rings'

        def apply(self, scene):
            sent.append(scene.get('lights') or {})

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    groups = dict(vizrock_settings.light_groups)
    vizrock_settings.light_groups = {'default': 0, 'cabA': 1}
    try:
        brain = Brain()
        brain.outputs = [Spy()]
        brain.scene_library.scenes[2]['lights'] = {
            'default': [{'mode': 'solid', 'hue': 1, 'seconds': 4},
                        {'mode': 'pulse', 'hue': 2, 'seconds': 4}],
            'cabA': [{'mode': 'chase', 'hue': 10},
                          {'mode': 'strobe', 'hue': 11},
                          {'mode': 'solid', 'hue': 12}]}
        brain.handle('goto', 2)

        seen = []
        for _ in range(6):
            seen.append(sent[-1][1]['hue'])
            brain._advance_light_step()
        assert sorted(set(seen)) == [10, 11, 12], \
            f'a 3-step peripheral must reach all three, got {seen}'
        assert seen == [10, 11, 12, 10, 11, 12], seen
    finally:
        vizrock_settings.light_groups = groups


def _commit_reset_ignores_the_incoming_scene_override():
    """
    On a cue, LIVE is already the new scene — so the effect reset must come from the
    global spec, or a per-scene osc_end would send the incoming scene's reset for an
    effect the outgoing one turned on.
    """
    from vizrock.configurations.settings import vizrock_settings

    fired = []

    class Spy:
        name = 'resolume'

        def apply(self, scene):
            pass

        def send_messages(self, messages, repeat=1):
            fired.extend(m.get('address') for m in messages)

        def on_state(self, _):
            pass

        def status(self):
            return 'ok'

        def address_label(self):
            return ''

    burst = dict(vizrock_settings.burst)
    vizrock_settings.burst = {**burst, 'osc_end': [{'address': '/global/reset', 'value': 1}]}
    try:
        brain = Brain()
        brain.outputs = [Spy()]
        brain.scene_library.scenes[3]['burst'] = {
            'osc_end': [{'address': '/scene3/only', 'value': 1}]}
        fired.clear()
        brain.handle('goto', 3)
        assert '/global/reset' in fired, fired
        assert '/scene3/only' not in fired, \
            f'the incoming scene must not supply the reset: {fired}'
    finally:
        vizrock_settings.burst = burst


def _restart_refires_without_rearming():
    brain = Brain()
    brain.handle('goto', 2)
    armed_before = brain.armed
    brain.handle('restart_scene')
    assert brain.live == 2, brain.live
    assert brain.armed == armed_before, 'restart must not disturb what is queued'

    # restart puts the scene back as authored, whatever was fiddled with mid-set
    brain.scene_library.scenes[2]['lights'] = {'default': [
        {'mode': 'pulse', 'hue': 200, 'seconds': 4}, {'mode': 'chase', 'hue': 160, 'seconds': 4}]}
    brain.handle('goto', 2)
    brain._advance_light_step()
    brain.handle('cycle_color')
    brain.handle('light_burst')
    assert brain.color_index is not None and brain._light_step == 1
    brain.handle('restart_scene')
    assert brain.color_index is None, 'a hand-picked color must not survive a restart'
    assert brain._light_step == 0, 'the light sequence restarts at step 1'
    assert brain._burst_until == 0.0, 'a running burst is cancelled'

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
    # boot loads the opener and arms the one after it, so GO commits scene 2
    assert brain.live == 2, f'the scene should still load, got {brain.live}'
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


def _scene_effects():
    """
    A scene can lay an effect over a clip, which is how scenes that share a video
    still look different. The reset fires first so the previous scene's effect never
    survives into the next.
    """
    from vizrock.brain import Brain
    brain = Brain()
    sent = []

    class EffectSpy:
        name = 'visuals'
        def apply(self, scene): pass
        def send_messages(self, messages, repeat=1):
            sent.extend(m['address'] for m in messages)
        def status(self): return 'ok'
        def address_label(self): return ''
        def close(self): pass

    brain.outputs = [EffectSpy()]
    brain.scene_library.scenes[2]['osc'] = [{'address': '/echo/on', 'value': 1.0}]
    brain.blackout = False

    sent.clear()
    brain.handle('goto', 2)
    assert '/echo/on' in sent, ('a scene must fire its own effects', sent)

    # a scene without effects fires none of its own, but the reset still runs
    sent.clear()
    brain.scene_library.scenes[3].pop('osc', None)
    brain.handle('goto', 3)
    assert '/echo/on' not in sent, ('an effect must not survive the next cue', sent)

    # blackout suppresses them: a stuck parameter on an invisible composition is
    # exactly the kind of thing that surprises someone two songs later
    sent.clear()
    brain.blackout = True
    brain.handle('goto', 2)
    assert '/echo/on' not in sent, ('blackout must suppress scene effects', sent)
