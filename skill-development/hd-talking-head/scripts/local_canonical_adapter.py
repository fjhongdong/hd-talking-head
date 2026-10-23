"""Bind one registered local-canonical composition to the HD executor."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
ENTRY = "scripts/local_canonical_renderer.cjs"
DEPENDENCY_ID = "hd-talking-head-local-canonical"
VERSION = json.loads((SKILL / "package.json").read_text(encoding="utf-8"))["version"]
DEFAULT_REGISTRY = "references/verified-template-registry.json"
PROVENANCE = (
    "template_origin", "template_id", "template_version", "verification_id",
    "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
    "semantic_families", "capacity",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _registry_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("registry_path must be a POSIX path inside the Skill")
    resolved = (SKILL / relative).resolve(strict=True)
    if SKILL.resolve() not in resolved.parents:
        raise ValueError("registry_path escapes the Skill")
    return resolved


def _validate(node: Path, payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes or len(payload) > 4 * 1024 * 1024:
        raise ValueError("brief must be at most 4 MiB of UTF-8 JSON bytes")
    result = subprocess.run(
        [str(node), str(SKILL / ENTRY), "--validate"], input=payload,
        capture_output=True, timeout=10, check=False, cwd="/",
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace")[:2000])
    return json.loads(result.stdout)


def create_adapter(
    *, composition_id: str, runtime_root, node_executable, browser_executable,
    brief_loader, registry_path: str = DEFAULT_REGISTRY,
):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter

    runtime = Path(runtime_root).resolve(strict=True)
    node = Path(node_executable).resolve(strict=True)
    browser = Path(browser_executable).resolve(strict=True)
    registry = _registry_path(registry_path)
    for executable in (node, browser):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"missing executable dependency: {executable}")
    package = json.loads((runtime / "packages/cli/package.json").read_text())
    renderer_version = package.get("version")
    if package.get("name") != "@hyperframes/cli" or not renderer_version:
        raise ValueError("runtime_root is not a HyperFrames checkout")

    def guarded_loader(job, recipe, component):
        payload = brief_loader(job, recipe, component)
        checked = _validate(node, payload)
        if checked["composition_id"] != composition_id:
            raise ValueError("actual brief composition differs from the approved adapter")
        request = json.loads(json.dumps(component["invocation_record"]["template_request"]))
        if checked["template_request"] != request:
            raise ValueError("actual brief differs from the frozen template_request")
        canvas = checked["canvas"]
        window = component["render_window"]
        if (
            canvas["duration_in_frames"] != window["end_frame"] - window["start_frame"]
            or any(canvas[key] != recipe["canvas"][key] for key in ("width", "height", "fps"))
            or component["artifact_contract"]["alpha"]
        ):
            raise ValueError("actual brief differs from the approved opaque render window/canvas")
        return payload

    registry_sha = _sha(registry)
    return ReferenceProcessAdapter(
        adapter_id=f"local-canonical-{composition_id}-v1",
        dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter",
        dependency_root=SKILL,
        entrypoint=ENTRY,
        entrypoint_sha256=_sha(SKILL / ENTRY),
        producer_version=VERSION,
        primary_renderer="HyperFrames",
        renderer_version=renderer_version,
        artifact_media_type="video",
        launcher=node,
        launcher_sha256=_sha(node),
        brief_loader=guarded_loader,
        self_contained_wrapper=True,
        timeout_seconds=300,
        argv_template=(
            "{launcher}", "{entrypoint}", "--brief", "{brief_path}",
            "--output", "{output_path}", "--runtime-root", str(runtime),
            "--browser", str(browser), "--skill-root", str(SKILL),
            "--registry-path", registry_path, "--registry-sha256", registry_sha,
            "--renderer-version", renderer_version,
        ),
        qualification_registry_path=(
            None if registry_path == DEFAULT_REGISTRY else registry_path
        ),
        qualification_registry_sha256=(
            None if registry_path == DEFAULT_REGISTRY else registry_sha
        ),
    )


def create_binding(
    adapter, brief_bytes: bytes, *, composition_id: str,
    registry_path: str = DEFAULT_REGISTRY,
) -> dict[str, object]:
    """Build a planned local-canonical provenance binding."""
    checked = _validate(adapter.launcher, brief_bytes)
    if checked["composition_id"] != composition_id:
        raise ValueError("brief composition differs from requested composition")
    registry = json.loads(_registry_path(registry_path).read_text(encoding="utf-8"))
    matches = [
        item for item in registry["templates"]
        if item.get("render_contract", {}).get("composition_id") == composition_id
        and item.get("template_origin") == "verified_local_canonical"
    ]
    if len(matches) != 1:
        raise ValueError("composition is not uniquely registered as local canonical")
    template = matches[0]
    return {
        **{key: template[key] for key in PROVENANCE},
        "producer_type": "dependency",
        "dependency_id": adapter.dependency_id,
        "entrypoint": adapter.entrypoint,
        "producer_version": adapter.producer_version,
        "primary_renderer": adapter.primary_renderer,
        "renderer_version": adapter.renderer_version,
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {
            "argv": ["node", adapter.entrypoint],
            "status": "planned",
            "exit_code": None,
            "template_request": checked["template_request"],
        },
    }


def create_artifact_probe(*, ffprobe_executable):
    """Use the already hardened native 9:16 HyperFrames media probe."""
    from hyperframes_chatgpt_exchange_adapter import create_artifact_probe as factory

    return factory(ffprobe_executable=ffprobe_executable)
