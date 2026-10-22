"""Export a code-only runtime; verify archives before installing into a new root."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


MANIFEST = 'runtime-manifest.json'
REQUIRED = {'edit/hd/__init__.py',
            'edit/hd/tools/__init__.py', 'edit/hd/tools/state.py',
            'edit/hd/tools/startup.py', 'edit/hd/tools/segment_render.py'}
REQUIRED.update('edit/v5/tools/' + name + '.py' for name in (
    'openlux_images', 'bold_subtitles', 'build_visual_plan', 'bold_layouts', 'style_tokens'))
MAX_BYTES = 64 * 1024 * 1024


def _allowed(name):
    path = PurePosixPath(name)
    return (name == path.as_posix() and '\\' not in name
            and not path.is_absolute() and '..' not in path.parts
            and (name == 'edit/__init__.py' or name in REQUIRED or
                 (path.parent == PurePosixPath('edit/hd/tools')
                  and path.suffix == '.py' and path.stem.isidentifier())))


def _local(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f'symlink path is forbidden: {path}')
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def export_bundle(project_root, output):
    project_root, output = _local(project_root), _local(output)
    names = set(REQUIRED)
    if (project_root / 'edit/__init__.py').exists() or (project_root / 'edit/__init__.py').is_symlink():
        names.add('edit/__init__.py')
    names.update(p.relative_to(project_root).as_posix()
                 for p in (project_root / 'edit/hd/tools').glob('*.py'))
    payloads = {}
    for name in sorted(names):
        path = _local(project_root / name)
        if not _allowed(name) or not path.is_file():
            raise ValueError(f'missing or invalid runtime source: {name}')
        payloads[name] = path.read_bytes()
    if sum(map(len, payloads.values())) > MAX_BYTES:
        raise ValueError('runtime exceeds bundle size limit')
    manifest = {'schema_version': 1, 'files': {
        name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}}
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
        for name, data in payloads.items():
            archive.writestr(name, data)
    return manifest


def _verified_payloads(bundle):
    with zipfile.ZipFile(_local(bundle)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or MANIFEST not in names:
            raise ValueError('duplicate entries or missing manifest')
        if len(infos) > 1000 or sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError('runtime exceeds bundle size limit')
        for info in infos:
            mode = info.external_attr >> 16
            if (info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or (info.filename != MANIFEST and not _allowed(info.filename))):
                raise ValueError(f'unsafe runtime entry: {info.filename}')
        manifest = json.loads(archive.read(MANIFEST), object_pairs_hook=_pairs)
        if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'files'}
                or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
                or not isinstance(manifest['files'], dict)):
            raise ValueError('invalid runtime manifest')
        files = manifest['files']
        if not REQUIRED <= files.keys() or set(names) != set(files) | {MANIFEST}:
            raise ValueError('missing or extra runtime entries')
        payloads = {}
        for name, expected in files.items():
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f'runtime hash mismatch: {name}')
            payloads[name] = data
        return manifest, payloads


def verify_bundle(bundle):
    return _verified_payloads(bundle)[0]


def install_bundle(bundle, project_root):
    manifest, payloads = _verified_payloads(bundle)
    project_root = _local(project_root)
    # Creating the root exclusively prevents accidental merging into an old runtime.
    project_root.mkdir()
    for name, data in payloads.items():
        path = project_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--project-root', type=Path, required=True)
    export.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--bundle', type=Path, required=True)
    install = commands.add_parser('install')
    install.add_argument('--bundle', type=Path, required=True)
    install.add_argument('--project-root', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'export':
        result = export_bundle(args.project_root, args.output)
    elif args.command == 'verify':
        result = verify_bundle(args.bundle)
    else:
        result = install_bundle(args.bundle, args.project_root)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
