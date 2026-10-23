"""Candidate/variant contracts for safe partial reuse across Job revisions."""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping

from .contract_artifacts import sha256_json


class VariantMatrixError(ValueError):
    """Raised when candidate reuse could become ambiguous or unsafe."""


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_STATUSES = frozenset({"planned", "ready_for_review", "approved", "invalidated"})


def _fail(message: str) -> None:
    raise VariantMatrixError(message)


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        _fail(f"{label} must be non-empty text")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if _IDENTIFIER.fullmatch(result) is None:
        _fail(f"{label} must be a safe identifier")
    return result


def _sha_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase sha256 or null")
    return value


def _strict(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} fields are invalid")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        _fail(f"{label} must be a list of non-empty text")
    if len(value) != len(set(value)):
        _fail(f"{label} must not contain duplicates")
    return list(value)


def _approval(value: object, label: str) -> dict[str, Any]:
    approval = _strict(value, {"status", "stage", "revision", "receipt_sha256"}, label)
    status = _text(approval["status"], f"{label}.status")
    if status not in {"not_approved", "ready_for_review", "approved"}:
        _fail(f"{label}.status is unsupported")
    _text(approval["stage"], f"{label}.stage")
    _identifier(approval["revision"], f"{label}.revision")
    _sha_or_none(approval["receipt_sha256"], f"{label}.receipt_sha256")
    if status == "approved" and approval["receipt_sha256"] is None:
        _fail(f"{label}.receipt_sha256 is required for approved candidates")
    return copy.deepcopy(approval)


def validate_variant_matrix(
    value: object,
    *,
    expected_job_revision: str | None = None,
) -> dict[str, Any]:
    """Validate a candidate graph and prove its manifest hash."""

    matrix = _strict(
        value,
        {"schema_version", "job_revision", "targets", "candidates", "manifest_sha256"},
        "variant matrix",
    )
    if matrix["schema_version"] != "variant-matrix/v1":
        _fail("unsupported variant matrix schema")
    job_revision = _identifier(matrix["job_revision"], "job_revision")
    if expected_job_revision is not None and job_revision != _identifier(expected_job_revision, "expected_job_revision"):
        _fail("variant matrix belongs to a different Job revision")
    targets_value = matrix["targets"]
    candidates_value = matrix["candidates"]
    if type(targets_value) is not list or not targets_value:
        _fail("targets must be a non-empty list")
    if type(candidates_value) is not list:
        _fail("candidates must be a list")
    target_ids: set[str] = set()
    target_candidate_refs: dict[str, dict[str, str]] = {}
    targets: list[dict[str, Any]] = []
    for index, raw_target in enumerate(targets_value):
        target = _strict(raw_target, {"target_id", "candidates"}, f"targets[{index}]")
        target_id = _identifier(target["target_id"], f"targets[{index}].target_id")
        if target_id in target_ids:
            _fail("target_id values must be unique")
        target_ids.add(target_id)
        refs = target["candidates"]
        if type(refs) is not dict or not refs:
            _fail(f"targets[{index}].candidates must be a non-empty object")
        normalized_refs: dict[str, str | None] = {}
        for slot, candidate_id in refs.items():
            _identifier(slot, f"targets[{index}].candidates slot")
            if candidate_id is not None:
                normalized_id = _identifier(candidate_id, f"targets[{index}].candidates[{slot}]")
                target_candidate_refs.setdefault(target_id, {})[slot] = normalized_id
                normalized_refs[slot] = normalized_id
            else:
                normalized_refs[slot] = None
        targets.append({"target_id": target_id, "candidates": normalized_refs})
    candidate_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for index, raw_candidate in enumerate(candidates_value):
        candidate = _strict(
            raw_candidate,
            {
                "candidate_id", "target_id", "slot", "status", "input_fingerprint",
                "artifact_sha256", "source_revision", "reuse_from", "affected_scope", "approval",
            },
            f"candidates[{index}]",
        )
        candidate_id = _identifier(candidate["candidate_id"], f"candidates[{index}].candidate_id")
        if candidate_id in candidate_ids:
            _fail("candidate_id values must be unique")
        candidate_ids.add(candidate_id)
        target_id = _identifier(candidate["target_id"], f"candidates[{index}].target_id")
        if target_id not in target_ids:
            _fail(f"candidates[{index}] references an unknown target")
        slot = _identifier(candidate["slot"], f"candidates[{index}].slot")
        status = _text(candidate["status"], f"candidates[{index}].status")
        if status not in _STATUSES:
            _fail(f"candidates[{index}].status is unsupported")
        input_fingerprint = _sha_or_none(candidate["input_fingerprint"], f"candidates[{index}].input_fingerprint")
        if input_fingerprint is None:
            _fail(f"candidates[{index}].input_fingerprint is required")
        artifact_sha256 = _sha_or_none(candidate["artifact_sha256"], f"candidates[{index}].artifact_sha256")
        if status in {"ready_for_review", "approved"} and artifact_sha256 is None:
            _fail(f"candidates[{index}].artifact_sha256 is required for produced candidates")
        source_revision = _identifier(candidate["source_revision"], f"candidates[{index}].source_revision")
        reuse_from = candidate["reuse_from"]
        if reuse_from is not None:
            reuse_from = _identifier(reuse_from, f"candidates[{index}].reuse_from")
            if reuse_from == candidate_id:
                _fail(f"candidates[{index}] cannot reuse itself")
        affected_scope = _string_list(candidate["affected_scope"], f"candidates[{index}].affected_scope")
        approval = _approval(candidate["approval"], f"candidates[{index}].approval")
        candidates.append({
            "candidate_id": candidate_id,
            "target_id": target_id,
            "slot": slot,
            "status": status,
            "input_fingerprint": input_fingerprint,
            "artifact_sha256": artifact_sha256,
            "source_revision": source_revision,
            "reuse_from": reuse_from,
            "affected_scope": affected_scope,
            "approval": approval,
        })
    referenced_ids: set[str] = set()
    for refs in target_candidate_refs.values():
        referenced_ids.update(refs.values())
    if candidate_ids != referenced_ids:
        _fail("target candidate references do not match candidate records")
    by_id = {item["candidate_id"]: item for item in candidates}
    for target_id, refs in target_candidate_refs.items():
        for slot, candidate_id in refs.items():
            selected = by_id[candidate_id]
            if selected["target_id"] != target_id or selected["slot"] != slot:
                _fail(f"target candidate slot does not match {candidate_id}")
    for candidate in candidates:
        if candidate["reuse_from"] is not None and candidate["reuse_from"] not in by_id:
            _fail(f"{candidate['candidate_id']} reuses an unknown candidate")
        if candidate["reuse_from"] is not None:
            source = by_id[candidate["reuse_from"]]
            if source["target_id"] != candidate["target_id"] or source["slot"] != candidate["slot"]:
                _fail(f"{candidate['candidate_id']} reuses a different target or slot")
        if candidate["status"] == "approved" and candidate["approval"]["status"] != "approved":
            _fail(f"{candidate['candidate_id']} status and approval disagree")
    for candidate_id in by_id:
        seen: set[str] = set()
        current = candidate_id
        while by_id[current]["reuse_from"] is not None:
            if current in seen:
                _fail("candidate reuse graph contains a cycle")
            seen.add(current)
            current = by_id[current]["reuse_from"]
    unsigned = {
        "schema_version": matrix["schema_version"],
        "job_revision": job_revision,
        "targets": targets,
        "candidates": candidates,
    }
    if matrix["manifest_sha256"] != sha256_json(unsigned):
        _fail("variant matrix hash does not match its contents")
    return {**unsigned, "manifest_sha256": matrix["manifest_sha256"]}


def build_variant_matrix(*, job_revision: str, targets: list[Mapping[str, object]], candidates: list[Mapping[str, object]]) -> dict[str, Any]:
    """Build a canonical variant matrix and calculate its manifest hash."""

    unsigned = {
        "schema_version": "variant-matrix/v1",
        "job_revision": job_revision,
        "targets": [copy.deepcopy(dict(item)) for item in targets],
        "candidates": [copy.deepcopy(dict(item)) for item in candidates],
    }
    unsigned["manifest_sha256"] = sha256_json(unsigned)
    return validate_variant_matrix(unsigned, expected_job_revision=job_revision)
