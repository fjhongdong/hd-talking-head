#!/usr/bin/env python3
"""Plan cross-Skill B-roll assignments without rendering or provider calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("discover", "assign", "check"))
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--treatment", type=Path)
    parser.add_argument("--director-brief", type=Path)
    args = parser.parse_args()
    from edit.hd.tools import broll_skill_selection as selection, contract_artifacts

    try:
        project = args.project_root.resolve(strict=True)
        from edit.hd.tools.startup import assert_project_origin
        assert_project_origin(project)
        if args.action == "discover":
            result = selection.discover_candidates(project)
        else:
            if args.treatment is None:
                parser.error("assign/check require --treatment")
            treatment = contract_artifacts.read_json_artifact(args.treatment)
            if args.action == "assign":
                treatment["skill_selection"] = selection.assign_skills(
                    project, treatment.get("skill_selection", {}),
                )
                contract_artifacts.write_json_artifact(args.treatment, treatment)
                result = treatment["skill_selection"]
            else:
                if args.director_brief is None:
                    parser.error("check requires --director-brief")
                result = selection.validate_selection(
                    project, contract_artifacts.read_json_artifact(args.director_brief),
                    treatment,
                )
    except (OSError, ValueError, KeyError, TypeError, contract_artifacts.ContractArtifactError) as error:
        parser.exit(1, f"B-roll selection stopped: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
