"""Bind Skill-managed jobs to their approved setup, without running media jobs."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import contract_artifacts as artifacts
from .state import WorkflowError


CONTRACT_VERSION = "hd-full-v2-startup-v1"
PREFLIGHT_MAX_AGE_SECONDS = 86400
MAX_GENERATION_CONCURRENCY = 2


def assert_project_origin(project_root: Path) -> None:
    """Never evict live modules and leave callers holding two runtime versions."""
    project_root = project_root.resolve()
    for name, module in tuple(sys.modules.items()):
        if name != "edit" and not name.startswith("edit."):
            continue
        filename = getattr(module, "__file__", None)
        paths = [Path(filename)] if filename else [Path(p) for p in getattr(module, "__path__", ())]
        if any(not path.resolve().is_relative_to(project_root / "edit") for path in paths):
            raise WorkflowError("startup cached module origin differs from selected project; use a fresh Python process")


def runtime_identity(project_root: Path) -> dict:
    project_root = project_root.resolve()
    source_root = project_root / "edit/hd/tools"
    required = ("state.py", "startup.py", "segment_render.py")
    if any(not (source_root / name).is_file() for name in required):
        raise WorkflowError("startup runtime contract is unavailable; update the selected project runtime")
    modules = {}
    for path in sorted(source_root.rglob("*.py")):
        if path.is_symlink() or not path.resolve().is_relative_to(source_root):
            raise WorkflowError("startup runtime module must be a local regular file")
        modules[path.relative_to(project_root).as_posix()] = artifacts.sha256_file(path)
    try:
        tree = ast.parse((source_root / "segment_render.py").read_text(encoding="utf-8"))
        contracts = [ast.literal_eval(node.value) for node in tree.body
                     if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "RENDERER_CONTRACT_VERSION" for t in node.targets)]
    except (OSError, SyntaxError, ValueError) as exc:
        raise WorkflowError("startup renderer contract is unreadable") from exc
    if len(contracts) != 1 or not isinstance(contracts[0], str):
        raise WorkflowError("startup renderer contract is missing")
    return {
        "contract_version": CONTRACT_VERSION,
        "project_root": str(project_root), "modules": modules,
        "compositor_contract": contracts[0],
        "python": {"executable": sys.executable, "prefix": sys.prefix,
                   "version": sys.version.split()[0]},
    }


def _read(path: Path, label: str) -> dict:
    if path.resolve() != path.absolute() or not path.is_file():
        raise WorkflowError(f"startup {label} is missing or not a regular file")
    try:
        return artifacts.read_json_artifact(path)
    except artifacts.ContractArtifactError as exc:
        raise WorkflowError(f"startup {label} is invalid") from exc


def _context(job) -> dict:
    context = _read(job.root / "job-context.json", "context")
    expected = {"workspace": str(job.root), "job_dir": str(job.job_dir), "job_id": job.job_id}
    if any(context.get(key) != value for key, value in expected.items()):
        raise WorkflowError("startup context belongs to another Job")
    project = Path(__file__).resolve().parents[3]
    assert_project_origin(project)
    if context.get("project_root") != str(project) or context.get("runtime") != runtime_identity(project):
        raise WorkflowError("startup runtime changed; review the runtime difference before resuming")
    release = context.get("skill_release")
    if not isinstance(release, dict) or not isinstance(release.get("root"), str):
        raise WorkflowError("startup Skill release is missing; explicit migration is required")
    root = Path(release["root"])
    manifest_path = root / "release-manifest.json"
    manifest = _read(manifest_path, "Skill release manifest")
    if (manifest.get("release_id") != release.get("release_id")
            or artifacts.sha256_file(manifest_path) != release.get("manifest_sha256")):
        raise WorkflowError("startup Skill release changed; explicit migration is required")
    # Read-only verification in an isolated process also avoids cached verifier modules.
    try:
        checked = subprocess.run(
            [sys.executable, str(root / "scripts/verify_skill_release.py")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        result = json.loads(checked.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise WorkflowError("startup Skill release verification failed") from exc
    if checked.returncode or result.get("status") != "pass" or result.get("manifest_sha256") != release["manifest_sha256"]:
        raise WorkflowError("startup Skill release integrity check failed")
    return context


def _config(job) -> tuple[Path, str]:
    path = job.job_dir / "manifests/provider-config.json"
    config = _read(path, "provider config")
    version = config.get("schema_version")
    fields = {"schema_version", "providers", "max_concurrency", "generation_enabled"}
    if version == 2:
        fields.add("reference_asr")
    if (set(config) != fields
            or type(version) is not int or version not in {1, 2}
            or type(config["max_concurrency"]) is not int
            or config["max_concurrency"] not in {1, MAX_GENERATION_CONCURRENCY}
            or type(config["generation_enabled"]) is not bool
            or not isinstance(config["providers"], list)):
        raise WorkflowError("startup provider config fields are invalid")
    reference_asr = config.get("reference_asr")
    if reference_asr is not None:
        if (not isinstance(reference_asr, dict)
                or set(reference_asr) != {"provider", "model", "execution", "upload_policy"}
                or reference_asr["provider"] != "whisper.cpp"
                or reference_asr["execution"] != "local"
                or reference_asr["upload_policy"] != "forbidden"
                or not isinstance(reference_asr["model"], str)
                or re.fullmatch(r"ggml-[a-z0-9][a-z0-9.-]*", reference_asr["model"]) is None):
            raise WorkflowError("startup reference ASR must identify an explicit local model without upload")
    fields = {"purpose", "provider", "model", "endpoint_id", "connection_status",
              "reference_images", "native_9_16", "silent_output", "quota_status"}
    purposes = set()
    for provider in config["providers"]:
        if (not isinstance(provider, dict) or set(provider) != fields
                or provider["purpose"] not in {"image", "video", "stock"}
                or provider["purpose"] in purposes
                or provider["connection_status"] not in {"verified", "unavailable", "not_required"}
                or provider["quota_status"] not in {"available", "unknown", "unavailable"}
                or any(type(provider[k]) is not bool for k in ("reference_images", "native_9_16", "silent_output"))
                or any(not isinstance(provider[k], str) or not provider[k].strip()
                       for k in ("provider", "model", "endpoint_id"))):
            raise WorkflowError("startup provider config must contain identifiers/capabilities, never credentials")
        purposes.add(provider["purpose"])
    if config["generation_enabled"] and not purposes.intersection({"image", "video"}):
        raise WorkflowError("startup generation config has no image/video provider")
    return path, artifacts.sha256_file(path)


def selected_channels(config: dict) -> dict:
    """Return the one confirmed image/video channel for this Job."""
    providers = {p["purpose"]: p for p in config["providers"] if p["purpose"] in {"image", "video"}}
    if config.get("generation_enabled") is False:
        return {}
    if set(providers) != {"image", "video"}:
        raise WorkflowError("startup requires one image and one video channel")
    if any(p["connection_status"] != "verified" or p["quota_status"] == "unavailable" for p in providers.values()):
        raise WorkflowError("startup image and video channels must be connected and available")
    return {purpose: {"provider": p["provider"], "model": p["model"],
                      "endpoint_id": p["endpoint_id"]}
            for purpose, p in providers.items()}


def _report(job, context: dict, config_sha256: str) -> None:
    report = _read(job.job_dir / "manifests/dependency-preflight.json", "preflight")
    if report.get("job_context") != {"job_id": job.job_id, "workspace": str(job.root)}:
        raise WorkflowError("startup preflight belongs to another Job or has no Job binding")
    if report.get("provider_config_sha256") != config_sha256:
        raise WorkflowError("startup preflight config changed; rerun preflight")
    manifest_path = Path(context["skill_release"]["root"]) / "references/dependency-manifest.json"
    manifest = _read(manifest_path, "dependency manifest")
    if (report.get("manifest_path") != str(manifest_path)
            or report.get("manifest_sha256") != artifacts.sha256_file(manifest_path)
            or report.get("project_root") != context["project_root"]
            or report.get("runtime") != context["runtime"]):
        raise WorkflowError("startup preflight runtime or dependency manifest changed")
    try:
        checked_at = datetime.fromisoformat(report["checked_at"])
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowError("startup preflight timestamp is invalid") from exc
    if not 0 <= age <= PREFLIGHT_MAX_AGE_SECONDS:
        raise WorkflowError("startup preflight is stale; refresh checks without repeating unchanged config approval")
    summary = report.get("summary", {})
    dependencies = report.get("dependencies")
    if (summary.get("status") not in {"ready", "ready_with_optional_gaps"}
            or summary.get("required_missing") != 0 or not isinstance(dependencies, list)
            or any(not isinstance(item, dict) for item in dependencies)):
        raise WorkflowError("startup preflight dependencies are not ready")
    by_id = {item.get("id"): item for item in dependencies}
    if len(by_id) != len(dependencies):
        raise WorkflowError("startup preflight dependencies are duplicated")
    # Read the exact configuration bytes bound by this report, not a second
    # unbound path read. Existing schema-1 jobs do not enable reference ASR.
    from . import transcribe
    try:
        pinned = transcribe._pin_local_media(job.job_dir / "manifests/provider-config.json",
                                            expected_sha256=config_sha256)
        try:
            config = json.loads(transcribe._read_descriptor_text(pinned.descriptor))
            transcribe._verify_pinned(pinned)
        finally:
            if not transcribe._close_descriptor(pinned.descriptor):
                raise WorkflowError("startup reference ASR config cleanup failed")
    except (OSError, ValueError, transcribe.TranscriptionError) as exc:
        raise WorkflowError("startup reference ASR configuration changed or is unreadable") from exc
    selected_asr = config.get("reference_asr")
    if selected_asr is not None:
        result = by_id.get("reference-asr", {})
        probe = result.get("reference_asr_probe")
        if (not isinstance(selected_asr, dict) or not isinstance(probe, dict)
                or result.get("required") is not True or result.get("selected") is not True
                or result.get("callable") is not True or result.get("status") != "callable"
                or probe.get("provider_config_sha256") != config_sha256
                or probe.get("callable") is not True or probe.get("model_load_verified") is not False
                or any(probe.get(k) != v for k, v in selected_asr.items())):
            raise WorkflowError("startup reference ASR probe is missing or mismatched")
        for key in ("executable", "model_file"):
            file_identity = probe.get(key)
            if (not isinstance(file_identity, dict)
                    or not isinstance(file_identity.get("path"), str)
                    or not Path(file_identity["path"]).is_absolute()
                    or not isinstance(file_identity.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", file_identity["sha256"]) is None
                    or type(file_identity.get("bytes")) is not int or file_identity["bytes"] <= 0):
                raise WorkflowError("startup reference ASR file identity is invalid")
    for item in manifest["dependencies"]:
        result = by_id.get(item["id"])
        if item.get("required") and (not result or result.get("required") is not True):
            raise WorkflowError("startup preflight dependency result is missing")
        if result and result.get("required"):
            level = item.get("required_level", "installed")
            if (result.get("status") not in {"available", "callable", "connected", "bound"}
                    or (level != "installed" and result.get(level) is not True)):
                raise WorkflowError("startup preflight dependency is not satisfied: " + item["id"])
    plan = job.job_dir / "07-visual-direction/visual-plan.json"
    if plan.is_file() and job.stages["visual_direction"]["status"] == "approved":
        if report.get("visual_plan") != {"path": str(plan), "sha256": artifacts.sha256_file(plan)}:
            raise WorkflowError("startup preflight does not match the approved visual plan")


def _approval_identity(job, context: dict, config_sha256: str) -> dict:
    identity = {"schema_version": 1, "job_id": job.job_id, "workspace": str(job.root),
            "provider_config_sha256": config_sha256,
            "runtime_sha256": artifacts.sha256_json(context["runtime"]),
            "skill_release": context["skill_release"]}
    bindings = job.job_dir / "manifests/generation-channels.json"
    config = _read(job.job_dir / "manifests/provider-config.json", "provider config")
    if config.get("generation_enabled") and not bindings.is_file():
        raise WorkflowError("confirm model and reference bindings for both generation channels")
    if bindings.is_file():
        data = _read(bindings, "generation channels")
        if data.get("schema_version") != 1 or set(data) - {"schema_version", "image", "video"}:
            raise WorkflowError("generation channel bindings are invalid")
        for purpose in ("image", "video"):
            if config.get("generation_enabled"):
                from . import generation_model, generation_inputs
                try:
                    binding = data.get(purpose, {})
                    generation_model.validate_binding(binding.get("model_binding"))
                    generation_inputs.validate_binding(binding)
                except ValueError as exc:
                    raise WorkflowError(str(exc)) from exc
            query = data.get(purpose, {}).get("query")
            if query is not None and (not isinstance(query, dict) or not isinstance(query.get("tool"), str)
                                      or not query["tool"] or not isinstance(query.get("arguments", {}), dict)):
                raise WorkflowError("generation query must identify its real tool and arguments")
        identity["generation_channels_sha256"] = artifacts.sha256_file(bindings)
    return identity


def confirm_setup(job, config_path: Path, *, user_confirmation: str,
                  image_channel: str | None = None,
                  video_channel: str | None = None) -> Path:
    """Record a real current-user approval; never infer it from a successful probe."""
    if not isinstance(user_confirmation, str) or not user_confirmation.strip():
        raise WorkflowError("startup requires explicit user confirmation")
    context = _context(job)
    config, digest = _config(job)
    if config_path.resolve() != config:
        raise WorkflowError("startup config must be the current Job provider-config.json")
    _report(job, context, digest)
    channels = selected_channels(json.loads(config.read_bytes()))
    requested = {"image": image_channel, "video": video_channel}
    for purpose, channel in requested.items():
        if channel is not None:
            if purpose not in channels or channel != channels[purpose]["endpoint_id"]:
                raise WorkflowError(f"{purpose} channel is not one of the configured choices")
    # A config with one provider per purpose is the current minimal selection
    # surface; the receipt makes that choice explicit for downstream requests.
    identity = _approval_identity(job, context, digest)
    path = job.job_dir / "manifests/setup-approval.json"
    if path.exists():
        previous = _read(path, "setup confirmation")
        if all(previous.get(k) == v for k, v in identity.items()) and (
                "channels" not in previous or previous.get("channels") == channels):
            return path
    artifacts.write_json_artifact(path, {
        **identity, "approved_at": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
        "user_confirmation": user_confirmation.strip(),
    })
    return path


def require_startup(job) -> None:
    # Bare state-engine jobs support historical migration/testing. Skill jobs are
    # recognisable even if their context was accidentally lost during bootstrap.
    if not ((job.root / "job-context.json").exists() or (job.root / "00-user-provided").exists()):
        return
    context = _context(job)
    config, digest = _config(job)
    _report(job, context, digest)
    approval = _read(job.job_dir / "manifests/setup-approval.json", "setup confirmation")
    if any(approval.get(k) != v for k, v in _approval_identity(job, context, digest).items()):
        raise WorkflowError("startup config confirmation is stale or belongs to another Job")
    if not isinstance(approval.get("user_confirmation"), str) or not approval["user_confirmation"].strip():
        raise WorkflowError("startup config confirmation is missing")
    # Historical approvals remain valid under their original provider-config
    # binding. New confirmations include channels; do not rewrite old receipts.
    if "channels" in approval and approval.get("channels") != selected_channels(json.loads(config.read_bytes())):
        raise WorkflowError("startup channel confirmation is missing or stale")
