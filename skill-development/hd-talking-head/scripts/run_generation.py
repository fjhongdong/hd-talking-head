#!/usr/bin/env python3
"""Expose selected host actions and collect their actual image/video results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--purpose", choices=["image", "video"], required=True)
    prepare.add_argument("--request-id", required=True)
    prepare.add_argument("--arguments-json", type=Path, required=True)
    prepare.add_argument("--input-files-json", type=Path)
    add = commands.add_parser("add")
    add.add_argument("--plan-json", type=Path, required=True)
    add.add_argument("--plan-sha256", required=True)
    add.add_argument("--user-confirmation", required=True)
    claim = commands.add_parser("next")
    claim.add_argument("--request-id", required=True)
    claim.add_argument("--account-limit", type=int)
    record = commands.add_parser("record")
    record.add_argument("--action-json", type=Path, required=True)
    record.add_argument("--response-json", type=Path, required=True)
    replace = commands.add_parser("replace-unsent-upload")
    replace.add_argument("--action-json", type=Path, required=True)
    replace.add_argument("--evidence-json", type=Path, required=True)
    edit = commands.add_parser("edit-completed-image")
    edit.add_argument("--plan-json", type=Path, required=True)
    edit.add_argument("--plan-sha256", required=True)
    edit.add_argument("--user-confirmation", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve()))
    from edit.hd.tools import generation_channels, generation_queue

    if args.command == "prepare":
        result = generation_channels.prepare_request(args.job, args.purpose, _read(args.arguments_json),
            request_id=args.request_id, input_files=_read(args.input_files_json) if args.input_files_json else [])
    elif args.command == "add":
        result = generation_queue.add(args.job, _read(args.plan_json), args.user_confirmation, args.plan_sha256)
    elif args.command == "next":
        result = generation_channels.next_action(args.job, args.request_id, account_limit=args.account_limit)
    elif args.command == "record":
        result = generation_channels.record_result(args.job, _read(args.action_json), _read(args.response_json))
    elif args.command == "replace-unsent-upload":
        result = generation_channels.replace_unsent_upload(args.job, _read(args.action_json), _read(args.evidence_json))
    else:
        result = generation_queue.edit_completed_image(args.job, _read(args.plan_json), args.user_confirmation, args.plan_sha256)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
