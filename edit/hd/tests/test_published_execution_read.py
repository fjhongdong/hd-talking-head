"""Qualification inspection must not recover or clean execution journals."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from edit.hd.tools import broll_component_executor as executor


class PublishedExecutionReadTests(unittest.TestCase):
    def test_read_only_journal_refuses_recovery_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = root / 'transaction.json'
            following = root / 'transaction.json.next'
            record = dict.fromkeys(executor._JOURNAL_KEYS)
            record['state'] = 'published'
            def payload_for(state):
                return json.dumps({**record, 'state': state}, sort_keys=True, separators=(',', ':')).encode() + b'\n'
            payload = payload_for('published')
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaises(executor.BrollComponentExecutionError):
                    executor._read_published_record_at(descriptor, current.name, 'BROLL_RENDER_FAILED')
                current.write_bytes(payload)
                self.assertEqual(executor._read_published_record_at(descriptor, current.name, 'BROLL_RENDER_FAILED'),
                                 record)
                following.write_bytes(payload)
                before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
                with self.assertRaises(executor.BrollComponentExecutionError):
                    executor._read_published_record_at(descriptor, current.name, 'BROLL_RENDER_FAILED')
                self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()})
                following.unlink()
                for state in ('planned', 'running', 'complete', 'publishing'):
                    current.write_bytes(payload_for(state))
                    with self.subTest(state=state), self.assertRaises(executor.BrollComponentExecutionError):
                        executor._read_published_record_at(descriptor, current.name, 'BROLL_RENDER_FAILED')
            finally:
                os.close(descriptor)
