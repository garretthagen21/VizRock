#!/usr/bin/python3
#
# @file    updater.py
#
# @brief   Self-update: pull from git, then exit so systemd restarts on the new code
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
#
# @date    2026-08-08
#


import logging
import os
import signal
import socket
import subprocess
import threading
import time

import vizrock.constants.paths as vizrock_paths

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60
REACHABILITY_HOST = ('github.com', 443)
REACHABILITY_TIMEOUT = 3
GIT_TIMEOUT = 120


class Updater:
    """
    Checks whether an update is available and applies it.

    Applying means `git pull --ff-only`, reinstalling if dependencies moved, then
    exiting — systemd's Restart=always brings the process back on the new code, so
    no privilege escalation is needed. The browser reconnects on its own.

    Everything runs on a background thread. Nothing here is reachable from the cue
    dispatch path, and the venue has no internet, so an accidental mid-show update
    is not possible.
    """

    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda: None)
        self.online = False
        self.current = ''
        self.subject = ''
        self.incoming = []
        self.busy = False
        self.message = 'checking…'
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    # MARK: - State
    def snapshot(self):
        return {
            'online': self.online,
            'current': self.current,
            'subject': self.subject,
            'behind': len(self.incoming),
            'incoming': self.incoming,
            'busy': self.busy,
            'can_update': bool(self.online and self.incoming and not self.busy),
            'message': self.message,
        }

    def close(self):
        self.is_running = False

    # MARK: - Applying
    def apply(self, target):
        """
        Start an update towards `target`, the sha the UI last displayed. Refusing a
        stale target stops a queued click from applying something never shown.
        """
        if self.busy:
            return False, 'an update is already running'
        if not self.online:
            return False, 'no internet connection'
        if not self.incoming:
            return False, 'already up to date'
        if target != self.incoming[0]['sha']:
            return False, 'the listed update changed — refresh and try again'
        self.busy = True
        self.message = 'updating…'
        self.on_change()
        threading.Thread(target=self._apply, daemon=True).start()
        return True, 'update started'

    # MARK: - Private
    def _git(self, *args, timeout=GIT_TIMEOUT):
        return subprocess.run(('git', '-C', str(vizrock_paths.Directories.REPO_DIR)) + args,
                              capture_output=True, text=True, timeout=timeout)

    def _is_reachable(self):
        try:
            with socket.create_connection(REACHABILITY_HOST, REACHABILITY_TIMEOUT):
                return True
        except OSError:
            return False

    def _read_local(self):
        head = self._git('rev-parse', '--short', 'HEAD', timeout=10)
        if head.returncode != 0:
            self.message = 'not a git checkout — updates unavailable'
            return False
        self.current = head.stdout.strip()
        self.subject = self._git('log', '-1', '--format=%s', timeout=10).stdout.strip()
        return True

    def _read_incoming(self):
        if self._git('fetch', '--quiet').returncode != 0:
            self.message = 'could not reach the remote'
            return
        listing = self._git('log', '--format=%h\x1f%s', 'HEAD..@{u}', timeout=10)
        if listing.returncode != 0:
            self.message = 'no upstream branch is tracked'
            return
        self.incoming = [{'sha': sha, 'subject': subject}
                         for sha, _, subject in
                         (line.partition('\x1f') for line in listing.stdout.splitlines()) if sha]
        self.message = f'{len(self.incoming)} update(s) available' if self.incoming else 'up to date'

    def _poll_loop(self):
        while self.is_running:
            if not self.busy:
                self.online = self._is_reachable()
                if self._read_local():
                    if self.online:
                        self._read_incoming()
                    else:
                        self.message = 'offline — connect to the internet to update'
                self.on_change()
            for _ in range(POLL_INTERVAL_SECONDS):
                if not self.is_running:
                    return
                time.sleep(1)

    def _apply(self):
        try:
            before = self._dependency_fingerprint()
            pull = self._git('pull', '--ff-only')
            if pull.returncode != 0:
                self.message = f'pull failed: {pull.stderr.strip()[:120]}'
                logger.warning('update pull failed: %s', pull.stderr.strip())
                return
            if self._dependency_fingerprint() != before and not self._reinstall():
                return
            self.message = 'updated — restarting'
            logger.info('updated to %s, restarting', self._git('rev-parse', '--short', 'HEAD',
                                                               timeout=10).stdout.strip())
            self.on_change()
            time.sleep(1)                       # let the UI see the message first
            # systemd Restart=always brings us back on the new code
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception as error:
            self.message = f'update failed: {error}'
            logger.warning('update failed: %s', error)
        finally:
            self.busy = False
            self.on_change()

    def _dependency_fingerprint(self):
        setup = vizrock_paths.Directories.REPO_DIR / 'setup.py'
        return setup.read_text() if setup.exists() else ''

    def _reinstall(self):
        pip = vizrock_paths.Directories.REPO_DIR / 'venv' / 'bin' / 'pip'
        if not pip.exists():
            self.message = 'dependencies changed but the venv was not found'
            return False
        self.message = 'dependencies changed — reinstalling…'
        self.on_change()
        result = subprocess.run([str(pip), 'install', '-e', str(vizrock_paths.Directories.REPO_DIR)],
                                capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            self.message = f'dependency install failed: {result.stderr.strip()[:120]}'
            logger.warning('pip install failed: %s', result.stderr.strip())
            return False
        return True
