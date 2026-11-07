"""Regression checks for Garden's approved task and authored input boundary."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import _env
import garden_native_adapter as garden


class GardenBoundaryTests(unittest.TestCase):
    def test_project_inventory_detects_work_changes_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            project = root / 'native-projects' / 'shot'
            (project / 'work').mkdir(parents=True)
            (project / 'assets').mkdir()
            (project / 'index.html').write_text('<html/>')
            (project / 'work' / 'scene.js').write_text('first')
            before = garden.project_files(root, project)
            (project / 'work' / 'scene.js').write_text('second')
            self.assertNotEqual(before, garden.project_files(root, project))
            outside = root / 'outside.png'
            outside.write_bytes(b'outside')
            (project / 'assets' / 'link.png').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'symbolic links'):
                garden.project_files(root, project)

    def test_native_task_rejects_changes_to_entire_approved_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            request = root / 'brief.json'
            approved = {'semantic_row_id': 'row-1', 'quote': '消息', 'semantic': '消息变待办',
                        'required_change': '变成待办', 'component_brief': '三个待办'}
            for field in ('required_change', 'component_brief'):
                changed = {**approved, field: '另一件事'}
                brief = {'job_id': 'job-1', 'task_source': changed}
                request.write_text(json.dumps(brief))
                component = {'brief_sha256': hashlib.sha256(request.read_bytes()).hexdigest()}
                with self.subTest(field=field), \
                     mock.patch.object(garden, 'validate_brief', return_value=brief), \
                     mock.patch.object(garden, '_template', return_value={}):
                    with self.assertRaisesRegex(ValueError, 'changed after selection'):
                        garden.native_task(SimpleNamespace(job_id='job-1'), {}, component, request,
                                           approved_task_source=approved)


if __name__ == '__main__':
    unittest.main()
