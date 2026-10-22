import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/runtime_bundle.py'


class RuntimeBundleTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'runtime bundle deployment entrypoint is missing')
        spec = importlib.util.spec_from_file_location('runtime_bundle', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'source'
        for name in ('edit/__init__.py', 'edit/hd/__init__.py',
                     'edit/hd/tools/__init__.py', 'edit/hd/tools/state.py',
                     'edit/hd/tools/startup.py', 'edit/hd/tools/segment_render.py',
                     'edit/v5/tools/openlux_images.py', 'edit/v5/tools/bold_subtitles.py',
                     'edit/v5/tools/build_visual_plan.py', 'edit/v5/tools/bold_layouts.py',
                     'edit/v5/tools/style_tokens.py'):
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# runtime\n')
        (self.project / '.env').write_text('SECRET=not exported')
        self.bundle = self.root / 'runtime.zip'

    def test_roundtrip_and_no_overwrite(self):
        self.module.export_bundle(self.project, self.bundle)
        report = self.module.verify_bundle(self.bundle)
        self.assertEqual(len(report['files']), 11)
        target = self.root / 'new-project'
        self.module.install_bundle(self.bundle, target)
        self.assertFalse((target / '.env').exists())
        self.assertTrue((target / 'edit/hd/tools/state.py').is_file())
        with self.assertRaises((ValueError, FileExistsError)):
            self.module.install_bundle(self.bundle, target)
        with self.assertRaises(FileExistsError):
            self.module.export_bundle(self.project, self.bundle)

    def test_reject_source_symlink(self):
        path = self.project / 'edit/hd/tools/state.py'
        path.unlink()
        path.symlink_to(self.project / '.env')
        with self.assertRaises(ValueError):
            self.module.export_bundle(self.project, self.bundle)

    def test_reject_destination_symlink(self):
        self.module.export_bundle(self.project, self.bundle)
        target = self.root / 'linked'
        target.symlink_to(self.root / 'not-created', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.module.install_bundle(self.bundle, target)
        self.assertFalse((self.root / 'not-created').exists())

    @unittest.skipUnless(os.environ.get('HD_RUNTIME_PROJECT_ROOT'),
                         'set HD_RUNTIME_PROJECT_ROOT for real runtime deployment integration')
    def test_real_runtime_clean_process_imports(self):
        source = Path(os.environ['HD_RUNTIME_PROJECT_ROOT']).resolve()
        self.module.export_bundle(source, self.bundle)
        target = self.root / 'deployed-project'
        self.module.install_bundle(self.bundle, target)
        outside = self.root / 'outside-project'
        outside.mkdir()
        code = '''
import importlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
assert not Path.cwd().resolve().is_relative_to(root)
files = sorted((root / 'edit/hd/tools').glob('*.py'))
assert files, 'no runtime modules exported'
for path in files:
    module = importlib.import_module('edit.hd.tools.' + path.stem)
    assert Path(module.__file__).resolve() == path.resolve(), module.__file__
from edit.hd.tools.startup import runtime_identity
identity = runtime_identity(root)
assert identity['project_root'] == str(root)
for name, module in tuple(sys.modules.items()):
    if name == 'edit' or name.startswith('edit.') or name == 'style_tokens':
        filename = getattr(module, '__file__', None)
        if filename:
            assert Path(filename).resolve().is_relative_to(root), (name, filename)
print(json.dumps({'module_count': len(files), 'root': str(root)}))
'''
        environment = dict(os.environ)
        environment.pop('PYTHONPATH', None)
        environment['PYTHONPATH'] = str(target)
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run([sys.executable, '-c', code, str(target)],
                                cwd=outside, env=environment, capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['root'], str(target))
        self.assertGreater(report['module_count'], 3)

    def test_reject_malformed_archives_without_writes(self):
        self.module.export_bundle(self.project, self.bundle)
        with zipfile.ZipFile(self.bundle) as archive:
            originals = [(i, archive.read(i)) for i in archive.infolist()]
        for kind in ('traversal', 'extra', 'duplicate', 'symlink', 'tamper', 'manifest_duplicate'):
            bad = self.root / (kind + '.zip')
            with zipfile.ZipFile(bad, 'w') as archive:
                for info, data in originals:
                    if kind == 'tamper' and info.filename.endswith('state.py'):
                        data += b'changed'
                    if kind == 'manifest_duplicate' and info.filename == 'runtime-manifest.json':
                        data = data.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
                    if kind == 'symlink' and info.filename.endswith('state.py'):
                        info = zipfile.ZipInfo(info.filename)
                        info.create_system = 3
                        info.external_attr = 0o120777 << 16
                    archive.writestr(info, data)
                if kind in ('traversal', 'extra', 'duplicate'):
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        archive.writestr({'traversal': '../escape', 'extra': '.env',
                                          'duplicate': 'edit/hd/tools/state.py'}[kind], b'x')
            target = self.root / ('target-' + kind)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.module.install_bundle(bad, target)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
