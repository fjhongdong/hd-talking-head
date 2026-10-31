"""Prepare only the dependencies used by unmodified native motion renderers."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from adapter_kit import sha256_file

PACKAGES = {'barty-motion-graphics': ('playwright', '1.64.0'), 'bang-motion': ('puppeteer', '25.3.0'),
            'mg-styles-15': ('puppeteer-core', '25.12.0'), 'video-shotcraft': ('remotion', '4.0.484')}

BLENDER_VERSION = '5.1.2'
BLENDER_ARCHIVES = {
    ('Darwin', 'arm64'): ('blender-5.1.2-macos-arm64.dmg',
        'f104ffee2ba6aee32328e5c203b7e4608d8a1745f7bbcf2766f3b9777e8fbe17',
        'Blender.app/Contents/MacOS/Blender'),
}


def _blender_distribution():
    try:
        filename, digest, executable = BLENDER_ARCHIVES[(platform.system(), platform.machine())]
    except KeyError as error:
        raise ValueError('Project-local Blender preparation requires this package target: macOS arm64') from error
    return {'filename': filename, 'sha256': digest, 'executable': executable,
            'url': 'https://download.blender.org/release/Blender5.1/' + filename}


def blender_runtime_root(project):
    root = Path(project).resolve(strict=True) / ('skill-development/runtime/motion-native-blender-' + BLENDER_VERSION)
    if root.resolve() != root.absolute():
        raise ValueError('Blender must stay in the separate project runtime directory')
    return root


def blender_environment(project):
    root = blender_runtime_root(project)
    inherited = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME'}}
    return {**inherited, 'BLENDER_USER_RESOURCES': str(root / 'user-resources'),
            'XDG_CACHE_HOME': str(root / 'cache'), 'PYTHONDONTWRITEBYTECODE': '1'}


def prepare_template_dependencies(project, *, dependency_id, template_id):
    if (dependency_id, template_id) != ('mg-styles-15', '3d-render'):
        return {'status': 'not_required'}
    root = blender_runtime_root(project)
    distribution = _blender_distribution()
    if root.exists():
        return check_template_dependencies(project, dependency_id=dependency_id, template_id=template_id)
    root.parent.mkdir(parents=True, exist_ok=True)
    downloads = root.parent / ('motion-native-blender-' + BLENDER_VERSION + '-downloads')
    downloads.mkdir(exist_ok=True)
    archive = downloads / distribution['filename']
    if not archive.exists():
        subprocess.run(['curl', '--fail', '--location', '--output', str(archive), distribution['url']],
                       check=True, capture_output=True, text=True, timeout=600)
    archive_sha = sha256_file(archive)
    if archive_sha != distribution['sha256']:
        raise ValueError('Blender archive differs from its official pinned SHA256; preserve it and stop')
    with tempfile.TemporaryDirectory(prefix='.blender-install-', dir=root.parent) as temporary:
        stage = Path(temporary); installed = stage / 'installed'; installed.mkdir()
        mount = stage / 'mount'; mount.mkdir()
        subprocess.run(['hdiutil', 'attach', str(archive), '-readonly', '-nobrowse', '-mountpoint', str(mount)],
                       check=True, capture_output=True, text=True, timeout=60)
        try:
            shutil.copytree(mount / 'Blender.app', installed / 'Blender.app', symlinks=True)
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True, text=True, timeout=60)
        executable = installed / distribution['executable']
        executable_sha = sha256_file(executable)
        (installed / 'source.json').write_text(json.dumps({**distribution, 'version': BLENDER_VERSION,
            'executable_sha256': executable_sha}, indent=2) + '\n')
        installed.rename(root)
    return check_template_dependencies(project, dependency_id=dependency_id, template_id=template_id)

def locked_files(project, dependency_id):
    name = PACKAGES[dependency_id][0]
    directory = Path(project) / 'skill-development/hd-talking-head/assets/motion-native-runtime' / name
    return {filename: directory / filename for filename in ('package.json', 'package-lock.json')}

def package_for(dependency_id):
    name, version = PACKAGES[dependency_id]
    if dependency_id in {'mg-styles-15', 'video-shotcraft'}:
        return json.loads(locked_files(Path(__file__).resolve().parents[3], dependency_id)['package.json'].read_bytes())
    return {'private': True, 'dependencies': {name: version}}


def runtime_root(project, *, dependency_id='barty-motion-graphics'):
    name, version = PACKAGES[dependency_id]
    root = Path(project).resolve(strict=True) / ('skill-development/runtime/motion-native-' + name + '-' + version)
    if root.resolve() != root.absolute():
        raise ValueError('Motion dependencies must stay in the separate project runtime directory')
    return root


def _minimum_node(project, dependency_id):
    name = PACKAGES[dependency_id][0]
    lock = json.loads(locked_files(project, dependency_id)['package-lock.json'].read_bytes())
    requirement = (lock['packages']['']['engines']['node'] if dependency_id in {'mg-styles-15', 'video-shotcraft'}
                   else lock['packages']['node_modules/' + name]['engines']['node'])
    if not re.fullmatch(r'>=\d+(?:\.\d+){0,2}', requirement):
        raise ValueError('Unsupported locked Node requirement: ' + requirement)
    parts = tuple(int(part) for part in requirement[2:].split('.'))
    return requirement, parts + (0,) * (3 - len(parts))


def _validate_node_version(project, dependency_id, version):
    requirement, minimum = _minimum_node(project, dependency_id)
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+][\w.-]+)?', version)
    if not match or tuple(map(int, match.groups())) < minimum:
        raise ValueError(dependency_id + ' requires Node ' + requirement + '; found ' + version
                         + '. Install a supported Node version before preparing native motion.')


def _tool_version(executable, name):
    result = subprocess.run([executable, '--version' if name == 'node' else '-version'],
                            check=True, capture_output=True, text=True, timeout=15)
    lines = result.stdout.strip().splitlines()
    if not lines or not lines[0].strip():
        raise ValueError('Cannot read native motion tool version: ' + name)
    return lines[0].strip()


def _node_preflight(project, dependency_id):
    node = shutil.which('node')
    if not node:
        raise ValueError('Node is required for native motion preparation and rendering')
    version = _tool_version(node, 'node')
    _validate_node_version(project, dependency_id, version)
    return node, version


def validate_runtime_identity(project, identity, *, dependency_id):
    """Validate a frozen generation identity without requiring its old tools."""
    name, version = PACKAGES[dependency_id]
    if (not isinstance(identity, dict)
            or set(identity) != {'schema_version', 'dependency_id', 'renderer_version', 'lock_sha256', 'tools', 'browser'}
            or identity['schema_version'] != 1 or identity['dependency_id'] != dependency_id
            or identity['renderer_version'] != name + '-' + version
            or identity['lock_sha256'] != hashlib.sha256(locked_files(project, dependency_id)['package-lock.json'].read_bytes()).hexdigest()
            or not isinstance(identity['tools'], dict) or set(identity['tools']) != {'node', 'ffmpeg', 'ffprobe'}):
        raise ValueError('Frozen native motion runtime identity differs from its locked dependency')
    for item in [*identity['tools'].values(), identity['browser']]:
        if (not isinstance(item, dict) or set(item) != {'path', 'version'}
                or not isinstance(item['path'], str) or not Path(item['path']).is_absolute()
                or not isinstance(item['version'], str) or not item['version'].strip()):
            raise ValueError('Frozen native motion runtime requires actual tool and browser versions')
    _validate_node_version(project, dependency_id, identity['tools']['node']['version'])
    return identity


def check(project, *, dependency_id='barty-motion-graphics', mode='render'):
    name, version = PACKAGES[dependency_id]
    if mode not in {'render', 'reuse'}:
        raise ValueError('Unknown native motion runtime check mode')
    if mode == 'reuse':
        ffprobe = shutil.which('ffprobe')
        if not ffprobe:
            raise ValueError('Frozen native motion media inspection requires FFprobe')
        return {'status': 'ready', 'tools': {'ffprobe': ffprobe},
                'tool_versions': {'ffprobe': _tool_version(ffprobe, 'ffprobe')}}
    node, node_version = _node_preflight(project, dependency_id)
    root = runtime_root(project, dependency_id=dependency_id)
    if json.loads((root / 'package.json').read_bytes()) != package_for(dependency_id):
        raise ValueError('Motion runtime package identity changed')
    lock = json.loads((root / 'package-lock.json').read_bytes())
    if lock != json.loads(locked_files(project, dependency_id)['package-lock.json'].read_bytes()):
        raise ValueError('Motion runtime lock differs from the bundled source')
    packages = (('playwright', 'playwright-core') if dependency_id == 'barty-motion-graphics' else
                ('puppeteer', 'puppeteer-core') if dependency_id == 'bang-motion' else
                tuple(package_for(dependency_id)['dependencies']))
    for package_name in packages:
        expected_version = package_for(dependency_id)['dependencies'].get(package_name, version)
        package = root / 'node_modules' / package_name / 'package.json'
        if (json.loads(package.read_bytes())['version'] != expected_version
                or lock['packages']['node_modules/' + package_name]['version'] != expected_version):
            raise ValueError('Motion runtime dependency identity changed: ' + package_name)
    tools = {'node': node, **{tool: shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')}}
    if not all(tools.values()):
        raise ValueError('Native motion rendering requires Node, FFmpeg and FFprobe')
    versions = {'node': node_version, **{tool: _tool_version(tools[tool], tool) for tool in ('ffmpeg', 'ffprobe')}}
    # Launch the same browser entry used by the original renderer. No shim or
    # replacement browser driver is injected into third-party code.
    script = "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();console.log(JSON.stringify({browser:chromium.executablePath(),version:b.version()}));await b.close()})().catch(e=>{console.error(e.message);process.exit(1)})"
    environment = {}
    if dependency_id == 'barty-motion-graphics' and (root / 'browsers').is_dir():
        environment['PLAYWRIGHT_BROWSERS_PATH'] = str(root / 'browsers')
    if dependency_id in {'bang-motion', 'mg-styles-15', 'video-shotcraft'}:
        from adapter_kit import browser_candidates
        browsers = browser_candidates(project)
        if not browsers:
            raise ValueError('Native motion rendering needs a prepared local Chrome browser')
        environment['PUPPETEER_EXECUTABLE_PATH'] = str(browsers[0].resolve(strict=True))
        module = 'puppeteer-core' if dependency_id == 'mg-styles-15' else 'puppeteer'
        script = "const p=require('NATIVE_BROWSER_DRIVER');(async()=>{const b=await p.launch({headless:'new',executablePath:process.env.PUPPETEER_EXECUTABLE_PATH});console.log(JSON.stringify({browser:process.env.PUPPETEER_EXECUTABLE_PATH,version:await b.version()}));await b.close()})().catch(e=>{console.error(e.message);process.exit(1)})".replace('NATIVE_BROWSER_DRIVER', module)
        if dependency_id == 'mg-styles-15':
            environment['MG_CHROME'] = environment['PUPPETEER_EXECUTABLE_PATH']
            environment['MG_RENDER_SLOTS'] = '1'
        if dependency_id == 'video-shotcraft':
            script = "const {execFileSync}=require('node:child_process');const p=process.env.PUPPETEER_EXECUTABLE_PATH;require('@remotion/cli/package.json');console.log(JSON.stringify({browser:p,version:execFileSync(p,['--version'],{encoding:'utf8'}).trim()}))"
    result = subprocess.run([tools['node'], '-e', script], cwd=root, check=True,
                            capture_output=True, text=True, timeout=30, env={**os.environ, **environment})
    browser = json.loads(result.stdout)
    identity = {'schema_version': 1, 'dependency_id': dependency_id,
                'renderer_version': name + '-' + version,
                'lock_sha256': hashlib.sha256(locked_files(project, dependency_id)['package-lock.json'].read_bytes()).hexdigest(),
                'tools': {tool: {'path': executable, 'version': versions[tool]} for tool, executable in tools.items()},
                'browser': {'path': browser['browser'], 'version': browser['version']}}
    validate_runtime_identity(project, identity, dependency_id=dependency_id)
    return {'status': 'ready', 'runtime_root': str(root), 'node_modules': str(root / 'node_modules'),
            'renderer_version': PACKAGES[dependency_id][0] + '-' + version, 'browser': browser['browser'],
            'browser_version': browser['version'], 'environment': environment, 'tools': tools,
            'tool_versions': versions, 'runtime_identity': identity}


def check_template_dependencies(project, *, dependency_id, template_id, mode='render'):
    """Check Blender only for new creation with the selected original 3D style."""
    if mode not in {'render', 'reuse'}:
        raise ValueError('Unknown native template dependency check mode')
    if mode == 'reuse' or (dependency_id, template_id) != ('mg-styles-15', '3d-render'):
        return {'status': 'not_required'}
    root = blender_runtime_root(project)
    distribution = _blender_distribution()
    local = root / distribution['executable']
    if root.exists() and not local.is_file():
        raise ValueError('Project-local Blender installation is incomplete; preserve it and stop')
    executable = str(local) if local.is_file() else shutil.which('blender')
    application = Path('/Applications/Blender.app/Contents/MacOS/Blender')
    if executable is None and application.is_file():
        executable = str(application)
    if executable is None:
        raise ValueError('MG 3d-render requires Blender 5.1 with Cycles before visual confirmation; '
                         'Blender is not installed. Preserve this template and stop its preparation.')
    if executable == str(local):
        metadata = json.loads((root / 'source.json').read_bytes())
        if metadata.get('version') != BLENDER_VERSION or any(metadata.get(key) != value for key, value in distribution.items()):
            raise ValueError('Project-local Blender source identity changed')
        digest = sha256_file(local)
        if digest != metadata.get('executable_sha256'):
            raise ValueError('Project-local Blender executable changed')
    expression = ("import bpy,json; print('HD_MG_BLENDER=' + json.dumps({'version':list(bpy.app.version),"
                  "'cycles':bool(bpy.app.build_options.cycles)}))")
    result = subprocess.run([executable, '--background', '--factory-startup', '--python-expr', expression],
                            capture_output=True, text=True, check=True, timeout=30, env=blender_environment(project))
    records = [line[len('HD_MG_BLENDER='):] for line in result.stdout.splitlines()
               if line.startswith('HD_MG_BLENDER=')]
    identity = json.loads(records[0]) if len(records) == 1 else {}
    if (not isinstance(identity.get('version'), list) or identity['version'][:2] != [5, 1]
            or identity.get('cycles') is not True):
        raise ValueError('MG 3d-render requires the original Blender 5.1/Cycles environment')
    binary_sha = sha256_file(executable)
    return {'status': 'ready', 'blender': str(Path(executable).resolve(strict=True)),
            'executable_sha256': binary_sha, **identity}


def prepare(project, *, dependency_id='barty-motion-graphics'):
    name, version = PACKAGES[dependency_id]
    node, _ = _node_preflight(project, dependency_id)
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
    parser.add_argument('--template-id', help='Prepare/check this selected native template only')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.template_id:
        action = check_template_dependencies if args.check else prepare_template_dependencies
        print(json.dumps(action(args.project_root, dependency_id=args.dependency_id, template_id=args.template_id)))
    else:
        print(json.dumps((check if args.check else prepare)(args.project_root, dependency_id=args.dependency_id)))
