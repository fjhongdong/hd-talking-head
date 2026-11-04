"""Reuse successful native facts only within a verified, in-process operation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import stat
from time import perf_counter


def _metric(name, value=1):
    from edit.hd.tools.startup import current_operation
    operation = current_operation()
    if operation is not None:
        metrics = operation.native_fact_metrics
        metrics[name] = metrics.get(name, 0) + value


def input_hashes(count, check):
    started = perf_counter()
    try:
        return check()
    finally:
        _metric('input_hashes', count)
        _metric('input_hash_seconds', perf_counter() - started)


def input_probe(check):
    started = perf_counter()
    try:
        return check()
    finally:
        _metric('input_probes')
        _metric('input_probe_seconds', perf_counter() - started)


def _validator_identity(project, validate):
    code = getattr(validate, '__code__', None)
    if code is None or not Path(code.co_filename).resolve().is_relative_to(project):
        raise ValueError('Native cache requires a package-owned validator')
    return (str(Path(code.co_filename).resolve()), validate.__qualname__, code.co_firstlineno)


def _input_paths(root, target):
    return tuple(sorted({target, *(parent for parent in target.parents
                                   if parent.is_relative_to(root) and parent != root)}))


def input_file_digest(root, target, *, cache=None):
    """Reuse an already checked input digest inside a caller's verified batch."""
    supplied_root, target = Path(root).absolute(), Path(target).absolute()
    root = supplied_root.resolve(strict=True)
    if target.is_relative_to(supplied_root):
        target = root / target.relative_to(supplied_root)
    def digest():
        value = hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                value.update(block)
        return value.hexdigest()
    if cache is None:
        return input_hashes(1, digest)
    try:
        if not target.resolve(strict=True).is_relative_to(root):
            raise ValueError('Native input digest escapes its Job')
        files = _input_paths(root, target)
        before = _snapshot(root, files, None)
        key = ('native-input-file', str(root), str(target))
        cached = cache.get(key)
        if cached is not None:
            if cached[0] == before:
                _metric('input_hash_fact_hits')
                return cached[1]
            del cache[key]
            _metric('input_fact_invalidations')
    except (OSError, ValueError):
        return input_hashes(1, digest)
    value = input_hashes(1, digest)
    try:
        if _snapshot(root, files, None) == before:
            cache[key] = (before, value)
    except (OSError, ValueError):
        pass
    return value


def _source_snapshot(paths):
    started = perf_counter()
    try:
        return tuple((str(path), item.st_dev, item.st_ino, item.st_mode,
                      item.st_size, item.st_mtime_ns, item.st_ctime_ns)
                     for path in paths for item in (path.lstat(),))
    finally:
        _metric('source_metadata_paths', len(paths))
        _metric('source_metadata_seconds', perf_counter() - started)


def source_unchanged(project, identity, directory, verify, *, records=()):
    """Reuse one selected source's full check, including restored source trees."""
    from edit.hd.tools.startup import _operation_cache
    project, directory = Path(project).resolve(strict=True), Path(directory)
    cache = _operation_cache(project)
    key = ('native-source-facts', str(project), identity)
    cached = cache.get(key) if cache is not None else None
    if cached is not None:
        paths, before = cached
        try:
            if _source_snapshot(paths) == before:
                _metric('source_fact_hits')
                return directory
        except OSError:
            pass
        del cache[key]
        for result_key in tuple(cache):
            if result_key[0] == 'native-result-facts' and result_key[3] == identity:
                del cache[result_key]
        _metric('source_fact_invalidations')
    # Enumerate only on the first check or an actual invalidation. Every directory
    # is retained so new/deleted files and symlink replacements cannot hide.
    inventory = tuple(directory.rglob('*'))
    paths = {directory, *inventory, *(Path(path) for path in records)}
    for path in tuple(paths):
        paths.update(parent for parent in path.parents if parent.is_relative_to(project))
    paths = tuple(sorted(paths))
    before = _source_snapshot(paths) if cache is not None else None
    verify(inventory)
    if cache is not None:
        if _source_snapshot(paths) != before:
            raise ValueError('Native source changed during verification')
        cache[key] = (paths, before)
    return directory


def inspect_inputs(project, job_dir, brief, validate):
    """Share only file and audio facts; parent Job/route/approval checks stay live."""
    from edit.hd.tools.startup import _operation_cache
    cache = _operation_cache(project)
    if cache is None:
        return validate(job_dir, brief)
    try:
        root, package = Path(job_dir).resolve(strict=True), Path(project).resolve(strict=True)
        inputs = {name: brief[name] for name in ('speech', 'materials', 'composition')}
        tool = shutil.which('ffprobe')
        if not tool:
            raise ValueError('Native input cache requires FFprobe')
        key = ('native-input-facts', str(package), _validator_identity(package, validate),
               str(root), hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(), tool)
        files = {_relative(root, item['job_path']) for item in [brief['speech'], *brief['materials']]}
        for path in tuple(files):
            files.update(parent for parent in path.parents if parent.is_relative_to(root) and parent != root)
        files = tuple(sorted(files))
        before = _snapshot(root, files, tool)
        cached = cache.get(key)
        if cached is not None:
            if cached == before:
                _metric('input_fact_hits')
                return None
            del cache[key]
            _metric('input_fact_invalidations')
    except (OSError, ValueError, TypeError, KeyError):
        return validate(job_dir, brief)
    checked = validate(job_dir, brief)
    try:
        if _snapshot(root, files, tool) == before:
            cache[key] = before
            snapshots = {record[0]: record for record in before}
            for record in [brief['speech'], *brief['materials']]:
                target = _relative(root, record['job_path'])
                cache[('native-input-file', str(root), str(target))] = (
                    (before[0], *(snapshots[str(path)] for path in _input_paths(root, target))), record['sha256'])
    except (OSError, ValueError):
        pass
    return checked


def _relative(root, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
        raise ValueError('Native cache dependency is not Job-relative')
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError('Native cache dependency escapes its Job')
    return target


def _dependencies(root, brief, result):
    files, projects = set(), set()

    def collect(value):
        if isinstance(value, dict):
            if 'job_path' in value:
                files.add(_relative(root, value['job_path']))
            for name in ('project_directory', 'project_src'):
                if name in value:
                    projects.add(_relative(root, value[name]))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(brief); collect(result)
    if 'result_record_path' in brief:
        files.add(_relative(root, brief['result_record_path']))
    for descriptor in ([result['render_call']] if 'render_call' in result else result.get('calls', [])):
        collect(json.loads(_relative(root, descriptor['job_path']).read_bytes()))
    if not projects:
        raise ValueError('Native cache requires the actual authored project directory')
    # Include directories and empty directories: additions/removals anywhere in
    # authored source or render outputs must invalidate, not just recorded files.
    def tree(directory):
        files.add(directory)
        for item in directory.iterdir():
            files.add(item)
            if item.name in {'node_modules', '.git'}:
                continue  # Installed modules are not consumed by result inspection.
            if item.is_symlink():
                raise ValueError('Native source symlinks are not reusable')
            if item.is_dir():
                tree(item)
    for project in projects:
        tree(project)
    # Every path component is checked, so swapping a directory for a link cannot
    # hide changed bytes. Job root metadata excludes mtime: Job revision is not a fact.
    for file in tuple(files):
        if not file.is_relative_to(root):
            raise ValueError('Native cache dependency escapes its Job')
        files.update(parent for parent in file.parents if parent.is_relative_to(root) and parent != root)
    return tuple(sorted(files))


def _snapshot(root, files, tool):
    records = []
    anchor = root.stat()
    records.append((str(root), anchor.st_dev, anchor.st_ino, anchor.st_mode))
    for file in files:
        item = file.lstat()
        if stat.S_ISLNK(item.st_mode) and file.name not in {'node_modules', '.git'}:
            raise ValueError('Native dependency symlinks are not reusable')
        records.append((str(file), item.st_dev, item.st_ino, item.st_mode,
                        item.st_size, item.st_mtime_ns, item.st_ctime_ns))
    # FFprobe often has a symlink launcher. Bind both it and its resolved binary,
    # including link parents, without hashing the executable at every lookup.
    if tool is not None:
        executable = Path(tool)
        target = executable.resolve(strict=True)
        for file in sorted({executable, target, *executable.parents, *target.parents}):
            item = file.lstat()
            records.append((str(file), item.st_dev, item.st_ino, item.st_mode,
                            item.st_size, item.st_mtime_ns, item.st_ctime_ns))
    return tuple(records)


def inspect_unchanged(project, job_dir, payload, data, brief, validate, *, source_identity=None):
    """Memoize immutable facts; callers still check current approval on every use.

    A verified package snapshot binds validator/native source identity. Metadata
    binds every consumed Job file, authored tree, output and current probe tool.
    Unknown identity, changed dependencies and failed checks never grant reuse.
    """
    from edit.hd.tools.startup import _operation_cache
    cache = _operation_cache(project)
    if cache is None:
        return validate(job_dir, payload, data)
    try:
        root = Path(job_dir).resolve(strict=True)
        package = Path(project).resolve(strict=True)
        # run_stage imports fresh adapter instances. Function-object identity
        # would miss across them; the verified source path binds stable code.
        validator = _validator_identity(package, validate)
        result = json.loads(data)
        renderer = result.get('renderer_version') or result.get('upstream_commit')
        if not renderer or not brief.get('job_id'):
            raise ValueError('Native cache requires Job and renderer identity')
        tool = shutil.which('ffprobe')
        if not tool:
            raise ValueError('Native cache requires the current probe executable')
        key = ('native-result-facts', str(package), validator, source_identity,
               str(root), brief['job_id'], hashlib.sha256(payload).hexdigest(),
               hashlib.sha256(data).hexdigest(), renderer, tool)
        cached = cache.get(key)
        if cached is not None:
            files, before, checked = cached
            if _snapshot(root, files, tool) == before:
                _metric('result_fact_hits')
                return deepcopy(checked)
            del cache[key]
            _metric('result_fact_invalidations')
        files = _dependencies(root, brief, result)
        before = _snapshot(root, files, tool)
    except (OSError, ValueError, TypeError, KeyError):
        # Cache eligibility is narrower than the underlying native protocol.
        return validate(job_dir, payload, data)
    checked = validate(job_dir, payload, data)
    try:
        if _snapshot(root, files, tool) == before:
            cache[key] = (files, before, deepcopy(checked))
    except (OSError, ValueError):
        pass
    return checked
