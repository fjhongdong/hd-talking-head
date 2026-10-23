"""Job-independent CLI for the shared relation renderer; not an approval tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from collections.abc import Sequence

# Support a pinned script entrypoint as well as `python -m` invocation.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from edit.hd.tools.relation_motion_maintenance_render import (
    _new_output_path,
    render_relation_brief_artifact,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("brief", "output", "node", "playwright", "browser", "ffmpeg", "ffprobe"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        for name, value in vars(args).items():
            if not Path(value).is_absolute():
                raise ValueError(f"{name} must be an absolute path")
        output = _new_output_path(args.output)
        output.parent.resolve(strict=True)
        source = Path(args.brief)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("brief must be a regular JSON file of at most 4 MiB")
        brief = json.loads(source.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="relation-render-", dir=output.parent) as temporary:
            artifact = render_relation_brief_artifact(
                brief=brief, output_dir=Path(temporary) / "render", node_executable=args.node,
                playwright_module=args.playwright, browser_executable=args.browser,
                ffmpeg_executable=args.ffmpeg, ffprobe_executable=args.ffprobe,
            )
            candidate = Path(artifact["candidate_path"])
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != artifact["mp4_sha256"]:
                raise ValueError("candidate changed before publication")
            # Same-filesystem link publishes the exact tested bytes and refuses overwrite.
            os.link(candidate, output)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"relation render failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
