"""Archive smoke: preserve real PNG bytes and existing delivery files."""
import copy
import json
import shutil
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

from scripts import export_delivery as export
from edit.hd.tools import contract_artifacts as artifacts


class DeliveryExportTests(unittest.TestCase):
    def test_archive_smoke_and_input_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = SimpleNamespace(root=root / 'workspace', job_dir=root / 'workspace/edit/hd/jobs/test',
                                  job_id='test', stages={'cover': {'artifacts': []},
                                                       'delivery': {'artifacts': []}})
            job.job_dir.mkdir(parents=True)
            def registered(stage, name, content):
                path = job.job_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                job.stages[stage]['artifacts'].append({'path': name, **export._record(path)})
                return path
            registered('cover', '04-cover/cover-brief.json', json.dumps({'title': '文明/密码'}).encode())
            image = root / 'portrait.png'
            Image.new('RGB', (9, 16), 'orange').save(image)
            cover = registered('delivery', '12-delivery/cover/cover-9x16.png', image.read_bytes())
            film = root / 'formal.mp4'
            film.write_bytes(b'existing formal film bytes')
            receipt = {'delivery_manifest': {'sha256': 'a' * 64}, 'delivery': export._record(film)}
            with (mock.patch.object(export, 'DELIVERY_ROOT', root / '素材与作品'),
                  mock.patch.object(export.delivery_approval, 'delivery_file', return_value=film),
                  mock.patch.object(export.delivery_approval, 'validate_delivery_receipt', return_value=receipt)):
                with self.assertRaisesRegex(ValueError, '缺少独立3:4'):
                    export.export_delivery(job)
                generated = job.root / 'punk-assets/punk-cover/one'
                generated.mkdir(parents=True)
                portrait = generated / 'cover.png'
                Image.new('RGB', (3, 4), 'blue').save(portrait)
                metadata = {'title': '文明/密码', 'aspect_ratio': '3:4', 'independently_composed': True,
                            'job_id': 'different-job'}
                (generated / 'generation.json').write_text(json.dumps(metadata))
                with self.assertRaisesRegex(ValueError, '缺少独立3:4'):
                    export.export_delivery(job)
                metadata['job_id'] = job.job_id
                (generated / 'generation.json').write_text(json.dumps(metadata))
                result = export.export_delivery(job)
                self.assertEqual(Path(result['delivery_directory']).name, '文明_密码')
                for key, source in [('delivery_file', film), ('cover_9x16_file', cover),
                                    ('cover_3x4_file', portrait)]:
                    self.assertEqual(Path(result[key]).read_bytes(), source.read_bytes())
                self.assertEqual(export.export_delivery(job), result)
                self.assertEqual(export.exported_paths(job), result)
                old_job = copy.copy(job)
                old_job.job_dir = root / 'old-job'
                shutil.copytree(job.job_dir, old_job.job_dir)
                # Explicit changed input replaces the final directory and preserves the old bundle.
                old = portrait.read_bytes()
                Image.new('RGB', (3, 4), 'green').save(portrait)
                publish = export.delivery_approval._publish_once
                def fail_new_bundle(source, target):
                    if source.name == 'bundle':
                        raise OSError('simulated publish failure')
                    return publish(source, target)
                with mock.patch.object(export.delivery_approval, '_publish_once', side_effect=fail_new_bundle):
                    with self.assertRaisesRegex(OSError, 'simulated publish failure'):
                        export.export_delivery(job, cover_3x4=portrait)
                self.assertEqual(Path(result['cover_3x4_file']).read_bytes(), old)
                with mock.patch.object(artifacts, 'write_json_artifact', side_effect=OSError('record write failed')):
                    with self.assertRaisesRegex(OSError, 'record write failed'):
                        export.export_delivery(job, cover_3x4=portrait)
                self.assertEqual(export.exported_paths(job), result)
                self.assertEqual(Path(result['cover_3x4_file']).read_bytes(), old)
                version = export.export_delivery(job, cover_3x4=portrait)
                self.assertEqual(version, result)
                self.assertEqual({p.name for p in Path(version['delivery_directory']).iterdir()}, set(export._FILES.values()))
                archived = list((root / 'video-jobs/交付历史/文明_密码').iterdir())
                self.assertEqual(len(archived), 1)
                self.assertEqual((archived[0] / '封面_3x4.png').read_bytes(), old)
                self.assertEqual(Path(version['cover_3x4_file']).read_bytes(), portrait.read_bytes())
                self.assertEqual(export.export_delivery(job, cover_3x4=portrait), version)
                with self.assertRaisesRegex(ValueError, '损坏或被修改'):
                    export.export_delivery(old_job, cover_3x4=portrait)
                record_path = job.job_dir / 'manifests/delivery-export.json'
                record = json.loads(record_path.read_text())
                record['directory'] = str(Path(version['delivery_directory']) / ('版本-' + artifacts.sha256_json(record['outputs'])[:12]))
                record_path.write_text(json.dumps(record))
                self.assertEqual(export.exported_paths(job), version)
                (job.job_dir / 'manifests/delivery-export.json').unlink()
                duplicate = generated.parent / 'two'
                duplicate.mkdir()
                (duplicate / 'generation.json').write_text(json.dumps(metadata))
                (duplicate / 'cover.png').write_bytes(portrait.read_bytes())
                with self.assertRaisesRegex(ValueError, '多个独立3:4'):
                    export.export_delivery(job)
                with self.assertRaisesRegex(ValueError, '本Job工作区'):
                    export.export_delivery(job, cover_3x4=image)
                link = generated / 'outside.png'
                link.symlink_to(image)
                with self.assertRaisesRegex(ValueError, '软链接'):
                    export.export_delivery(job, cover_3x4=link)
                renamed = generated / 'renamed.png'
                Image.new('RGB', (3, 4), 'red').save(renamed, format='JPEG')
                with self.assertRaisesRegex(ValueError, 'PNG'):
                    export.export_delivery(job, cover_3x4=renamed)
                export.export_delivery(job, cover_3x4=portrait)
                Path(version['delivery_file']).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, '损坏或被修改'):
                    export.exported_paths(job)
                # A different production makes the old metadata stale, not accepted.
                receipt['delivery_manifest']['sha256'] = 'b' * 64
                self.assertEqual(export.exported_paths(job), {})


if __name__ == '__main__':
    unittest.main()
