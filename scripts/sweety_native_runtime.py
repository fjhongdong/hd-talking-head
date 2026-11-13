"""Run the unchanged Sweety renderer with project-local ordinary Python packages."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from package_paths import PACKAGE_ROOT

RUNTIME = 'runtime/handdraw-python312'
RENDERER_VERSION = 'sweety-handdraw-video-3.1.0'


def environment(project=PACKAGE_ROOT):
    project = Path(project).resolve(strict=True)
    # Keep the vendor read-only, and never trigger a model/browser installation.
    return {**os.environ, 'PYTHONPATH': str(project / RUNTIME),
            'PYTHONDONTWRITEBYTECODE': '1', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
            'PLAYWRIGHT_BROWSERS_PATH': str(project / 'runtime/motion-native-playwright-1.64.0/browsers'),
            'PATH': str(project / 'runtime/ffmpeg-9.0.2/bin') + os.pathsep + os.environ.get('PATH', '')}


def check(project=PACKAGE_ROOT, *, python_executable=sys.executable, mode='render'):
    project = Path(project).resolve(strict=True)
    python = str(Path(python_executable).resolve(strict=True))
    tools = {name: shutil.which(name, path=environment(project)['PATH']) for name in ('ffmpeg', 'ffprobe')}
    if not all(tools.values()):
        raise ValueError('Sweety requires existing FFmpeg and ffprobe')
    if mode == 'reuse':
        return {'status': 'ready', 'renderer_version': RENDERER_VERSION, 'tools': tools}
    code = ('import sys,json,importlib.metadata as m;'
            'from playwright.sync_api import sync_playwright;'
            'assert sys.version_info >= (3,12);'
            'p=sync_playwright().start();b=p.chromium.launch();'
            'print(json.dumps({"python":sys.executable,"browser":p.chromium.executable_path,'
            '"browser_version":b.version,"packages":{n:m.version(n) for n in '
            '["playwright","Pillow","numpy","scipy","requests","fonttools","pypinyin","jieba"]}}));'
            'b.close();p.stop()')
    result = subprocess.run([python, '-B', '-c', code], env=environment(project),
                            capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise ValueError('Sweety local runtime is unavailable: ' + result.stderr[-1800:])
    details = json.loads(result.stdout)
    if int(details['packages']['Pillow'].split('.')[0]) >= 12:
        raise ValueError('Sweety requires its upstream Pillow<12 environment')
    return {'status': 'ready', 'renderer_version': RENDERER_VERSION, 'tools': tools,
            'python': python, 'package_directory': str(project / RUNTIME),
            'environment': {key: environment(project)[key] for key in
                            ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE',
                             'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD', 'PLAYWRIGHT_BROWSERS_PATH')}, **details}


def kinetic_title_content(config):
    """Project the title text that the original kinetic-title recipe displays."""
    if (not isinstance(config, dict) or set(config) != {'template_id', 'recipe', 'params'}
            or config['template_id'] != 'web-kinetic-title' or config['recipe'] != 'kinetic_title'):
        raise ValueError('Sweety project differs from the selected kinetic-title recipe')
    params = config.get('params')
    if not isinstance(params, dict) or not isinstance(params.get('text'), str) or not params['text'].strip():
        raise ValueError('Sweety kinetic title needs its actual text parameters')
    text = params['text']
    # The original glyph-oriented styles split text themselves. Other styles
    # display the explicit words array when the caller supplies one.
    if params.get('style') not in {'spring_pop', 'typewriter', 'scramble'} and 'words' in params:
        words = params['words']
        if not isinstance(words, list) or not words or not all(isinstance(word, str) for word in words):
            raise ValueError('Sweety kinetic title has invalid visible words')
        text = ''.join(words)
    return {'params': {'text': text}}


def render_web(project, native_project, composition):
    """Call the original render function, without injecting or replacing animation."""
    from sweety_native_adapter import source_root, load_template_catalog
    source = source_root(project) / 'skills/sweety-handdraw-video'
    directory = Path(native_project).resolve(strict=True)
    config = json.loads((directory / 'web-motion.json').read_bytes())
    if set(config) != {'template_id', 'recipe', 'params'}:
        raise ValueError('Sweety web config requires only original recipe and parameters')
    row = next((r for r in load_template_catalog(project) if r['template_id'] == config['template_id']), None)
    if not row or row['native_template_group'] != 'web_motion' or row['native_option_id'] != config['recipe']:
        raise ValueError('Sweety web config must use its selected original fixed recipe')
    sys.path.insert(0, str(source / 'scripts'))
    import web_motion
    result = web_motion.render(config['recipe'], config['params'], composition['width'], composition['height'],
                               composition['frames'] / composition['fps'], directory / 'out/frames',
                               fps=composition['fps'])
    # The upstream includes a settled endpoint frame; ordinary encoding consumes
    # exactly the parent's approved number of frames, without changing timing.
    (directory / 'out/web-motion-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


def render_style(project, native_project, composition, job_root):
    """Validate original built visuals and call the upstream video-only worker."""
    from sweety_native_adapter import source_root, _visual_inputs
    source = source_root(project) / 'skills/sweety-handdraw-video/scripts'
    sys.path.insert(0, str(source))
    from video_renderer import Renderer, render_chunk, export_storyboard
    from video_verifier import verify_job, file_hash
    from narration_master import verify_compiled_master
    from timeline_contract import validate_timeline
    directory = Path(native_project).resolve(strict=True)
    target = directory / 'out/visual.mp4'
    report_path = directory / 'out/style-visual-checks.json'
    if target.exists() or report_path.exists():
        raise ValueError('Preserve existing native visual execution; use a new revision')
    _visual_inputs(job_root,directory)  # Reject external files before Renderer opens them.
    renderer = Renderer(directory)
    timeline = renderer.timeline
    if (timeline.get('manifest_sha256') != file_hash(directory / 'job.json')
            or {k: timeline['canvas'][k] for k in ('width', 'height', 'fps')} !=
               {k: composition[k] for k in ('width', 'height', 'fps')}):
        raise ValueError('Native visual build differs from its authored manifest or canvas')
    if renderer.watermark is not None and timeline['watermark'].get('position', 'legacy') != 'legacy':
        from watermark_assets import plan_watermark
        renderer.watermark_plan = plan_watermark(renderer)
    frozen_inputs = _visual_inputs(job_root,directory)
    checks = {'verify_job_assets_only': verify_job(directory, assets_only=True),
              'verify_compiled_master': verify_compiled_master(directory, timeline),
              'validate_timeline': validate_timeline(timeline)}
    if not checks['verify_compiled_master']:
        raise ValueError('Native visuals require the real locked narration clock')
    seconds = composition['frames'] / composition['fps']
    if abs(timeline['narration_master']['samples'] / 48000 - seconds) > 1 / 48000 + 1e-9:
        raise ValueError('Native narration clock differs from the parent visual window')
    export_storyboard(renderer)
    start = renderer.voice_start()
    result = render_chunk(directory, target, start, 0, composition['frames'])
    if _visual_inputs(job_root,directory) != frozen_inputs:
        raise ValueError('Sweety visual dependencies changed during native rendering')
    report = {'scope': 'silent_visual_material', 'native_full_film_verified': False,
              'checks': checks, 'voice_start_seconds': start, 'first_frame': 0,
              'composition': composition, 'native_captions': True,
              'visual_inputs': frozen_inputs,
              'media': result}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=PACKAGE_ROOT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--render-web', type=Path)
    parser.add_argument('--render-style', type=Path)
    parser.add_argument('--job-root', type=Path)
    parser.add_argument('--composition-json')
    args = parser.parse_args()
    if args.render_style:
        if args.job_root is None:
            parser.error('--render-style requires the current --job-root')
        render_style(args.project_root, args.render_style, json.loads(args.composition_json), args.job_root)
    elif args.render_web:
        render_web(args.project_root, args.render_web, json.loads(args.composition_json))
    else:
        print(json.dumps(check(args.project_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
