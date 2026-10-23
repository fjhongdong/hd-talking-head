"""Approved content map: the only semantic source for full-v2 consumers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from . import contract_artifacts, material_usage, state


ALLOWED_EVIDENCE = {"supported", "needs_user_decision", "unsupported"}
ALLOWED_PRIORITIES = {"critical", "high", "medium", "low"}
ALLOWED_BROLL_PRIORITIES = {"high", "medium", "none"}
ALLOWED_SEMANTIC_TYPES = {
    "fact",
    "opinion",
    "case",
    "contrast",
    "process",
    "metaphor",
    "identity",
    "number",
    "interface",
    "thesis",
}


class ContentAnalysisError(ValueError):
    """Raised when a content map is invalid, stale, or not approved."""


def _object(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContentAnalysisError(f"{label} must be an object")
    return dict(value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContentAnalysisError(f"{label} schema is invalid")


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ContentAnalysisError(f"{label} must be non-empty text")
    return value


def _span(value: Any, script_text: str, label: str) -> Tuple[int, int]:
    if (
        type(value) is not list
        or len(value) != 2
        or any(type(part) is not int for part in value)
    ):
        raise ContentAnalysisError(f"{label} source_span is invalid")
    start, end = value
    if start < 0 or end <= start or end > len(script_text):
        raise ContentAnalysisError(f"{label} source_span is outside the script")
    return start, end


def _string_list(value: Any, label: str, *, allow_empty: bool = True) -> List[str]:
    if type(value) is not list or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise ContentAnalysisError(f"{label} must be a text list")
    if not allow_empty and not value:
        raise ContentAnalysisError(f"{label} must not be empty")
    if len(set(value)) != len(value):
        raise ContentAnalysisError(f"{label} contains duplicates")
    return list(value)


def _validate_sections(value: Any, script_text: str) -> List[Dict[str, Any]]:
    if type(value) is not list or not value:
        raise ContentAnalysisError("sections must be a non-empty list")
    sections: List[Dict[str, Any]] = []
    identifiers = set()
    for index, raw in enumerate(value):
        section = _object(raw, f"section {index}")
        _exact_keys(section, {"id", "title", "source_span"}, f"section {index}")
        identifier = _text(section["id"], f"section {index} id")
        if identifier in identifiers:
            raise ContentAnalysisError("section id contains duplicates")
        identifiers.add(identifier)
        start, end = _span(section["source_span"], script_text, f"section {identifier}")
        sections.append(
            {
                "id": identifier,
                "title": _text(section["title"], f"section {identifier} title"),
                "source_span": [start, end],
            }
        )
    return sections


def _validate_items(value: Any, script_text: str) -> List[Dict[str, Any]]:
    if type(value) is not list or not value:
        raise ContentAnalysisError("items must be a non-empty list")
    items: List[Dict[str, Any]] = []
    identifiers = set()
    expected = {
        "id",
        "source_text",
        "source_span",
        "priority",
        "keywords",
        "semantic_type",
        "evidence_status",
        "broll_priority",
    }
    for index, raw in enumerate(value):
        item = _object(raw, f"item {index}")
        _exact_keys(item, expected, f"item {index}")
        identifier = _text(item["id"], f"item {index} id")
        if identifier in identifiers:
            raise ContentAnalysisError("item id contains duplicates")
        identifiers.add(identifier)
        start, end = _span(item["source_span"], script_text, f"item {identifier}")
        source_text = _text(item["source_text"], f"item {identifier} source_text")
        if script_text[start:end] != source_text:
            raise ContentAnalysisError(
                f"item {identifier} source_text does not match the script"
            )
        keywords = _string_list(
            item["keywords"], f"item {identifier} keywords", allow_empty=False
        )
        if any(keyword not in source_text for keyword in keywords):
            raise ContentAnalysisError(
                f"item {identifier} keyword is absent from source_text"
            )
        priority = item["priority"]
        broll_priority = item["broll_priority"]
        evidence = item["evidence_status"]
        semantic_type = item["semantic_type"]
        if priority not in ALLOWED_PRIORITIES:
            raise ContentAnalysisError(f"item {identifier} priority is invalid")
        if broll_priority not in ALLOWED_BROLL_PRIORITIES:
            raise ContentAnalysisError(f"item {identifier} broll_priority is invalid")
        if evidence not in ALLOWED_EVIDENCE:
            raise ContentAnalysisError(f"item {identifier} evidence_status is invalid")
        if semantic_type not in ALLOWED_SEMANTIC_TYPES:
            raise ContentAnalysisError(f"item {identifier} semantic_type is invalid")
        if evidence == "unsupported" and (
            priority in {"critical", "high"} or broll_priority == "high"
        ):
            raise ContentAnalysisError(
                f"unsupported item {identifier} cannot be high priority"
            )
        items.append(
            {
                "id": identifier,
                "source_text": source_text,
                "source_span": [start, end],
                "priority": priority,
                "keywords": keywords,
                "semantic_type": semantic_type,
                "evidence_status": evidence,
                "broll_priority": broll_priority,
            }
        )
    return items


def _validate_claims(value: Any, script_text: str) -> List[Dict[str, Any]]:
    if type(value) is not list:
        raise ContentAnalysisError("claims must be a list")
    claims: List[Dict[str, Any]] = []
    identifiers = set()
    required = {"id", "source_text", "source_span", "evidence_status"}
    optional = {"entities", "numbers", "source_requirements"}
    for index, raw in enumerate(value):
        claim = _object(raw, f"claim {index}")
        if not required.issubset(claim) or not set(claim).issubset(required | optional):
            raise ContentAnalysisError(f"claim {index} schema is invalid")
        identifier = _text(claim["id"], f"claim {index} id")
        if identifier in identifiers:
            raise ContentAnalysisError("claim id contains duplicates")
        identifiers.add(identifier)
        start, end = _span(claim["source_span"], script_text, f"claim {identifier}")
        source_text = _text(claim["source_text"], f"claim {identifier} source_text")
        if script_text[start:end] != source_text:
            raise ContentAnalysisError(
                f"claim {identifier} source_text does not match the script"
            )
        evidence = claim["evidence_status"]
        if evidence not in ALLOWED_EVIDENCE:
            raise ContentAnalysisError(f"claim {identifier} evidence_status is invalid")
        normalized = {
            "id": identifier,
            "source_text": source_text,
            "source_span": [start, end],
            "evidence_status": evidence,
            "entities": _string_list(claim.get("entities", []), "claim entities"),
            "numbers": _string_list(claim.get("numbers", []), "claim numbers"),
            "source_requirements": _string_list(
                claim.get("source_requirements", []), "claim source_requirements"
            ),
        }
        claims.append(normalized)
    return claims


def validate_content_analysis(
    analysis: Mapping[str, Any], *, script_text: str,
) -> Dict[str, Any]:
    value = _object(analysis, "content analysis")
    _exact_keys(
        value,
        {"thesis", "hook", "sections", "items", "claims"},
        "content analysis",
    )
    if type(script_text) is not str or not script_text:
        raise ContentAnalysisError("script text is unavailable")
    return {
        "thesis": _text(value["thesis"], "thesis"),
        "hook": _text(value["hook"], "hook"),
        "sections": _validate_sections(value["sections"], script_text),
        "items": _validate_items(value["items"], script_text),
        "claims": _validate_claims(value["claims"], script_text),
    }


def render_analysis_review(record: Mapping[str, Any]) -> str:
    analysis = record["analysis"]
    lines = [
        "# 内容理解审核",
        "",
        f"- 核心观点：{analysis['thesis']}",
        f"- 开场钩子：{analysis['hook']}",
        f"- 内容地图 SHA-256：`{record['analysis_sha256']}`",
        "",
        "## 重点、关键词与 B-roll 优先级",
        "",
    ]
    labels = {
        "supported": "已有支持",
        "needs_user_decision": "待用户决定",
        "unsupported": "不支持上屏",
    }
    for item in analysis["items"]:
        lines.extend(
            [
                f"### {item['id']} · {item['priority']} · {item['broll_priority']}",
                "",
                f"> {item['source_text']}",
                "",
                f"- 关键词：{'、'.join(item['keywords'])}",
                f"- 类型：{item['semantic_type']}",
                f"- 证据：{labels[item['evidence_status']]}",
                "",
            ]
        )
    pending = [
        item for item in analysis["items"]
        if item["evidence_status"] == "needs_user_decision"
    ]
    lines.extend(["## 待用户决定", ""])
    if pending:
        lines.extend(f"- {item['id']}：{item['source_text']}" for item in pending)
    else:
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def _script_text(job: state.JobState) -> str:
    path = job.root / job.inputs["script"]["path"]
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContentAnalysisError("unable to read the bound script") from exc


def prepare_content_analysis(
    job: state.JobState, analysis: Mapping[str, Any],
) -> Dict[str, Any]:
    state.require_runnable(job, "content_analysis")
    normalized = validate_content_analysis(analysis, script_text=_script_text(job))
    base_record: Dict[str, Any] = {
        "schema_version": 1,
        "script_sha256": job.inputs["script"]["sha256"],
        "analysis": normalized,
    }
    record = dict(base_record)
    record["analysis_sha256"] = contract_artifacts.sha256_json(base_record)
    output = job.job_dir / "02-content-analysis"
    record_path = output / "content-analysis.json"
    review_path = output / "review.md"
    contract_artifacts.write_json_artifact(record_path, record)
    contract_artifacts.write_text_artifact(review_path, render_analysis_review(record))
    material_usage.publish_and_mark_ready(
        job,
        "content_analysis",
        (record_path, review_path),
        producer="edit.hd.tools.content_analysis",
        producer_version="1",
        stage_input_records=material_usage.current_stage_input_records(
            job, "content_analysis"
        ),
        references=[],
    )
    return record


def load_approved_content_analysis(job: state.JobState) -> Dict[str, Any]:
    if "content_analysis" not in job.stages:
        raise ContentAnalysisError("content_analysis is unavailable for legacy workflow")
    if job.stages["content_analysis"]["status"] != "approved":
        raise ContentAnalysisError("content_analysis must be approved")
    record = contract_artifacts.read_json_artifact(
        job.job_dir / "02-content-analysis" / "content-analysis.json"
    )
    _exact_keys(
        record,
        {"schema_version", "script_sha256", "analysis", "analysis_sha256"},
        "content analysis record",
    )
    if record["schema_version"] != 1:
        raise ContentAnalysisError("content_analysis schema version is invalid")
    if record["script_sha256"] != job.inputs["script"]["sha256"]:
        raise ContentAnalysisError("content_analysis script identity changed")
    normalized = validate_content_analysis(
        record["analysis"], script_text=_script_text(job)
    )
    base_record = {
        "schema_version": 1,
        "script_sha256": record["script_sha256"],
        "analysis": normalized,
    }
    expected = contract_artifacts.sha256_json(base_record)
    if record["analysis_sha256"] != expected:
        raise ContentAnalysisError("content_analysis identity changed")
    return {**base_record, "analysis_sha256": expected}
