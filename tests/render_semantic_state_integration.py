"""Render and qualify the five SemanticState families without registering them.

The ``seed`` phase creates one reviewable sample per family.  The ``qualify``
phase only accepts those samples after an external review record has bound the
exact sample and frozen renderer.  It then executes two distinct briefs per
family through the production component executor and exports read-only
published-execution bindings.  Neither phase grants user approval or edits the
main template registry.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "tests"))

from render_local_canonical_integration import (
    _frame_proofs,
    _proof,
    _sha,
    _verification_id,
    _write_json,
)
from semantic_state_adapter import (
    ENTRY,
    TEMPLATES,
    _read_snapshot,
    create_adapter,
    create_artifact_probe,
    create_binding,
)


FAMILIES = ("replacement", "threshold", "delay", "hierarchy", "feedback")
PATTERNS = {
    "replacement": ("establish", "replace", "compare"),
    "threshold": ("establish", "cross_threshold", "raise_threshold"),
    "delay": ("establish", "wait", "realize"),
    "hierarchy": ("establish", "reveal_layers", "resolve"),
    "feedback": ("establish", "produce", "feedback_return"),
}
CONTENT_SEMANTIC_TYPES = {
    "replacement": "contrast",
    "threshold": "contrast",
    "delay": "process",
    "hierarchy": "process",
    "feedback": "process",
}


def _subject(identity, label, initial, final, preserve=False):
    return {
        "id": identity,
        "label": label,
        "initial_state": initial,
        "final_state": final,
        "preserve": preserve,
    }


def make_brief(family: str, variant: int) -> dict:
    """Return one semantically distinct, renderer-valid qualification brief."""
    if family not in FAMILIES or variant not in (1, 2):
        raise ValueError("qualification requires one known family and variant 1 or 2")
    fixtures = {
        "replacement": (
            ("技术更替", "动力设备从蒸汽机更替为电动机，工厂布局保持原样", [
                _subject("change", "动力设备", "蒸汽机", "电动机"),
                _subject("context", "工厂布局", "保持原样", "保持原样", True),
            ], {"change_id": "change", "context_ids": ["context"]}),
            ("工具更替", "录入工具从人工录入更替为 AI 助手，厂房布局、业务规则和协作交接保持不变", [
                _subject("change", "录入工具", "人工录入", "AI 助手"),
                _subject("context-layout", "厂房布局", "保持不变", "保持不变", True),
                _subject("context-rules", "业务规则", "保持不变", "保持不变", True),
                _subject("context-handoff", "协作交接", "保持不变", "保持不变", True),
            ], {
                "change_id": "change",
                "context_ids": ["context-layout", "context-rules", "context-handoff"],
            }),
        ),
        "threshold": (
            ("标准迁移", "个人能力越过旧评价标准后，评价标准继续上移", [
                _subject("ability", "个人能力", "尚未达标", "已经达标"),
                _subject("standard", "评价标准", "旧标准", "新标准"),
            ], {"capability_id": "ability", "threshold_id": "standard"}),
            ("竞争门槛", "团队效率跨过当前行业门槛，行业门槛随即提高", [
                _subject("ability", "团队效率", "低于门槛", "越过门槛"),
                _subject("standard", "行业门槛", "当前要求", "更高要求"),
            ], {"capability_id": "ability", "threshold_id": "standard"}),
        ),
        "delay": (
            ("释放延迟", "电动机诞生后，生产力经过长期改造才释放", [
                _subject("trigger", "电动机", "已经诞生", "已经诞生", True),
                _subject("outcome", "生产力", "尚未释放", "逐步爆发"),
            ], {"trigger_id": "trigger", "outcome_id": "outcome"}),
            ("组织滞后", "AI 工具上线后，团队能力经过流程重构才提升", [
                _subject("trigger", "AI 工具", "已经上线", "已经上线", True),
                _subject("outcome", "团队能力", "尚未提升", "开始提升"),
            ], {"trigger_id": "trigger", "outcome_id": "outcome"}),
        ),
        "hierarchy": (
            ("能力分层", "AI 应用依次展开为工具层和流程层两层能力", [
                _subject("layer-1", "工具层", "未展开", "会使用工具"),
                _subject("layer-2", "流程层", "未展开", "会重构流程"),
            ], {"layer_ids": ["layer-1", "layer-2"]}),
            ("价值分层", "企业价值依次展开为效率层、质量层、创新层和组织层", [
                _subject("layer-1", "效率层", "未展开", "节省时间"),
                _subject("layer-2", "质量层", "未展开", "稳定产出"),
                _subject("layer-3", "创新层", "未展开", "创造新价值"),
                _subject("layer-4", "组织层", "未展开", "形成新协作"),
            ], {"layer_ids": ["layer-1", "layer-2", "layer-3", "layer-4"]}),
        ),
        "feedback": (
            ("实践反馈", "决策进入实践，反馈返回并修正下一次判断", [
                _subject("source", "决策", "初始判断", "修正判断"),
                _subject("result", "实践", "尚无反馈", "产生反馈"),
            ], {"source_id": "source", "result_id": "result"}),
            ("用户反馈", "方案交给用户，真实反馈返回并改进方案", [
                _subject("source", "方案", "第一版", "改进版"),
                _subject("result", "用户", "尚未验证", "反馈结果"),
            ], {"source_id": "source", "result_id": "result"}),
        ),
    }
    title, source_text, subjects, roles = fixtures[family][variant - 1]
    targets = {
        "threshold": [["ability", "standard"], ["ability"], ["standard"]],
        "delay": [["trigger", "outcome"], ["trigger", "outcome"], ["outcome"]],
        "feedback": [["source"], ["result"], ["source"]],
    }.get(family)
    if family == "replacement":
        all_subjects = [roles["change_id"], *roles["context_ids"]]
        targets = [all_subjects, [roles["change_id"]], all_subjects]
    elif family == "hierarchy":
        layers = roles["layer_ids"]
        targets = [[layers[0]], layers[1:], layers]
    actions = [
        {
            "id": f"phase-{index + 1}",
            "operation": operation,
            "subject_ids": targets[index],
            "start_frame": index * 20,
            "end_frame": (index + 1) * 20,
            "depends_on": [] if index == 0 else [f"phase-{index}"],
        }
        for index, operation in enumerate(PATTERNS[family])
    ]
    return {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 120},
        "title": title,
        "roles": roles,
        "motion": {
            "version": 1,
            "content_item_id": f"qualification-{family}-{variant}",
            "source_text": source_text,
            "family": family,
            "meaningful_change": "画面按语义关系逐步改变，并在阅读窗口保持稳定",
            "subjects": subjects,
            "actions": actions,
            "duration_frames": 120,
            "read_window": {"start_frame": 60, "end_frame": 108, "minimum_frames": 24},
            "exit_window": {"start_frame": 108, "end_frame": 120},
        },
    }


def action_evidence_frames(brief: dict) -> list[tuple[str, int]]:
    return [
        (action["operation"], action["end_frame"] - 1)
        for action in brief["motion"]["actions"]
    ]


def _qualified_output(value: Path) -> Path:
    output = value.resolve()
    relative = output.relative_to(SKILL.resolve())
    if len(relative.parts) < 3 or relative.parts[:2] != ("assets", "verified-templates"):
        raise ValueError("qualification output must be inside Skill assets/verified-templates")
    return output


@contextmanager
def _owned_output(value: Path):
    output = _qualified_output(value)
    output.mkdir(parents=True, exist_ok=False)
    marker = output / ".owned-incomplete"
    token = hashlib.sha256(os.urandom(32)).hexdigest()
    marker.write_text(token, encoding="ascii")
    try:
        yield output
        if marker.read_text(encoding="ascii") != token:
            raise ValueError("qualification ownership marker changed")
        marker.unlink()
    except BaseException:
        try:
            if marker.read_text(encoding="ascii") == token:
                shutil.rmtree(output)
        except (OSError, UnicodeError):
            pass
        raise


def _version(command: list[str]) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=15, check=False,
    )
    value = (result.stdout or result.stderr).splitlines()
    if result.returncode or not value or not value[0].strip():
        raise ValueError("runtime version command failed")
    return value[0].strip()[:128]


def build_runtime_contracts(args) -> tuple[dict, dict[str, Path]]:
    from edit.hd.tools.runtime_contracts import discover_macho_libraries, tree_identity

    paths = {
        "node": args.node.resolve(strict=True),
        "playwright": args.playwright.resolve(strict=True),
        "browser": args.browser.resolve(strict=True),
        "ffmpeg": args.ffmpeg.resolve(strict=True),
        "ffprobe": args.ffprobe.resolve(strict=True),
    }
    versions = {
        "node": _version([str(paths["node"]), "--version"]),
        "ffmpeg": _version([str(paths["ffmpeg"]), "-version"]),
        "ffprobe": _version([str(paths["ffprobe"]), "-version"]),
        "browser": _version([str(paths["browser"]), "--version"]),
    }
    package = paths["playwright"].parent / "package.json"
    versions["playwright"] = "playwright " + str(json.loads(package.read_text())["version"])
    contracts = {}
    for name in ("node", "ffmpeg", "ffprobe"):
        contracts[name] = {
            "kind": "file_snapshot",
            "path": str(paths[name]),
            "sha256": _sha(paths[name]),
            "version": versions[name],
            "library_discovery": "mach_o_static_v1",
            "libraries": discover_macho_libraries(paths[name]),
        }
    directory_roots = {
        "playwright": [paths["playwright"].parent, paths["playwright"].parent.parent / "playwright-core"],
        "browser": [paths["browser"].parents[2]],
    }
    for name, roots in directory_roots.items():
        contracts[name] = {
            "kind": "directory_tree",
            "path": str(paths[name]),
            "version": versions[name],
            "roots": [
                {"path": str(root.resolve(strict=True)), "sha256": tree_identity(root.resolve(strict=True))["sha256"]}
                for root in roots
            ],
        }
    return contracts, paths


def _render_seed_bundle(brief: Path, output: Path, contracts: dict,
                        tools: dict[str, Path]) -> None:
    command = [
        sys.executable,
        str(SKILL / ENTRY),
        "--runtime-contracts",
        json.dumps(contracts, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    ]
    for name in ("node", "playwright", "browser", "ffmpeg", "ffprobe"):
        command.extend(["--" + name, str(tools[name])])
    with brief.open("rb") as incoming, output.open("xb+") as outgoing:
        command.extend([
            "--brief", f"/dev/fd/{incoming.fileno()}",
            "--output", f"/dev/fd/{outgoing.fileno()}",
        ])
        process = subprocess.Popen(
            command,
            pass_fds=(incoming.fileno(), outgoing.fileno()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=300)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, 9)
            process.communicate(timeout=5)
            raise ValueError("SemanticState seed render timed out") from exc
    if process.returncode or stdout:
        detail = stderr[-4096:].decode("utf-8", errors="replace")
        raise ValueError("SemanticState seed render failed: " + detail)


def create_synthetic_job(folder: Path, source_video: Path, brief: dict):
    from edit.hd.tools import content_analysis, state

    folder.mkdir(parents=True, exist_ok=False)
    source_text = brief["motion"]["source_text"]
    script = folder / "synthetic-script.md"
    script.write_text(source_text, encoding="utf-8")
    local_source = folder / "synthetic-source.mp4"
    shutil.copyfile(source_video, local_source)
    job = state.create_job(folder, local_source, script, profile="full-v2")
    marker = {"synthetic_fixture": True, "human_approval_claimed": False}
    _write_json(job.job_dir / "SYNTHETIC-QUALIFICATION.json", marker)
    inspect = job.job_dir / "01-inspect/report.json"
    _write_json(inspect, marker)
    state.mark_ready(job, "inspect", [inspect])
    state.approve(job, "inspect")
    content_analysis.prepare_content_analysis(job, {
        "thesis": source_text,
        "hook": brief["title"],
        "sections": [{"id": "section", "title": brief["title"], "source_span": [0, len(source_text)]}],
        "items": [{
            "id": brief["motion"]["content_item_id"],
            "source_text": source_text,
            "source_span": [0, len(source_text)],
            "priority": "high",
            "keywords": [subject["label"] for subject in brief["motion"]["subjects"]],
            "semantic_type": CONTENT_SEMANTIC_TYPES[brief["motion"]["family"]],
            "evidence_status": "supported",
            "broll_priority": "high",
        }],
        "claims": [],
    })
    state.approve(job, "content_analysis")
    return job


def seed(args) -> None:
    contracts, tools = build_runtime_contracts(args)
    with _owned_output(args.output) as output:
        items = []
        for family in FAMILIES:
            folder = output / family
            folder.mkdir()
            brief = make_brief(family, 1)
            _write_json(folder / "brief.json", brief)
            print(f"Rendering SemanticState seed {family} (one worker)", flush=True)
            sample = folder / "sample.mp4"
            _render_seed_bundle(folder / "brief.json", sample, contracts, tools)
            frames = _frame_proofs(
                tools["ffmpeg"], sample, folder / "frames",
                {"entry": 10, "stable": 72, "exit": 119},
            )
            actions = _frame_proofs(
                tools["ffmpeg"], sample, folder / "action-frames",
                dict(action_evidence_frames(brief)),
            )
            items.append({
                "family": family,
                "template_id": TEMPLATES[family],
                "brief": _proof(folder / "brief.json"),
                "sample": _proof(sample),
                "frame_evidence": frames,
                "action_frames": actions,
            })
        _write_json(output / "pending-review.json", {
            "status": "pending_visual_review",
            "human_approval_claimed": False,
            "source": _proof(SKILL / ENTRY),
            "families": items,
        })


REVIEW_FIELDS = {
    "schema_version", "status", "reviewer_type", "reviewer", "reviewed_at",
    "approval_reference", "family", "template_id", "seed_manifest_sha256",
    "brief_sha256", "sample_sha256", "source_sha256", "visual_qa",
    "action_sequence_qa",
}
REVIEW_MAX_BYTES = 64 * 1024


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("seed manifest contains duplicate keys")
        result[key] = value
    return result


def load_review(path: Path) -> object:
    """Read one bounded, immutable review snapshot with strict JSON rules."""
    data = _read_snapshot(
        path, "seed review", executable=False, maximum=REVIEW_MAX_BYTES,
    )
    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_json,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError(
                "seed review contains a non-finite number"
            )),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("seed review is unreadable") from exc


def _validated_seed_frames(root: Path, family: str, value: object, *,
                           directory: str, roles: tuple[str, ...]) -> list[dict]:
    if type(value) is not list or len(value) != len(roles):
        raise ValueError("seed frame evidence fields are invalid")
    result = []
    previous = -1.0
    for record, role in zip(value, roles):
        if (type(record) is not dict
                or set(record) != {"role", "timestamp_sec", "path", "sha256"}
                or record["role"] != role
                or type(record["timestamp_sec"]) not in (int, float)
                or not math.isfinite(record["timestamp_sec"])
                or not previous < record["timestamp_sec"] < 5.01
                or type(record["sha256"]) is not str
                or len(record["sha256"]) != 64):
            raise ValueError("seed frame evidence fields are invalid")
        path = root / family / directory / f"{role}.png"
        expected_path = path.relative_to(SKILL).as_posix()
        if record["path"] != expected_path:
            raise ValueError("seed frame evidence path is invalid")
        payload = _read_snapshot(
            path, "seed frame evidence", executable=False, maximum=16 * 1024 * 1024,
        )
        if (not payload.startswith(b"\x89PNG\r\n\x1a\n")
                or hashlib.sha256(payload).hexdigest() != record["sha256"]):
            raise ValueError("seed frame evidence differs from current bytes")
        result.append(json.loads(json.dumps(record)))
        previous = float(record["timestamp_sec"])
    return result


def load_seed_lineage(seed_root: Path) -> dict:
    """Bind one manifest snapshot to current source, brief and sample bytes."""
    root = seed_root.resolve(strict=True)
    _qualified_output(root)
    manifest_path = root / "pending-review.json"
    data = _read_snapshot(
        manifest_path, "seed manifest", executable=False, maximum=1024 * 1024,
    )
    try:
        manifest = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_json,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("seed manifest is unreadable") from exc
    if (type(manifest) is not dict
            or set(manifest) != {"status", "human_approval_claimed", "source", "families"}
            or manifest["status"] != "pending_visual_review"
            or manifest["human_approval_claimed"] is not False
            or type(manifest["source"]) is not dict
            or set(manifest["source"]) != {"path", "sha256"}
            or manifest["source"]["path"] != ENTRY
            or type(manifest["families"]) is not list
            or len(manifest["families"]) != len(FAMILIES)):
        raise ValueError("seed manifest fields are invalid")
    source_bytes = _read_snapshot(
        SKILL / ENTRY, "SemanticState source", executable=False, maximum=4 * 1024 * 1024,
    )
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if manifest["source"]["sha256"] != source_sha:
        raise ValueError("seed manifest source differs from the current renderer")
    items = {}
    fields = {
        "family", "template_id", "brief", "sample", "frame_evidence", "action_frames",
    }
    for item in manifest["families"]:
        if type(item) is not dict or set(item) != fields:
            raise ValueError("seed manifest family fields are invalid")
        family = item["family"]
        if (family not in FAMILIES or family in items
                or item["template_id"] != TEMPLATES[family]):
            raise ValueError("seed manifest family identity is invalid")
        expected = {
            "brief": root / family / "brief.json",
            "sample": root / family / "sample.mp4",
        }
        proofs = {}
        for key, path in expected.items():
            proof = item[key]
            if (type(proof) is not dict or set(proof) != {"path", "sha256"}
                    or proof["path"] != path.relative_to(SKILL).as_posix()
                    or type(proof["sha256"]) is not str or len(proof["sha256"]) != 64):
                raise ValueError("seed manifest proof is invalid")
            maximum = 4 * 1024 * 1024 if key == "brief" else 64 * 1024 * 1024
            payload = _read_snapshot(path, "seed " + key, executable=False, maximum=maximum)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != proof["sha256"]:
                raise ValueError("seed manifest proof differs from current bytes")
            proofs[key] = {"path": path, "bytes": payload, "sha256": digest}
        try:
            brief = json.loads(
                proofs["brief"]["bytes"].decode("utf-8"), object_pairs_hook=_unique_json,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("seed brief is unreadable") from exc
        if (type(brief) is not dict or type(brief.get("motion")) is not dict
                or brief["motion"].get("family") != family):
            raise ValueError("seed brief family differs from manifest")
        proofs["frame_evidence"] = _validated_seed_frames(
            root, family, item["frame_evidence"], directory="frames",
            roles=("entry", "stable", "exit"),
        )
        proofs["action_frames"] = _validated_seed_frames(
            root, family, item["action_frames"], directory="action-frames",
            roles=PATTERNS[family],
        )
        items[family] = proofs
    if set(items) != set(FAMILIES):
        raise ValueError("seed manifest does not cover all families")
    return {
        "manifest_path": manifest_path,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "source_sha256": source_sha,
        "source": {"path": SKILL / ENTRY, "bytes": source_bytes, "sha256": source_sha},
        "families": items,
    }


def assert_reviewed_source(lineage: dict) -> None:
    """Reject renderer changes after the seed manifest was reviewed."""
    current = _read_snapshot(
        SKILL / ENTRY, "SemanticState source", executable=False,
        maximum=4 * 1024 * 1024,
    )
    if (hashlib.sha256(current).hexdigest() != lineage["source_sha256"]
            or current != lineage["source"]["bytes"]):
        raise ValueError("SemanticState renderer changed after review")


def validate_review(value: object, *, family: str, seed_manifest_sha256: str,
                    brief_sha256: str, sample_sha256: str,
                    source_sha256: str) -> dict:
    if type(value) is not dict or set(value) != REVIEW_FIELDS:
        raise ValueError("seed review fields are invalid")
    if (value["schema_version"] != 1 or value["status"] != "approved"
            or value["reviewer_type"] != "human"
            or value["family"] != family or value["template_id"] != TEMPLATES[family]
            or value["seed_manifest_sha256"] != seed_manifest_sha256
            or value["brief_sha256"] != brief_sha256
            or value["sample_sha256"] != sample_sha256
            or value["source_sha256"] != source_sha256):
        raise ValueError("seed review identity is invalid")
    for key in ("reviewer", "approval_reference"):
        if type(value[key]) is not str or not value[key].strip() or len(value[key]) > 256:
            raise ValueError("seed review human identity is invalid")
    try:
        reviewed = datetime.fromisoformat(value["reviewed_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError("seed review time is invalid") from exc
    if reviewed.tzinfo is None or reviewed.utcoffset() is None:
        raise ValueError("seed review time must include a timezone")
    for key in ("visual_qa", "action_sequence_qa"):
        if type(value[key]) is not dict or value[key].get("status") != "approved":
            raise ValueError("seed review QA is not approved")
    return json.loads(json.dumps(value))


def _candidate(family: str, sample: Path, review: dict, *, source_sha256: str,
               frame_evidence: list[dict], action_frames: list[dict]) -> dict:
    reviewed_at = review["reviewed_at"]
    reviewer = review["reviewer"]
    record = {
        "template_origin": "verified_local_canonical",
        "template_id": TEMPLATES[family],
        "template_version": "1.0.0",
        "adaptation_level": "content_reflow",
        "upstream": {"project": "hd-talking-head-semantic-state", "repository": ".", "commit": "native-v1"},
        "source_entrypoint": ENTRY,
        "source_sha256": source_sha256,
        "source_files": [
            {"path": ENTRY, "sha256": source_sha256},
            _proof(SKILL / "scripts/semantic_state_adapter.py"),
        ],
        "sample_path": sample.relative_to(SKILL).as_posix(),
        "sample_sha256": _sha(sample),
        "semantic_families": [family],
        "capacity": {"min_units": 2, "max_units": 4},
        "artifact_contract": {
            "width": 1080, "height": 1920, "fps": 24,
            "duration_min_sec": 4.99, "duration_max_sec": 5.01, "codec": "h264",
        },
        "render_contract": {
            "engine": "SemanticState",
            "composition_id": "semantic-state-" + family,
            "exit_policy": "external_compositor",
        },
        "visual_qa": {
            "status": review["visual_qa"]["status"],
            "reviewed_at": reviewed_at,
            "reviewer": reviewer,
            "frame_evidence": frame_evidence,
            "checks": {
                "no_clipping": True,
                "no_overlap": True,
                "no_placeholder_copy": True,
                "balanced_layout": True,
                "decorations_anchored": True,
                "no_exit_jump": True,
            },
        },
        "action_sequence_qa": {
            "status": review["action_sequence_qa"]["status"],
            "reviewed_at": reviewed_at,
            "reviewer": reviewer,
            "events": [
                {
                    "event": frame["role"],
                    "timestamp_sec": frame["timestamp_sec"],
                    "path": frame["path"],
                    "sha256": frame["sha256"],
                }
                for frame in action_frames
            ],
        },
    }
    record["verification_id"] = _verification_id(record)
    return record


def _reviewed_candidate(candidate: dict, *, source_registry: dict,
                        cases: list[dict], reviewed_at: str) -> dict:
    record = json.loads(json.dumps(candidate, ensure_ascii=False, allow_nan=False))
    record["execution_qa"] = {
        "status": "reviewed",
        "reviewed_at": reviewed_at,
        "reviewer": "Codex automated technical qualification; not human approval",
        "content_paths": ["/title", "/motion/source_text", "/motion/subjects"],
        "source_registry": json.loads(json.dumps(source_registry)),
        "cases": [
            {
                key: json.loads(json.dumps(case[key]))
                for key in ("brief", "recipe", "receipt", "sample", "frame_evidence")
            }
            for case in cases
        ],
    }
    record["verification_id"] = _verification_id(record)
    return record


def _recipe(adapter, job, brief: dict, payload: bytes, family: str, case: int,
            registry_path: str, registry_sha256: str) -> dict:
    component_id = "semantic-state-" + family
    component = {
        "component_id": component_id,
        "kind": "code_generated",
        "semantic_role": "explanation",
        "layer_role": "base",
        "executor": "reference_adapter",
        "media_type": "animation",
        "render_window": {
            "start_frame": 0, "end_frame": 120, "z_index": 0,
            "layout_slot": "full_frame", "opacity": 1.0,
            "safe_zone": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        },
        "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": False},
        **create_binding(
            adapter, job, payload,
            registry_path=registry_path,
            registry_sha256=registry_sha256,
        ),
    }
    return {
        "schema_version": 2,
        "segment_id": f"synthetic-semantic-{family}-{case}",
        "strategy_revision": 1,
        "mode": "single",
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "composition": {
            "family": "single_full_frame",
            "presenter_mode": "bottom_window",
            "reading_order": [component_id],
            "component_dependencies": [],
        },
        "components": [component],
        "final_compositor": "ffmpeg",
    }


def qualify(args) -> None:
    from edit.hd.tools.broll_component_executor import (
        ComponentExecutionRequest,
        execute_component,
        export_published_execution_binding,
    )
    from edit.hd.tools.visual_strategy import validate_shot_recipe_v2

    seed_root = args.seed_root.resolve(strict=True)
    review_root = args.review_root.resolve(strict=True)
    lineage = load_seed_lineage(seed_root)
    contracts, tools = build_runtime_contracts(args)
    with _owned_output(args.output) as output:
        assert_reviewed_source(lineage)
        candidates = {}
        registries = {}
        for family in FAMILIES:
            folder = output / family
            folder.mkdir()
            seed_item = lineage["families"][family]
            review = validate_review(
                load_review(review_root / family / "review.json"),
                family=family,
                seed_manifest_sha256=lineage["manifest_sha256"],
                brief_sha256=seed_item["brief"]["sha256"],
                sample_sha256=seed_item["sample"]["sha256"],
                source_sha256=lineage["source_sha256"],
            )
            sample = folder / "seed-sample.mp4"
            sample.write_bytes(seed_item["sample"]["bytes"])
            assert_reviewed_source(lineage)
            candidate = _candidate(
                family, sample, review,
                source_sha256=lineage["source_sha256"],
                frame_evidence=seed_item["frame_evidence"],
                action_frames=seed_item["action_frames"],
            )
            candidates[family] = candidate
            registry = folder / "qualification/source-registry.json"
            _write_json(registry, {"schema_version": 1, "templates": [candidate]})
            registries[family] = (registry.relative_to(SKILL).as_posix(), _sha(registry))
        pending = []
        for family in FAMILIES:
            registry_path, registry_sha = registries[family]
            cases = []
            for case in (1, 2):
                assert_reviewed_source(lineage)
                folder = output / family / f"case-{case}"
                folder.mkdir()
                brief = make_brief(family, case)
                _write_json(folder / "brief.json", brief)
                payload = (folder / "brief.json").read_bytes()
                job = create_synthetic_job(
                    folder / "fixture", output / family / "seed-sample.mp4", brief,
                )
                adapter = create_adapter(
                    template_id=TEMPLATES[family],
                    python_executable=Path(sys.executable),
                    node_executable=tools["node"],
                    playwright_module=tools["playwright"],
                    browser_executable=tools["browser"],
                    ffmpeg_executable=tools["ffmpeg"],
                    ffprobe_executable=tools["ffprobe"],
                    runtime_contracts=contracts,
                    brief_loader=lambda *_, content=payload: content,
                    registry_path=registry_path,
                    registry_sha256=registry_sha,
                )
                recipe = _recipe(
                    adapter, job, brief, payload, family, case,
                    registry_path, registry_sha,
                )
                validate_shot_recipe_v2(recipe)
                _write_json(folder / "recipe.json", recipe)
                adapters = {
                    "code_generated": {adapter.dependency_id: adapter},
                    "artifact_probe": create_artifact_probe(
                        ffprobe_executable=tools["ffprobe"],
                    ),
                }
                request = ComponentExecutionRequest(
                    recipe=recipe, component_id="semantic-state-" + family,
                )
                print(
                    f"Executing SemanticState {family} case {case}/2 (one worker)",
                    flush=True,
                )
                assert_reviewed_source(lineage)
                try:
                    result = execute_component(job, request, adapters=adapters)
                except BaseException as exc:
                    evidence = getattr(exc, "evidence", None)
                    if evidence is not None:
                        print(
                            "SemanticState execution evidence: "
                            + json.dumps(
                                dict(evidence), ensure_ascii=True, sort_keys=True,
                                separators=(",", ":"), default=str,
                            ),
                            file=sys.stderr,
                            flush=True,
                        )
                    raise
                replay = execute_component(job, request, adapters=adapters)
                assert_reviewed_source(lineage)
                if (result.output_sha256 != replay.output_sha256
                        or result.invocation_evidence != replay.invocation_evidence):
                    raise AssertionError("same-recipe replay changed invocation or output")
                published = export_published_execution_binding(
                    job, request, adapters=adapters,
                )
                assert_reviewed_source(lineage)
                rendered = job.job_dir / result.job_path
                shutil.copyfile(rendered, folder / "sample.mp4")
                _write_json(folder / "execution.json", {
                    "synthetic_fixture": True,
                    "human_approval_claimed": False,
                    "same_recipe_reuses_identical_invocation": True,
                    "artifact": dict(result),
                    "published_execution": published,
                    "absolute_output": str(rendered),
                })
                frames = _frame_proofs(
                    tools["ffmpeg"], folder / "sample.mp4", folder / "frames",
                    {"entry": 10, "stable": 72, "exit": 119},
                )
                actions = _frame_proofs(
                    tools["ffmpeg"], folder / "sample.mp4", folder / "action-frames",
                    dict(action_evidence_frames(brief)),
                )
                cases.append({
                    "brief": _proof(folder / "brief.json"),
                    "recipe": _proof(folder / "recipe.json"),
                    "receipt": _proof(folder / "execution.json"),
                    "sample": _proof(folder / "sample.mp4"),
                    "frame_evidence": frames,
                    "action_frames": actions,
                })
            pending.append({
                "family": family,
                "template_id": TEMPLATES[family],
                "source_registry": _proof(SKILL / registry_path),
                "cases": cases,
            })
        _write_json(output / "pending-registration.json", {
            "status": "pending_visual_review",
            "human_approval_claimed": False,
            "families": pending,
        })


def audit(args) -> None:
    from verify_broll_template import (
        _decoded_frame_hashes,
        _proof_asset,
        _proof_json,
        _verify_template,
    )

    output = _qualified_output(args.output).resolve(strict=True)
    pending_path = output / "pending-registration.json"
    pending = json.loads(_read_snapshot(
        pending_path, "pending registration", executable=False,
        maximum=4 * 1024 * 1024,
    ).decode("utf-8"), object_pairs_hook=_unique_json)
    if (type(pending) is not dict
            or set(pending) != {"status", "human_approval_claimed", "families"}
            or pending["status"] != "pending_visual_review"
            or pending["human_approval_claimed"] is not False
            or type(pending["families"]) is not list
            or len(pending["families"]) != len(FAMILIES)):
        raise ValueError("pending registration fields are invalid")
    if type(args.reviewed_at) is not str or not args.reviewed_at.strip():
        raise ValueError("audit requires a reviewed-at value")

    reviewed = []
    seen = set()
    for item in pending["families"]:
        if (type(item) is not dict
                or set(item) != {"family", "template_id", "source_registry", "cases"}):
            raise ValueError("pending registration family fields are invalid")
        family = item["family"]
        if (family not in FAMILIES or family in seen
                or item["template_id"] != TEMPLATES[family]
                or type(item["cases"]) is not list or len(item["cases"]) != 2):
            raise ValueError("pending registration family identity is invalid")
        seen.add(family)
        source_registry = _proof_json(
            SKILL, item["source_registry"], f"{family}.source_registry",
        )
        templates = source_registry.get("templates")
        if (source_registry.get("schema_version") != 1
                or type(templates) is not list or len(templates) != 1):
            raise ValueError("qualification source registry is invalid")
        candidate = _reviewed_candidate(
            templates[0], source_registry=item["source_registry"],
            cases=item["cases"], reviewed_at=args.reviewed_at,
        )
        _verify_template(SKILL, candidate)

        action_count = 0
        for case_index, case in enumerate(item["cases"], start=1):
            if (type(case) is not dict
                    or set(case) != {
                        "brief", "recipe", "receipt", "sample",
                        "frame_evidence", "action_frames",
                    }):
                raise ValueError("qualification case fields are invalid")
            actions = case["action_frames"]
            if type(actions) is not list or [frame.get("role") for frame in actions] != list(PATTERNS[family]):
                raise ValueError("qualification action frame roles are invalid")
            sample = _proof_asset(SKILL, case["sample"], f"{family}.case-{case_index}.sample")
            for action in actions:
                if (type(action) is not dict
                        or set(action) != {"role", "timestamp_sec", "path", "sha256"}
                        or type(action["timestamp_sec"]) not in (int, float)
                        or not 0 <= action["timestamp_sec"] < 5.01
                        or abs(action["timestamp_sec"] * 24 - round(action["timestamp_sec"] * 24)) > 0.000001):
                    raise ValueError("qualification action frame fields are invalid")
                frame = _proof_asset(
                    SKILL, {"path": action["path"], "sha256": action["sha256"]},
                    f"{family}.case-{case_index}.{action['role']}",
                )
                index = round(action["timestamp_sec"] * 24)
                if (_decoded_frame_hashes(sample, [index])[0]
                        != _decoded_frame_hashes(frame)[0]):
                    raise ValueError("qualification action frame pixels differ from sample")
                action_count += 1
        reviewed.append((family, candidate, action_count))
    if seen != set(FAMILIES):
        raise ValueError("pending registration does not cover all families")

    report = []
    for family, candidate, action_count in reviewed:
        registry = output / family / "reviewed-registry.json"
        if registry.exists():
            raise ValueError("reviewed qualification registry already exists")
        _write_json(registry, {"schema_version": 1, "templates": [candidate]})
        report.append({
            "family": family,
            "template_id": TEMPLATES[family],
            "reviewed_registry": _proof(registry),
            "case_count": 2,
            "action_frames_verified": action_count,
        })
    destination = output / "qualification-report.json"
    if destination.exists():
        raise ValueError("qualification report already exists")
    _write_json(destination, {
        "status": "reviewed",
        "reviewed_at": args.reviewed_at,
        "human_approval_claimed": False,
        "families": report,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("seed", "qualify", "audit"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed-root", type=Path)
    parser.add_argument("--review-root", type=Path)
    parser.add_argument("--reviewed-at")
    for name in ("node", "playwright", "browser", "ffmpeg", "ffprobe"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve(strict=True)))
    if args.mode == "seed":
        seed(args)
    elif args.mode == "qualify":
        if args.seed_root is None or args.review_root is None:
            parser.error("qualify requires --seed-root and --review-root")
        qualify(args)
    else:
        if not args.reviewed_at:
            parser.error("audit requires --reviewed-at")
        audit(args)


if __name__ == "__main__":
    main()
