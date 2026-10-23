"""Render a semantic brief to a new MP4; does not approve or modify Jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from edit.hd.tools.semantic_state_pipeline import render_semantic_artifact


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("brief", "output", "node", "playwright", "browser", "ffmpeg", "ffprobe"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args(argv)
    try:
        if any(not Path(value).is_absolute() for value in vars(args).values()):
            raise ValueError("all paths must be absolute")
        output = Path(args.output)
        if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
            raise ValueError("output must be new and without symlinks")
        output.parent.resolve(strict=True)
        fd = os.open(args.brief, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("brief must be a regular file")
            data = source.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("brief exceeds 4 MiB")
        brief = json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
        with tempfile.TemporaryDirectory(prefix="semantic-render-", dir=output.parent) as temporary:
            stage = Path(temporary) / "render"
            artifact = render_semantic_artifact(brief=brief, output_dir=stage,
                node_executable=args.node, playwright_module=args.playwright,
                browser_executable=args.browser, ffmpeg_executable=args.ffmpeg, ffprobe_executable=args.ffprobe)
            candidate = stage / "candidate.mp4"
            if artifact["candidate_path"] != str(candidate) or candidate.is_symlink():
                raise ValueError("unexpected candidate path")
            digest = hashlib.sha256()
            fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                identity = os.fstat(source.fileno())
                if not stat.S_ISREG(identity.st_mode):
                    raise ValueError("candidate must be regular")
                for block in iter(lambda: source.read(65536), b""):
                    digest.update(block)
                if digest.hexdigest() != artifact["mp4_sha256"]:
                    raise ValueError("candidate changed before publication")
                os.link(candidate, output)
                installed = None
                try:
                    installed = output.lstat()
                    fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, "rb") as published:
                        actual = os.fstat(published.fileno())
                        if not stat.S_ISREG(actual.st_mode) or not os.path.samestat(identity, actual):
                            raise ValueError("candidate identity changed at publication")
                        digest = hashlib.sha256()
                        for block in iter(lambda: published.read(65536), b""):
                            digest.update(block)
                        if digest.hexdigest() != artifact["mp4_sha256"]:
                            raise ValueError("published media changed")
                except Exception:
                    if installed is not None and os.path.samestat(installed, output.lstat()):
                        output.unlink()
                    raise
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"semantic render failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
