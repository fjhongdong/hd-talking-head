#!/usr/bin/env python3
"""Record this Job's explicit environment approval after a successful preflight."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--user-confirmation", required=True)
    args = parser.parse_args()
    try:
        context = json.loads(args.job_context.read_text(encoding="utf-8"))
        project = Path(context["project_root"]).resolve()
        sys.path.insert(0, str(project))
        from edit.hd.tools import state, startup
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        print("setup confirmation stopped: invalid context or unavailable runtime", file=sys.stderr)
        return 2
    try:
        startup.assert_project_origin(project)
        job = state.load_job(Path(context["job_dir"]))
        if args.job_context.resolve() != job.root / "job-context.json":
            raise state.WorkflowError("startup context is not the current Job context")
        path = startup.confirm_setup(job, job.job_dir / "manifests/provider-config.json",
                                     user_confirmation=args.user_confirmation)
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        print("setup confirmation stopped: invalid context or unavailable runtime", file=sys.stderr)
        return 2
    except state.WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": "confirmed", "job_id": job.job_id, "approval_path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
