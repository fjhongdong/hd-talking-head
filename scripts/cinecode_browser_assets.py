"""Pin the browser libraries used by CineCode's unmodified native starters."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from adapter_kit import sha256_file
from native_result_reuse import source_unchanged

ASSET_DIRECTORY = 'assets/motion-native-runtime/cinecode'
JOB_DIRECTORY = 'cinecode-deps'
LOCK_SHA256 = '454220297c82d47df36a7b94d296dcdfe757374c6259c18a54a917562052e4fa'


def _locked_packages(project):
    location = Path(project) / ASSET_DIRECTORY / 'source-lock.json'
    payload = location.read_bytes()
    if hashlib.sha256(payload).hexdigest() != LOCK_SHA256:
        raise ValueError('CineCode browser dependency lock changed')
    return json.loads(payload)['packages']


def _files(packages):
    return {f'{group}/{name}': identity for group, package in packages.items()
            for name, identity in package['files'].items()}


def check_browser_assets(project):
    project = Path(project).resolve(strict=True)
    directory = project / ASSET_DIRECTORY
    packages = _locked_packages(project)
    expected = _files(packages)

    def verify(inventory):
        if directory.resolve() != directory or any(item.is_symlink() for item in inventory):
            raise ValueError('CineCode browser libraries must be regular package files')
        files = {item.relative_to(directory).as_posix(): item for item in inventory if item.is_file()}
        if set(files) != {*expected, 'source-lock.json'}:
            raise ValueError('CineCode browser dependency bundle is incomplete')
        for name, identity in expected.items():
            item = files[name]
            if item.stat().st_size != identity['byte_count'] or sha256_file(item) != identity['sha256']:
                raise ValueError('CineCode browser dependency changed: ' + name)

    source_unchanged(project, ('cinecode-browser-assets', LOCK_SHA256), directory, verify)
    return {group: {'version': package['version'], 'directory': str(directory / group),
                    'job_url': f'/{JOB_DIRECTORY}/{group}/'}
            for group, package in packages.items()}


def verify_job_dependencies(project, project_path, files):
    """Check any staged dependency against the lock using frozen project digests."""
    packages = _locked_packages(project)
    expected = _files(packages)
    prefix = f'{project_path}/{JOB_DIRECTORY}/'
    for item in files:
        name = item['job_path']
        if name.startswith(prefix):
            actual = {key: item[key] for key in ('sha256', 'byte_count')}
            if actual != expected.get(name[len(prefix):]):
                raise ValueError('CineCode Job browser dependency differs from its pinned source: ' + name)


def localize_browser_assets(project, directory, files):
    """Localize only exact pinned CDN prefixes in authored Job text before capture."""
    packages = _locked_packages(project)
    redirects = {group: f"https://cdn.jsdelivr.net/npm/{group}@{package['version']}/".encode()
                 for group, package in packages.items()}
    staged, changes = set(), {}
    for item in files:
        name = Path(item)
        if name.parts[0] == JOB_DIRECTORY or name.suffix not in {'.html', '.js', '.mjs'}:
            continue
        file = directory / name
        old = new = file.read_bytes()
        for group, prefix in redirects.items():
            if prefix in new:
                new = new.replace(prefix, f'/{JOB_DIRECTORY}/{group}/'.encode())
                staged.add(group)
        if new != old:
            changes[file] = new
    if not staged:
        return False
    source = Path(project) / ASSET_DIRECTORY
    for group in sorted(staged):
        for name, identity in packages[group]['files'].items():
            target = directory / JOB_DIRECTORY / group / name
            if target.exists():
                if (not target.is_file() or target.stat().st_size != identity['byte_count']
                        or sha256_file(target) != identity['sha256']):
                    raise ValueError('Existing CineCode Job dependency differs: ' + str(target))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / group / name, target)
    for file, content in changes.items():
        file.write_bytes(content)
    return True
