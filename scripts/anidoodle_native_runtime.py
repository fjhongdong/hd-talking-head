"""Reuse existing package-local native build/browser dependencies without installing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from adapter_kit import sha256_file
from package_paths import PACKAGE_ROOT

RENDERER_VERSION = 'anidoodle-0.10.1-9c20e77467be'
EXPECTED_PACKAGES = {'esbuild': '0.25.12', 'playwright': '1.64.0', 'playwright-core': '1.64.0'}
RUNTIME_PACKAGES = {
    'esbuild': 'runtime/hyperframes-0.8.167/node_modules/esbuild',
    'playwright': 'runtime/motion-native-playwright-1.64.0/node_modules/playwright',
    'playwright-core': 'runtime/motion-native-playwright-1.64.0/node_modules/playwright-core',
}


def check(project=PACKAGE_ROOT, *, mode='render'):
    project = Path(project).resolve(strict=True)
    if mode == 'reuse':
        ffprobe = shutil.which('ffprobe')
        if not ffprobe:
            raise ValueError('Anidoodle result inspection requires FFprobe')
        return {'status': 'ready', 'tools': {'ffprobe': ffprobe}, 'renderer_version': RENDERER_VERSION}
    if mode != 'render':
        raise ValueError('Unknown Anidoodle runtime check mode')
    tools = {key: shutil.which(key) for key in ('node', 'ffmpeg', 'ffprobe')}
    if not all(tools.values()):
        raise ValueError('Anidoodle requires existing Node, FFmpeg and FFprobe')
    versions = {key: subprocess.check_output([value, '--version' if key == 'node' else '-version'],
                text=True, timeout=15).splitlines()[0] for key, value in tools.items()}
    parts = tuple(map(int, re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', versions['node']).groups()))
    if parts < (22, 15, 0):
        raise ValueError('The isolated Anidoodle dependency resolver requires Node >=22.15')
    packages = {}
    for name, relative in RUNTIME_PACKAGES.items():
        root = project / relative
        package = root / 'package.json'
        if not package.is_file() or json.loads(package.read_bytes()).get('version') != EXPECTED_PACKAGES[name]:
            raise ValueError('Prepare the existing package-local dependency before Anidoodle: ' + relative)
        packages[name] = {'root': str(root), 'version': EXPECTED_PACKAGES[name],
                          'package_sha256': sha256_file(package)}
    helper = project / 'scripts/anidoodle_node_runtime.mjs'
    environment = {'NODE_OPTIONS': '--import=' + helper.as_uri(),
                   'ANIDOODLE_ESBUILD_ENTRY': str(Path(packages['esbuild']['root']) / 'lib/main.js'),
                   'NODE_PATH': str(Path(packages['playwright-core']['root']).parent),
                   'PLAYWRIGHT_BROWSERS_PATH': str(project / 'runtime/motion-native-playwright-1.64.0/browsers'),
                   'ANIDOODLE_BAKE_CACHE': '0', 'FFMPEG': tools['ffmpeg'],
                   'PYTHONDONTWRITEBYTECODE': '1'}
    engine = project / 'vendor/anidoodle/skills/anidoodle/engine'
    code = ('import {detect} from ' + json.dumps((engine / 'tools/detect.mjs').as_uri()) + ';'
            'const d=detect(); if(d.chosen!=="playwright") throw new Error(JSON.stringify(d.report));'
            'console.log(JSON.stringify({browser:d.browser,pwVersion:d.pw.version}));')
    found = json.loads(subprocess.check_output([tools['node'], '--input-type=module', '-e', code],
        cwd=project, env={**os.environ, **environment}, text=True, timeout=30))
    browser_path = found['browser'].get('launches') or found['browser'].get('executablePath')
    if found['pwVersion'] != EXPECTED_PACKAGES['playwright-core'] or not browser_path:
        raise ValueError('Anidoodle did not select the checked browser dependency')
    browser = Path(browser_path).resolve(strict=True)
    browser_version = subprocess.check_output([str(browser), '--version'], text=True, timeout=15).strip()
    identity = {'schema_version': 1, 'dependency_id': 'anidoodle', 'renderer_version': RENDERER_VERSION,
                'tools': {key: {'path': value, 'version': versions[key]} for key, value in tools.items()},
                'browser': {'path': str(browser), 'version': browser_version},
                'packages': packages, 'resolver_sha256': sha256_file(helper)}
    return {'status': 'ready', 'tools': tools, 'browser': str(browser), 'environment': environment,
            'runtime_identity': identity, 'renderer_version': RENDERER_VERSION}


def validate_identity(project, identity):
    """Result reuse binds the actual resolver and dependency versions, not a fake npm lock."""
    project = Path(project).resolve(strict=True)
    if (not isinstance(identity, dict) or identity.get('schema_version') != 1
            or identity.get('dependency_id') != 'anidoodle'
            or identity.get('renderer_version') != RENDERER_VERSION
            or identity.get('resolver_sha256') != sha256_file(project / 'scripts/anidoodle_node_runtime.mjs')
            or set(identity.get('tools', {})) != {'node', 'ffmpeg', 'ffprobe'}
            or set(identity.get('packages', {})) != set(EXPECTED_PACKAGES)):
        raise ValueError('Anidoodle execution runtime identity changed')
    for name, expected in EXPECTED_PACKAGES.items():
        row = identity['packages'][name]
        package = project / RUNTIME_PACKAGES[name] / 'package.json'
        if (row.get('root') != str(package.parent) or row.get('version') != expected
                or row.get('package_sha256') != sha256_file(package)):
            raise ValueError('Anidoodle native dependency changed: ' + name)
    for item in [*identity['tools'].values(), identity.get('browser', {})]:
        if (not isinstance(item, dict) or set(item) != {'path', 'version'}
                or not Path(item['path']).is_absolute() or not item['version']):
            raise ValueError('Anidoodle requires actual recorded tools and browser')
    return identity
