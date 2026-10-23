"""Export and install the complete Skill using its existing release manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from verify_skill_release import MANIFEST, REQUIRED, verify_release

IMPLEMENTATION = "skill-development/hd-talking-head"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def export_bundle(project_root, output):
    root, output = Path(project_root).resolve(), Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("bundle output must be outside the Skill")
    report = verify_release(root / IMPLEMENTATION)
    if report["status"] != "pass":
        raise ValueError("Skill release verification failed")
    manifest = json.loads((root / MANIFEST).read_text())
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in [*manifest["files"], MANIFEST]:
            archive.write(root / name, name)
    return manifest


def _check(archive):
    infos = archive.infolist()
    names = [item.filename for item in infos]
    if len(names) != len(set(names)) or MANIFEST not in names:
        raise ValueError("duplicate entries or missing release manifest")
    for item in infos:
        path = PurePosixPath(item.filename)
        if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                or path.as_posix() != item.filename or item.is_dir()
                or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise ValueError("invalid release file: " + item.filename)
    manifest = json.loads(archive.read(MANIFEST), object_pairs_hook=_unique_object)
    if (set(manifest) != {"schema_version", "release_id", "files"}
            or manifest["schema_version"] != 1
            or not isinstance(manifest["files"], dict)
            or not REQUIRED.issubset(manifest["files"])
            or set(names) != set(manifest["files"]) | {MANIFEST}):
        raise ValueError("incomplete Skill release")
    for name, expected in manifest["files"].items():
        digest = hashlib.sha256()
        with archive.open(name) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError("Skill file changed: " + name)
    return manifest


def verify_bundle(bundle):
    with zipfile.ZipFile(bundle) as archive:
        return _check(archive)


def install_bundle(bundle, project_root):
    if Path(project_root).is_symlink():
        raise ValueError("installation target must be a new directory")
    root = Path(project_root).resolve()
    with zipfile.ZipFile(bundle) as archive:
        manifest = _check(archive)
        root.mkdir()
        for item in archive.infolist():
            destination = root / item.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src, destination.open("xb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(block)
            mode = (item.external_attr >> 16) & 0o777
            if mode:
                destination.chmod(mode)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--project-root", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    install = commands.add_parser("install")
    install.add_argument("--bundle", type=Path, required=True)
    install.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = export_bundle(args.project_root, args.output)
    elif args.command == "verify":
        result = verify_bundle(args.bundle)
    else:
        result = install_bundle(args.bundle, args.project_root)
    print(json.dumps({"status": "pass", "release_id": result["release_id"],
                      "files": len(result["files"])}))


if __name__ == "__main__":
    main()
