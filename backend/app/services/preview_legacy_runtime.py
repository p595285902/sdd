"""Controller adapter for the existing non-Compose workload and source-sync client."""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import OrderedDict

from app.services.preview_native_runtime import replay_events

RUNNER = '/controller/preview_legacy_session.py'
TERMINAL = ('failed', 'stopped', 'interrupted')
NATIVE_LABEL = 'sdd.preview.native-execution'


class LegacyRuntime:
    def __init__(self, controller):
        self.c = controller
        self.lock = threading.RLock()
        self.operations = {}
        self.last = {}
        self.terminal = OrderedDict()

    def operation(self, chat_id):
        with self.lock:
            return self.operations.setdefault(chat_id, threading.RLock())

    def exec(self, chat_id, argv):
        return self.c.native.exec(chat_id, argv, user='65534:65534')

    def read(self, chat_id, after):
        return json.loads(self.exec(chat_id, ['python', RUNNER, 'events', str(after)]))

    def launch(self, chat_id, plan):
        execution_id = str(uuid.UUID(plan['execution_id']))
        with self.operation(chat_id):
            cached = self.last.get(chat_id) or self.terminal.get(chat_id)
            if cached and cached['execution_id'] == execution_id:
                return self.status(chat_id, self.c.inspect(chat_id))
            container = self.c.inspect(chat_id)
            if not self.owns(container) or not container['State'].get('Running'):
                raise FileNotFoundError('Legacy preview workload is not running')
            try:
                current = self.read(chat_id, 0)
            except RuntimeError:
                current = None  # Source-ready workload has no execution journal yet.
            if current:
                if current['execution_id'] != execution_id:
                    raise RuntimeError('Stop the previous preview before starting a new execution')
                self.last[chat_id] = {key: value for key, value in current.items() if key != 'events'}
                return self.status(chat_id, container)
            self.c.native.upload(chat_id, {'preview-legacy-plan.json': (json.dumps(plan).encode(), 0o600)}, '/tmp', uid=65534)
            current = json.loads(self.exec(chat_id, ['python', RUNNER, 'start', execution_id]))
            self.terminal.pop(chat_id, None)
            self.c.native.terminal.pop(chat_id, None)
            self.last[chat_id] = {key: value for key, value in current.items() if key != 'events'}
            with self.c.activity_lock:
                self.c.activity[chat_id] = time.time()
            return self.status(chat_id, container)

    @staticmethod
    def owns(container):
        labels = (container or {}).get('Config', {}).get('Labels') or {}
        return bool(container) and not labels.get(NATIVE_LABEL) and not labels.get('sdd.preview.compose-service')

    def status(self, chat_id, container):
        # GET status must not exec/probe, resolve instructions or provision.
        if self.owns(container) and chat_id in self.last:
            current = self.last[chat_id]
            if not container['State'].get('Running') and current['state'] not in TERMINAL:
                current = {**current, 'state': 'interrupted', 'ready': False}
            return {'id': container['Id'], 'runtime': 'legacy', **current, **(current.get('details', {}) if current.get('ready') else {})}
        return self.terminal.get(chat_id) if container is None else None

    def preserve(self, chat_id, current):
        events, cursor = [], 0
        while cursor < current['cursor']:
            page = self.read(chat_id, cursor)
            if not page['events']:
                break
            events.extend(page['events'])
            event = page['events'][-1]
            next_cursor = event['payload']['through_cursor'] if event['kind'] == 'gap' else event['cursor']
            if next_cursor <= cursor:
                raise RuntimeError('Legacy journal did not advance')
            cursor = next_cursor
        self.terminal[chat_id] = {**current, 'events': events, 'ready': False}
        self.terminal.move_to_end(chat_id)
        while len(self.terminal) > 64:
            self.terminal.popitem(last=False)

    def terminal_page(self, chat_id, after):
        current = self.terminal[chat_id]
        events = replay_events(current['events'], after)
        state = current['state'] if not events or events[-1]['cursor'] >= current['cursor'] else 'running'
        return {**current, 'events': events, 'state': state}

    def events(self, chat_id, after=0):
        with self.operation(chat_id):
            if chat_id in self.terminal:
                return self.terminal_page(chat_id, after)
            container = self.c.inspect(chat_id)
            if not self.owns(container):
                raise FileNotFoundError('Legacy preview execution is missing')
            try:
                current = self.read(chat_id, after)
            except RuntimeError:
                cached = self.status(chat_id, container)
                if cached is None:
                    raise FileNotFoundError('Legacy preview execution is missing') from None
                return {**cached, 'events': []}
            self.last[chat_id] = {key: value for key, value in current.items() if key != 'events'}
            if current['state'] in TERMINAL:
                self.preserve(chat_id, current)
                self.c.stop(chat_id)
                return self.terminal_page(chat_id, after)
            if current.get('events') and current['events'][-1]['cursor'] < current['cursor']:
                current = {**current, 'state': 'running', 'ready': False}
            return current

    def before_stop(self, chat_id, container):
        if not self.owns(container):
            return
        with self.operation(chat_id):
            if chat_id in self.terminal:
                return
            try:
                current = self.read(chat_id, 0)
                if current['state'] not in TERMINAL:
                    self.exec(chat_id, ['python', RUNNER, 'stop'])
                    current = self.read(chat_id, 0)
                self.preserve(chat_id, current)
            except RuntimeError:
                cached = self.last.get(chat_id)
                if cached:
                    self.terminal[chat_id] = {**cached, 'state': 'interrupted', 'ready': False, 'events': []}
            finally:
                self.last.pop(chat_id, None)
