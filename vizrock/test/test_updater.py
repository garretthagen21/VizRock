#!/usr/bin/python3
#
# @file    test_updater.py
#
# @brief   Update gating: refuses offline, stale or duplicate requests
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#


from vizrock.managers.updater import Updater


def _idle():
    """An Updater with its polling thread never started, so state is ours to set."""
    updater = Updater.__new__(Updater)
    updater.on_change = lambda: None
    updater.online, updater.current, updater.subject = False, 'abc1234', 'a commit'
    updater.incoming, updater.busy, updater.message = [], False, ''
    updater.is_running = False
    return updater


def run():
    _refuses_when_it_cannot()
    _snapshot_shape()


def _refuses_when_it_cannot():
    updater = _idle()

    started, why = updater.apply('anything')
    assert not started and 'internet' in why, why

    updater.online = True
    started, why = updater.apply('anything')
    assert not started and 'up to date' in why, why

    # a click carrying a sha we never displayed must not apply something unseen
    updater.incoming = [{'sha': 'newsha1', 'subject': 'new work'}]
    started, why = updater.apply('staleshaX')
    assert not started and 'changed' in why, why

    updater.busy = True
    started, why = updater.apply('newsha1')
    assert not started and 'already running' in why, why


def _snapshot_shape():
    updater = _idle()
    snapshot = updater.snapshot()
    for key in ('online', 'current', 'subject', 'behind', 'incoming',
                'busy', 'can_update', 'message'):
        assert key in snapshot, key
    assert snapshot['can_update'] is False, 'offline with nothing incoming cannot update'

    updater.online = True
    updater.incoming = [{'sha': 'a', 'subject': 'b'}]
    assert updater.snapshot()['can_update'] is True
    assert updater.snapshot()['behind'] == 1

    updater.busy = True
    assert updater.snapshot()['can_update'] is False, 'must not offer an update mid-update'

    updater.busy = False
    updater.online = False
    assert updater.snapshot()['can_update'] is False, 'offline must never offer an update'
