"""Prepare the pinned original TalkCraft dependencies outside its source tree."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

RUNTIME_DIRECTORY = 'skill-development/runtime/talkcraft-native-ccb8a571'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_root(project):
    project = Path(project).resolve(strict=True)
    root = project / RUNTIME_DIRECTORY
    if root.resolve() != root.absolute():
        raise ValueError('TalkCraft native dependencies must use the project runtime directory')
    return root


def check(project):
    from talkcraft_skill_adapter import source_root, UPSTREAM_COMMIT
    from adapter_kit import browser_candidates
    source = source_root(project) / 'runtime'
    root = runtime_root(project)
    for name in ('package.json', 'package-lock.json'):
        if not (root / name).is_file() or (root / name).read_bytes() != (source / name).read_bytes():
            raise ValueError('TalkCraft native dependencies need their unmodified original package and lock files')
    manifest = json.loads((source / 'package.json').read_bytes())
    versions = {}
    for name, version in {**manifest['dependencies'], **manifest['devDependencies']}.items():
        package = root / 'node_modules' / name / 'package.json'
        if not package.is_file() or json.loads(package.read_bytes())['version'] != version:
            raise ValueError('TalkCraft native dependency is missing or has changed: ' + name)
        versions[name] = version
    tools = {name: shutil.which(name) for name in ('node', 'ffmpeg', 'ffprobe')}
    if not all(tools.values()):
        raise ValueError('TalkCraft native rendering requires Node, FFmpeg and FFprobe')
    browsers = browser_candidates(project)
    if not browsers:
        raise ValueError('TalkCraft native rendering needs a local prepared Chrome browser; no automatic download')
    browser = browsers[0].resolve(strict=True)
    script = "const {createRequire}=require('node:module');const r=createRequire(process.argv[1]);if(typeof r('@remotion/bundler').bundle!=='function'||typeof r('@remotion/renderer').renderMedia!=='function'||typeof r('remotion').registerRoot!=='function'||!r('@remotion/cli').CliInternals)throw Error('native Remotion API unavailable');"
    subprocess.run([tools['node'], '-e', script, str(root / 'package.json')], check=True,
                   capture_output=True, text=True, timeout=30)
    return {'status': 'ready', 'upstream_commit': UPSTREAM_COMMIT, 'runtime_root': str(root),
            'node_modules': str(root / 'node_modules'), 'renderer_version': versions['@remotion/renderer'],
            'package_sha256': _sha(root / 'package.json'), 'lock_sha256': _sha(root / 'package-lock.json'),
            'browser': str(browser), 'browser_sha256': _sha(browser), 'tools': tools}


def prepare(project):
    from talkcraft_skill_adapter import source_root
    source = source_root(project) / 'runtime'
    root = runtime_root(project)
    root.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'package-lock.json'):
        target = root / name
        if target.exists() and target.read_bytes() != (source / name).read_bytes():
            raise ValueError('Existing TalkCraft native runtime identity changed; preserve it for review')
        if not target.exists():
            shutil.copyfile(source / name, target)
    try:
        return check(project)
    except ValueError:
        pass
    npm = shutil.which('npm')
    if not npm:
        raise ValueError('npm is required to prepare the original locked TalkCraft dependencies')
    result = subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
                            cwd=root, capture_output=True, text=True, timeout=600,
                            env={**os.environ, 'npm_config_update_notifier': 'false'})
    if result.returncode:
        raise ValueError('Locked TalkCraft native dependency preparation failed: ' + result.stderr[-2000:])
    return check(project)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps((check if args.check else prepare)(args.project_root.resolve(strict=True)), ensure_ascii=False))


if __name__ == '__main__':
    main()
