"""Small runtime checks without installing dependencies or opening browsers."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import _env
import motion_native_runtime as runtime


class MotionNativeRuntimeTests(unittest.TestCase):
    def test_unsupported_node_stops_before_installation_or_runtime_writes(self):
        for dependency, version, minimum in [('barty-motion-graphics', 'v18.20.0', '>=20'),
                                               ('bang-motion', 'v22.11.0', '>=22.12.0'),
                                               ('mg-styles-15', 'v22.11.0', '>=22.12.0'),
                                               ('video-shotcraft', 'v22.11.0', '>=22.12.0')]:
            with self.subTest(dependency=dependency), \
                    mock.patch.object(runtime.shutil, 'which', return_value='/tools/node'), \
                    mock.patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, version)) as run, \
                    mock.patch.object(runtime, 'runtime_root') as root:
                with self.assertRaisesRegex(ValueError, minimum):
                    runtime.prepare(_env.PROJECT, dependency_id=dependency)
                root.assert_not_called()
                self.assertEqual([call.args[0] for call in run.call_args_list], [['/tools/node', '--version']])

    def test_selected_3d_style_blocks_before_confirmation_but_not_other_styles_or_reviewed_reuse(self):
        from types import SimpleNamespace
        import run_stage
        import motion_native_skill_adapter as native
        from test_motion_native_skill_adapter import brief
        with mock.patch.object(runtime.shutil,'which',side_effect=AssertionError('unselected/reused templates must not probe Blender')):
            for dependency,template,mode in [('mg-styles-15','flat-vector','render'),
                                              ('video-shotcraft','spotlight-hero-card','render'),
                                              ('mg-styles-15','3d-render','reuse')]:
                self.assertEqual(runtime.check_template_dependencies(_env.PROJECT,dependency_id=dependency,
                    template_id=template,mode=mode),{'status':'not_required'})
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();job=SimpleNamespace(job_dir=root)
            binding={'dependency_id':'mg-styles-15','template_id':'mg-styles-15/3d-render'}
            director={'segments':[{'segment_id':'seg-001','bindings':{'scene':binding}}]}
            with mock.patch.object(runtime.shutil,'which',return_value=None), \
                 mock.patch.object(runtime.Path,'is_file',return_value=False):
                with self.assertRaisesRegex(ValueError,'Blender 5.1.*before visual confirmation'):
                    run_stage._validate_prepared_native_inputs(job,_env.PROJECT,director,{'scenes':[]})
            request=root/'brief.json';request.write_text(json.dumps(brief('mg-styles-15','3d-render')))
            binding['brief_sha256']=native.sha(request)
            result=root/'native-inputs/native-test/result.json';result.parent.mkdir(parents=True);result.write_text('{}')
            treatment={'scenes':[{'segment_id':'seg-001','component_id':'scene','brief_path':'brief.json'}]}
            with mock.patch.object(runtime.shutil,'which',side_effect=AssertionError('reviewed reuse must stay offline')), \
                 mock.patch.object(native,'inspect_result',return_value={'status':'completed'}) as inspect:
                native.check_selected_template_dependencies(job,director,treatment)
            inspect.assert_called_once_with(root,request.read_bytes())

    def test_reuse_only_requires_current_ffprobe(self):
        with mock.patch.object(runtime.shutil, 'which', return_value='/tools/ffprobe') as which, \
                mock.patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ffprobe version 8.0\nconfiguration')) as run, \
                mock.patch.object(runtime, 'runtime_root') as root:
            checked = runtime.check(_env.PROJECT, dependency_id='bang-motion', mode='reuse')
            which.assert_called_once_with('ffprobe'); root.assert_not_called()
            self.assertEqual(checked['tools'], {'ffprobe': '/tools/ffprobe'})
            self.assertEqual([call.args[0] for call in run.call_args_list], [['/tools/ffprobe', '-version']])

    def test_new_render_records_actual_versions_and_frozen_identity_is_offline(self):
        dependency = 'barty-motion-graphics'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in runtime.locked_files(_env.PROJECT, dependency).items():
                shutil.copyfile(source, root / name)
            for package in ('playwright', 'playwright-core'):
                target = root / 'node_modules' / package; target.mkdir(parents=True)
                (target / 'package.json').write_text(json.dumps({'version': '1.64.0'}))
            def version_or_browser(argv, **kwargs):
                output = {'/tools/node': 'v22.12.0', '/tools/ffmpeg': 'ffmpeg version 8.0\nbuild',
                          '/tools/ffprobe': 'ffprobe version 8.0\nbuild'}[argv[0]]
                if argv[1] == '-e':
                    output = json.dumps({'browser': '/old/chromium', 'version': '140.0.1'})
                return subprocess.CompletedProcess(argv, 0, output)
            with mock.patch.object(runtime, 'runtime_root', return_value=root), \
                    mock.patch.object(runtime.shutil, 'which', side_effect=lambda name: '/tools/' + name), \
                    mock.patch.object(runtime.subprocess, 'run', side_effect=version_or_browser) as run:
                checked = runtime.check(_env.PROJECT, dependency_id=dependency)
                self.assertEqual(sum(call.args[0][1] == '-e' for call in run.call_args_list), 1)
            identity = checked['runtime_identity']
            self.assertEqual(identity['tools']['node'], {'path': '/tools/node', 'version': 'v22.12.0'})
            self.assertEqual(identity['tools']['ffmpeg']['version'], 'ffmpeg version 8.0')
            self.assertEqual(identity['browser'], {'path': '/old/chromium', 'version': '140.0.1'})
            with mock.patch.object(runtime.subprocess, 'run', side_effect=AssertionError('must stay offline')):
                self.assertEqual(runtime.validate_runtime_identity(_env.PROJECT, identity, dependency_id=dependency), identity)
                changed = copy.deepcopy(identity); changed['lock_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'locked dependency'):
                    runtime.validate_runtime_identity(_env.PROJECT, changed, dependency_id=dependency)


if __name__ == '__main__':
    unittest.main()
