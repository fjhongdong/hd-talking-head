#!/usr/bin/env python3
"""Copy completed films and existing covers into the user's delivery directory."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager

from PIL import Image

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DELIVERY_ROOT = PACKAGE_ROOT.parent / '素材与作品'
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from edit.hd.tools import contract_artifacts as artifacts, delivery_approval, state

_FILES = {'delivery_file': '成片.mp4', 'cover_9x16_file': '封面_9x16.png',
          'cover_3x4_file': '封面_3x4.png'}


def _canonical(path: Path) -> Path:
    path = Path(path).expanduser().absolute()
    if path != path.resolve():
        raise ValueError(f'交付路径不能包含软链接或路径跳转：{path}')
    return path


def _record(path: Path) -> dict:
    path = _canonical(path)
    if not path.is_file():
        raise ValueError(f'交付文件缺失：{path}')
    return {'sha256': artifacts.sha256_file(path), 'bytes': path.stat().st_size}


def _registered(job, stage: str, relative: str) -> Path:
    records = [item for item in job.stages[stage]['artifacts'] if item['path'] == relative]
    if len(records) != 1:
        raise ValueError(f'缺少已登记的交付输入：{relative}')
    state._validate_record(job.job_dir, records[0])
    return _canonical(job.job_dir / relative)


def _title(job) -> tuple[str, str]:
    brief = _registered(job, 'cover', '04-cover/cover-brief.json')
    title = artifacts.read_json_artifact(brief).get('title')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('已登记的封面缺少视频标题')
    title = title.strip()
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', title).strip(' .')
    if not safe or safe in {'.', '..'}:
        raise ValueError('视频标题不能用作交付目录')
    return title, safe


def _png(path: Path, width: int, height: int) -> None:
    _record(path)
    with Image.open(path) as image:
        if image.format != 'PNG' or image.width * height != image.height * width:
            raise ValueError(f'封面必须是可读的 {width}:{height} PNG：{path}')
        image.verify()


def _cover_3x4(job, title: str, explicit: Path | None) -> Path:
    workspace = _canonical(job.root)
    if explicit is not None:
        path = Path(explicit)
        path = _canonical(path if path.is_absolute() else workspace / path)
        if not path.is_relative_to(workspace):
            raise ValueError('独立3:4封面必须位于本Job工作区内')
    else:
        candidates = []
        for metadata in sorted((workspace / 'punk-assets/punk-cover').glob('*/generation.json')):
            _canonical(metadata)
            data = artifacts.read_json_artifact(metadata)
            if (data.get('job_id') == job.job_id and data.get('title') == title
                    and data.get('aspect_ratio') == '3:4'
                    and data.get('independently_composed') is True):
                candidate = _canonical(metadata.parent / 'cover.png')
                if not candidate.is_relative_to(workspace):
                    raise ValueError('独立3:4封面必须位于本Job工作区内')
                candidates.append(candidate)
        if not candidates:
            raise ValueError('缺少独立3:4封面；请提供已有文件，不会自动裁切或生成')
        if len(candidates) != 1:
            raise ValueError('存在多个独立3:4封面，请用 --cover-3x4 明确指定')
        path = candidates[0]
    _png(path, 3, 4)
    return path


def _paths(directory: Path) -> dict:
    return {'delivery_directory': str(directory),
            **{key: str(directory / filename) for key, filename in _FILES.items()}}


def exported_paths(job) -> dict:
    """Read current export metadata without publishing or changing production state."""
    metadata = job.job_dir / 'manifests/delivery-export.json'
    if not metadata.exists() and not metadata.is_symlink():
        return {}
    _canonical(metadata)
    data = artifacts.read_json_artifact(metadata)
    if (data.get('schema_version') != 1 or data.get('job_id') != job.job_id
            or not isinstance(data.get('delivery_manifest_sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', data['delivery_manifest_sha256'])):
        raise ValueError('交付归档信息损坏')
    delivered = delivery_approval.validate_delivery_receipt(job)
    if data['delivery_manifest_sha256'] != delivered['delivery_manifest']['sha256']:
        return {}
    title, safe = _title(job)
    outputs = data.get('outputs')
    if (data.get('title') != title or not isinstance(outputs, dict)
            or set(outputs) != set(_FILES.values())
            or not isinstance(data.get('directory'), str)):
        raise ValueError('交付归档信息损坏')
    root = _canonical(_canonical(DELIVERY_ROOT) / safe)
    directory = _canonical(Path(data['directory']))
    if directory != root:
        legacy = root / ('版本-' + artifacts.sha256_json(outputs)[:12])
        if directory != legacy or not _matches(root, outputs):
            raise ValueError('旧版交付记录不能替换当前定稿')
        directory = root
    for filename, expected in outputs.items():
        if _record(directory / filename) != expected:
            raise ValueError(f'交付归档文件已损坏或被修改：{filename}')
    if outputs[_FILES['delivery_file']] != {key: delivered['delivery'][key] for key in ('sha256', 'bytes')}:
        raise ValueError('交付归档成片与当前正式成片不一致')
    cover = _registered(job, 'delivery', '12-delivery/cover/cover-9x16.png')
    if outputs[_FILES['cover_9x16_file']] != _record(cover):
        raise ValueError('交付归档9:16封面与当前正式封面不一致')
    _reject_symlinks(directory)
    if {item.name for item in directory.iterdir()} != set(outputs):
        return {}
    return _paths(directory)


def _matches(directory: Path, outputs: dict) -> bool:
    _canonical(directory)
    if not directory.is_dir():
        return False
    if {item.name for item in directory.iterdir()} != set(outputs):
        return False
    for filename, expected in outputs.items():
        path = directory / filename
        if not path.is_file() or path.is_symlink() or _record(path) != expected:
            return False
    return True


def _reject_symlinks(directory: Path) -> None:
    _canonical(directory)
    if not directory.is_dir():
        raise ValueError('标题对应的交付路径不是目录')
    for base, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            if (Path(base) / name).is_symlink():
                raise ValueError('交付目录不能包含软链接')


@contextmanager
def _title_lock(safe: str):
    history = _canonical(DELIVERY_ROOT.parent / 'video-jobs' / '交付历史')
    history.mkdir(parents=True, exist_ok=True)
    _canonical(history)
    locks = _canonical(history / '.locks')
    locks.mkdir(exist_ok=True)
    _canonical(locks)
    lock = _canonical(locks / (hashlib.sha256(safe.encode()).hexdigest() + '.lock'))
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield history
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def export_delivery(job, *, cover_3x4: Path | None = None) -> dict:
    """Publish the current three authoritative files and preserve the previous directory."""
    title, safe = _title(job)
    with _title_lock(safe) as history:
        # Even explicit inputs must not allow a previous Job to restore its obsolete bundle.
        existing = exported_paths(job)
        if existing and cover_3x4 is None:
            return existing
        film = delivery_approval.delivery_file(job)
        cover = _registered(job, 'delivery', '12-delivery/cover/cover-9x16.png')
        _png(cover, 9, 16)
        portrait = _cover_3x4(job, title, cover_3x4)
        sources = dict(zip(_FILES.values(), (film, cover, portrait)))
        outputs = {name: _record(source) for name, source in sources.items()}
        root = _canonical(DELIVERY_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        _canonical(root)
        directory = _canonical(root / safe)
        delivered = delivery_approval.validate_delivery_receipt(job)
        data = {'schema_version': 1, 'job_id': job.job_id, 'title': title,
                'delivery_manifest_sha256': delivered['delivery_manifest']['sha256'],
                'directory': str(directory), 'outputs': outputs}
        metadata = _canonical(job.job_dir / 'manifests/delivery-export.json')
        if directory.exists():
            _reject_symlinks(directory)
        if _matches(directory, outputs):
            if not metadata.exists() or artifacts.read_json_artifact(metadata) != data:
                artifacts.write_json_artifact(metadata, data)
            return _paths(directory)
        with tempfile.TemporaryDirectory(prefix='.delivery-export-', dir=history) as temporary:
            staged = Path(temporary) / 'bundle'
            staged.mkdir()
            for name, source in sources.items():
                shutil.copyfile(source, staged / name)
                if _record(staged / name) != outputs[name]:
                    raise ValueError('交付输入在复制过程中发生变化')
            archived = None
            if directory.exists():
                archive_parent = _canonical(history / safe)
                archive_parent.mkdir(exist_ok=True)
                _canonical(archive_parent)
                archived = _canonical(archive_parent / uuid.uuid4().hex)
            try:
                if archived is not None:
                    delivery_approval._publish_once(directory, archived)
                delivery_approval._publish_once(staged, directory)
                artifacts.write_json_artifact(metadata, data)
            except BaseException:
                if not staged.exists() and directory.exists():
                    delivery_approval._publish_once(directory, staged)
                if archived is not None and archived.exists():
                    delivery_approval._publish_once(archived, directory)
                raise
        return _paths(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--cover-3x4', type=Path)
    args = parser.parse_args(argv)
    try:
        result = export_delivery(state.load_job(args.job), cover_3x4=args.cover_3x4)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
