"""Prepare only the dependencies used by unmodified native motion renderers."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

PACKAGES = {'barty-motion-graphics': ('playwright', '1.64.0'), 'bang-motion': ('puppeteer', '25.3.0')}

def locked_files(project, dependency_id):
    name = PACKAGES[dependency_id][0]
    directory = Path(project) / 'skill-development/hd-talking-head/assets/motion-native-runtime' / name
    return {filename: directory / filename for filename in ('package.json', 'package-lock.json')}

def package_for(dependency_id):
    name, version = PACKAGES[dependency_id]
    return {'private': True, 'dependencies': {name: version}}


def runtime_root(project, *, dependency_id='barty-motion-graphics'):
    name, version = PACKAGES[dependency_id]
    root = Path(project).resolve(strict=True) / ('skill-development/runtime/motion-native-' + name + '-' + version)
    if root.resolve() != root.absolute():
        raise ValueError('Motion dependencies must stay in the separate project runtime directory')
    return root


def check(project, *, dependency_id='barty-motion-graphics'):
    name, version = PACKAGES[dependency_id]
    root = runtime_root(project, dependency_id=dependency_id)
    if json.loads((root / 'package.json').read_bytes()) != package_for(dependency_id):
        raise ValueError('Motion runtime package identity changed')
    lock = json.loads((root / 'package-lock.json').read_bytes())
    if lock != json.loads(locked_files(project, dependency_id)['package-lock.json'].read_bytes()):
        raise ValueError('Motion runtime lock differs from the bundled source')
    for name in (('playwright', 'playwright-core') if dependency_id == 'barty-motion-graphics' else ('puppeteer', 'puppeteer-core')):
        package = root / 'node_modules' / name / 'package.json'
        if (json.loads(package.read_bytes())['version'] != version
                or lock['packages']['node_modules/' + name]['version'] != version):
            raise ValueError('Motion runtime dependency identity changed: ' + name)
    tools = {name: shutil.which(name) for name in ('node', 'ffmpeg', 'ffprobe')}
    if not all(tools.values()):
        raise ValueError('Native motion rendering requires Node, FFmpeg and FFprobe')
    # Launch the same browser entry used by the original renderer. No shim or
    # replacement browser driver is injected into third-party code.
    script = "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();console.log(JSON.stringify({browser:chromium.executablePath(),version:b.version()}));await b.close()})().catch(e=>{console.error(e.message);process.exit(1)})"
    environment = {}
    if dependency_id == 'barty-motion-graphics' and (root / 'browsers').is_dir():
        environment['PLAYWRIGHT_BROWSERS_PATH'] = str(root / 'browsers')
    if dependency_id == 'bang-motion':
        from adapter_kit import browser_candidates
        browsers = browser_candidates(project)
        if not browsers:
            raise ValueError('Bang native rendering needs a prepared local Chrome browser')
        environment['PUPPETEER_EXECUTABLE_PATH'] = str(browsers[0].resolve(strict=True))
        script = "const p=require('puppeteer');(async()=>{const b=await p.launch({headless:'new'});console.log(JSON.stringify({browser:process.env.PUPPETEER_EXECUTABLE_PATH,version:await b.version()}));await b.close()})().catch(e=>{console.error(e.message);process.exit(1)})"
    result = subprocess.run([tools['node'], '-e', script], cwd=root, check=True,
                            capture_output=True, text=True, timeout=30, env={**os.environ, **environment})
    browser = json.loads(result.stdout)
    return {'status': 'ready', 'runtime_root': str(root), 'node_modules': str(root / 'node_modules'),
            'renderer_version': PACKAGES[dependency_id][0] + '-' + version, 'browser': browser['browser'],
            'browser_version': browser['version'], 'environment': environment, 'tools': tools}


def prepare(project, *, dependency_id='barty-motion-graphics'):
    name, version = PACKAGES[dependency_id]
    root = runtime_root(project, dependency_id=dependency_id)
    root.mkdir(parents=True, exist_ok=True)
    package = root / 'package.json'
    if package.exists() and json.loads(package.read_bytes()) != package_for(dependency_id):
        raise ValueError('Existing motion runtime differs; preserve it for review')
    for filename, source in locked_files(project, dependency_id).items():
        target = root / filename
        if target.exists() and json.loads(target.read_bytes()) != json.loads(source.read_bytes()):
            raise ValueError('Existing native motion lock differs; preserve it for review')
        if not target.exists():
            shutil.copyfile(source, target)
    if not (root / 'node_modules' / name / 'package.json').is_file():
        npm = shutil.which('npm')
        if not npm:
            raise ValueError('npm is required to prepare native motion dependencies')
        subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=root,
                       check=True, capture_output=True, text=True, timeout=600,
                       env={**os.environ, 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1', 'PUPPETEER_SKIP_DOWNLOAD': '1', 'npm_config_update_notifier': 'false'})
    if dependency_id == 'barty-motion-graphics':
        node = shutil.which('node')
        if not node:
            raise ValueError('Node is required for native motion preparation')
        environment = dict(os.environ)
        if (root / 'browsers').is_dir():
            environment['PLAYWRIGHT_BROWSERS_PATH'] = str(root / 'browsers')
        executable = subprocess.check_output([node, '-e', "process.stdout.write(require('playwright').chromium.executablePath())"],
                                              cwd=root, env=environment, text=True, timeout=15)
        if not Path(executable).is_file():
            environment['PLAYWRIGHT_BROWSERS_PATH'] = str(root / 'browsers')
            subprocess.run([node, str(root / 'node_modules/playwright/cli.js'), 'install', 'chromium'],
                           cwd=root, env=environment, check=True, capture_output=True, text=True, timeout=600)
    return check(project, dependency_id=dependency_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--dependency-id', default='barty-motion-graphics')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps((check if args.check else prepare)(args.project_root, dependency_id=args.dependency_id)))
