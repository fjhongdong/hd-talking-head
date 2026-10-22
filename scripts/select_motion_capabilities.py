#!/usr/bin/env python3
"""Read our motion library, recall candidates, or check an existing offline plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("catalog", "search", "check"))
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--query")
    parser.add_argument("--use", choices=("aroll_overlay", "broll", "component", "design"))
    parser.add_argument("--include-history", action="store_true")
    parser.add_argument("--treatment", type=Path)
    parser.add_argument("--director-brief", type=Path)
    parser.add_argument("--job-dir", type=Path, help="read existing approved speech and referenced native briefs only")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    from edit.hd.tools import contract_artifacts, motion_capabilities as motion
    from edit.hd.tools.startup import assert_project_origin

    try:
        project = args.project_root.resolve(strict=True)
        assert_project_origin(project)
        if args.action == "catalog":
            catalog = motion.load_catalog(project)
            result = motion.catalog_summary(catalog) if args.summary_only else catalog
        elif args.action == "search":
            if not args.query:
                parser.error("search requires --query after the host has analyzed the full clause")
            result = motion.search_capabilities(project, args.query, use=args.use,
                                                include_history=args.include_history)
        else:
            if args.treatment is None or args.director_brief is None:
                parser.error("check requires --treatment and --director-brief; both are read-only")
            result = motion.check_offline_plan(project,
                contract_artifacts.read_json_artifact(args.director_brief),
                contract_artifacts.read_json_artifact(args.treatment), job_dir=args.job_dir)
    except (OSError, ValueError, KeyError, TypeError, contract_artifacts.ContractArtifactError) as error:
        parser.exit(1, f"Motion capability selection stopped: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
