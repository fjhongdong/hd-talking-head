"""Deterministic local runtime tree identities, not a hostile-process sandbox."""
import hashlib
import json
import os
from pathlib import Path
import stat
import re
import subprocess
import tempfile
import time


def _macho_output(path, timeout):
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(["/usr/bin/otool", "-arch", "all", "-L", str(path)],
                                stdout=output, stderr=subprocess.DEVNULL, timeout=timeout)
        if result.returncode:
            raise ValueError("Mach-O dependency inspection failed")
        output.seek(0)
        raw = output.read(1048577)
        if len(raw) > 1048576:
            raise ValueError("Mach-O dependency output limit exceeded")
        return raw.decode("utf-8", errors="strict")


def discover_macho_libraries(executable):
    """Discover absolute static load dependencies, not arbitrary dlopen libraries."""
    deadline = time.monotonic() + 30
    root = Path(executable)
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError("Mach-O entry must be a resolved absolute path")
    pending, identities, aliases = [root], {}, {}
    try:
        while pending:
            path = pending.pop()
            if path in identities:
                continue
            if len(identities) >= 513 or time.monotonic() >= deadline:
                raise ValueError("Mach-O discovery limit exceeded")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("Mach-O dependency is not a file")
                digest = hashlib.sha256()
                for block in iter(lambda: source.read(65536), b""):
                    digest.update(block)
                if _stamp(before) != _stamp(os.fstat(source.fileno())):
                    raise ValueError("Mach-O dependency changed")
            identities[path] = digest.hexdigest()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Mach-O discovery deadline exceeded")
            for name in parse_macho_dependencies(_macho_output(path, min(10, remaining))):
                if name.startswith(("/usr/lib/", "/System/Library/")):
                    continue
                target = Path(name).resolve(strict=True)
                if target == root:
                    raise ValueError("Mach-O library references executable")
                aliases.setdefault(target, set()).add(name)
                if sum(len(items) for items in aliases.values()) > 512:
                    raise ValueError("Mach-O load path limit exceeded")
                if target not in identities:
                    pending.append(target)
        result = [{"path": str(path), "sha256": identities[path], "load_paths": sorted(paths)}
                  for path, paths in sorted(aliases.items())]
        for path, digest in identities.items():
            _verify_file(path, digest, executable=False)
        for item in result:
            _verify_load_paths(item)
        if time.monotonic() >= deadline:
            raise ValueError("Mach-O discovery deadline exceeded")
        return result
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Mach-O dependency discovery failed") from exc


def parse_macho_dependencies(text):
    """Parse otool -arch all -L output, refusing unresolved loader tokens."""
    if type(text) is not str or len(text) > 1048576 or "\x00" in text:
        raise ValueError("invalid Mach-O dependency output")
    dependencies = set()
    header = False
    for line in text.splitlines():
        if not line:
            continue
        if not line.startswith("\t"):
            if not line.startswith("/") or not line.endswith(":"):
                raise ValueError("invalid Mach-O dependency header")
            header = True
            continue
        match = re.fullmatch(r"\t(.+) \(compatibility version [0-9]+(?:\.[0-9]+)*, current version [0-9]+(?:\.[0-9]+)*\)", line)
        if not header or match is None:
            raise ValueError("invalid Mach-O dependency record")
        name = match.group(1)
        path = Path(name)
        if (not path.is_absolute() or ".." in path.parts or str(path) != name
                or any(ord(char) < 32 for char in name)):
            raise ValueError("unresolved Mach-O dependency path")
        dependencies.add(name)
    if not dependencies:
        raise ValueError("empty Mach-O dependency output")
    return sorted(dependencies)


def normalize_contracts(value):
    """Validate explicit runtime identities; this does not approve their source."""
    names = {"node", "playwright", "browser", "ffmpeg", "ffprobe"}
    if type(value) is not dict or set(value) != names:
        raise ValueError("runtime contracts must contain exactly five tools")

    def absolute(path):
        if type(path) is not str or not path or "\x00" in path:
            raise ValueError("invalid runtime path")
        result = Path(path)
        if not result.is_absolute() or ".." in result.parts or str(result) != path:
            raise ValueError("runtime path must be canonical absolute")
        return result

    def digest(value):
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("invalid runtime digest")

    for name, contract in value.items():
        if type(contract) is not dict:
            raise ValueError("invalid runtime contract")
        kind = "directory_tree" if name in {"playwright", "browser"} else "file_snapshot"
        fields = {"kind", "path", "version", "roots" if kind == "directory_tree" else "sha256"}
        if kind == "file_snapshot" and "libraries" in contract:
            fields.add("libraries")
        if kind == "file_snapshot" and "library_discovery" in contract:
            fields.add("library_discovery")
            if contract["library_discovery"] != "mach_o_static_v1" or "libraries" not in contract:
                raise ValueError("invalid runtime library discovery")
        if set(contract) != fields or contract["kind"] != kind:
            raise ValueError("runtime contract fields or kind invalid")
        path = absolute(contract["path"])
        version = contract["version"]
        if type(version) is not str or not version.strip() or len(version) > 128 or any(ord(c) < 32 for c in version):
            raise ValueError("invalid runtime version")
        if kind == "file_snapshot":
            digest(contract["sha256"])
            libraries = contract.get("libraries", [])
            if type(libraries) is not list or len(libraries) > 512:
                raise ValueError("invalid runtime libraries")
            paths = {path}
            load_paths = set()
            for library in libraries:
                if type(library) is not dict or set(library) not in ({"path", "sha256"}, {"path", "sha256", "load_paths"}):
                    raise ValueError("invalid runtime library fields")
                library_path = absolute(library["path"])
                if library_path in paths:
                    raise ValueError("duplicate runtime library path")
                paths.add(library_path)
                digest(library["sha256"])
                if "library_discovery" in contract and "load_paths" not in library:
                    raise ValueError("static library discovery requires load paths")
                if "load_paths" in library:
                    aliases = library["load_paths"]
                    if type(aliases) is not list or not 1 <= len(aliases) <= 512:
                        raise ValueError("invalid runtime library load paths")
                    for alias in aliases:
                        alias_path = absolute(alias)
                        if alias_path in load_paths:
                            raise ValueError("duplicate runtime library load path")
                        load_paths.add(alias_path)
                        if len(load_paths) > 512:
                            raise ValueError("runtime library load path limit exceeded")
        else:
            roots = contract["roots"]
            if type(roots) is not list or not 1 <= len(roots) <= 16:
                raise ValueError("invalid runtime roots")
            paths = []
            for root in roots:
                if type(root) is not dict or set(root) != {"path", "sha256"}:
                    raise ValueError("invalid runtime root fields")
                paths.append(absolute(root["path"]))
                digest(root["sha256"])
            if len(set(paths)) != len(paths) or not any(root in path.parents for root in paths):
                raise ValueError("runtime entry must be inside unique declared roots")
    return json.loads(json.dumps(value))


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _verify_file(path, expected, executable):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or (executable and not before.st_mode & 0o111):
                raise ValueError("runtime file identity invalid")
            digest = hashlib.sha256()
            for block in iter(lambda: source.read(65536), b""):
                digest.update(block)
            if (_stamp(before) != _stamp(os.fstat(source.fileno()))
                    or _stamp(before) != _stamp(path.lstat())
                    or digest.hexdigest() != expected):
                raise ValueError("runtime file identity mismatch: " + str(path))
    except OSError as exc:
        raise ValueError("runtime file identity unavailable: " + str(path)) from exc


def verify_contracts(value):
    """Check current local bytes; callers must also verify after execution."""
    contracts = normalize_contracts(value)
    for name, contract in contracts.items():
        path = Path(contract["path"])
        if path.is_symlink() or not path.is_file() or (name != "playwright" and not os.access(path, os.X_OK)):
            raise ValueError("runtime entry identity invalid: " + name)
        if contract["kind"] == "directory_tree":
            for root in contract["roots"]:
                if tree_identity(root["path"])["sha256"] != root["sha256"]:
                    raise ValueError("runtime directory identity mismatch: " + name)
        else:
            _verify_file(path, contract["sha256"], executable=True)
            # Explicit declarations only: discovery must establish closure completeness.
            for library in contract.get("libraries", []):
                _verify_load_paths(library)
                _verify_file(Path(library["path"]), library["sha256"], executable=False)
                _verify_load_paths(library)
            if "library_discovery" in contract:
                declared = sorted(({**item, "load_paths": sorted(item["load_paths"])}
                                   for item in contract["libraries"]), key=lambda item: item["path"])
                if discover_macho_libraries(path) != declared:
                    raise ValueError("runtime static library identity mismatch: " + name)
                _verify_file(path, contract["sha256"], executable=True)
    return contracts


def _verify_load_paths(library):
    """Bind resolved load destinations, not every intermediate symlink spelling."""
    if "load_paths" not in library:
        return
    try:
        target = Path(library["path"])
        if target.resolve(strict=True) != target:
            raise ValueError("runtime library identity target is not resolved")
        for alias in library.get("load_paths", []):
            if Path(alias).resolve(strict=True) != target:
                raise ValueError("runtime library load identity changed")
    except (OSError, RuntimeError) as exc:
        raise ValueError("runtime library load identity unavailable") from exc


def tree_identity(directory):
    """Hash an explicitly chosen dependency closure; never infer its completeness."""
    root = Path(directory)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("runtime root must be an absolute nonsymlink directory")
    root = root.resolve(strict=True)
    records, checked = [], []
    file_count = total_bytes = 0

    def visit(path):
        nonlocal file_count, total_bytes
        if len(checked) >= 100000:
            raise ValueError("runtime entry limit exceeded")
        before = path.lstat()
        checked.append((path, _stamp(before)))
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(before.st_mode):
            target = path.resolve(strict=True)
            if target != root and root not in target.parents:
                raise ValueError("runtime symlink escapes root")
            records.append([relative, "symlink", os.readlink(path)])
        elif stat.S_ISDIR(before.st_mode):
            records.append([relative, "directory", before.st_mode & 0o111])
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child)
        elif stat.S_ISREG(before.st_mode):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                if _stamp(os.fstat(source.fileno())) != _stamp(before):
                    raise ValueError("runtime file changed before read")
                digest, size = hashlib.sha256(), 0
                for block in iter(lambda: source.read(65536), b""):
                    digest.update(block)
                    size += len(block)
                if size != before.st_size or _stamp(os.fstat(source.fileno())) != _stamp(before):
                    raise ValueError("runtime file changed during read")
            records.append([relative, "file", before.st_mode & 0o111, size, digest.hexdigest()])
            file_count += 1
            total_bytes += size
        else:
            raise ValueError("runtime contains a special file")

    visit(root)
    if any(_stamp(path.lstat()) != stamp for path, stamp in checked):
        raise ValueError("runtime tree changed during scan")
    payload = json.dumps(records, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return {"schema_version": 1, "kind": "directory_tree", "sha256": hashlib.sha256(payload).hexdigest(),
            "file_count": file_count, "entry_count": len(records), "byte_count": total_bytes}
