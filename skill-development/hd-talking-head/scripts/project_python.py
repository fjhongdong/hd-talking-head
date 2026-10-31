#!/usr/bin/env python3
"""Prepare project-local Python packages and run with the selected interpreter."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dependency_preflight import _atomic_write_json, _check_binding_probe, _check_python_module, _load_manifest, _probe_failure
from verify_skill_release import verify_release


def project_environment(project: Path) -> tuple[dict[str, str], Path]:
    packages = project / "skill-development/runtime" / (
        f"talking-head-python{sys.version_info.major}{sys.version_info.minor}"
    )
    paths = [str(project), str(Path(__file__).resolve().parent), str(packages)]
    manifest = _load_manifest(Path(__file__).resolve().parents[1] / "references/dependency-manifest.json")
    binaries = [str(_node_tool_directory(project, entry["node_tool"]) / "node_modules/.bin")
                for entry in manifest.get("preparation", []) if "node_tool" in entry]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(dict.fromkeys(paths)),
            "PATH": os.pathsep.join([*binaries, os.environ.get("PATH", "")])}, packages


def _node_tool_directory(project: Path, tool: dict) -> Path:
    return project / "skill-development/runtime" / (tool["package"] + "-" + tool["version"])


def _run_preparation(command: list[str], *, environment: dict[str, str], record: dict,
                     timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    record.update(command=command, returncode=None)
    try:
        result = subprocess.run(command, env=environment, cwd=cwd, capture_output=True,
                                text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        record.update(error_type="TimeoutExpired", timeout_seconds=timeout)
        raise
    except OSError as exc:
        record.update(error_type=type(exc).__name__, errno=exc.errno)
        raise
    record["returncode"] = result.returncode
    if result.returncode:
        record.update(_probe_failure(result))
        required = re.search(r"Hypit requires (?:pnpm [0-9.]+|Node >=[0-9.]+(?: and pnpm [0-9.]+)?)",
                             result.stderr or "")
        npm_code = re.search(r"npm (?:error|ERR!) code (E[A-Z0-9_]+)", result.stderr or "")
        if required:
            record["detail"] = required.group(0)
        elif npm_code:
            record["error_code"] = npm_code.group(1)
        raise RuntimeError(f"preparation command failed (exit {result.returncode}); stopped; no automatic retry")
    return result


def prepare_node_tool(project: Path, tool: dict, environment: dict[str, str], record: dict) -> None:
    target = _node_tool_directory(project, tool)
    if target.resolve() != target.absolute() or not target.resolve().is_relative_to(project):
        raise RuntimeError("Node tool directory must be a regular project-local path")
    metadata = target / "node_modules" / tool["package"] / "package.json"
    executable = target / "node_modules/.bin" / tool["package"]
    record.update(package=tool["package"], version=tool["version"], directory=str(target), commands=[])
    if not metadata.is_file():
        if target.exists() and any(target.iterdir()):
            raise RuntimeError("incomplete local Node tool directory; no overwrite")
        npm = shutil.which("npm", path=environment.get("PATH"))
        if not npm:
            raise RuntimeError("npm is unavailable; local Node tool not installed")
        command_record = {}
        record["commands"].append(command_record)
        _run_preparation([npm, "install", "--prefix", str(target), "--global=false", "--no-save",
                          "--package-lock=false", "--ignore-scripts", "--no-audit", "--no-fund",
                          "--registry=https://registry.npmjs.org", tool["package"] + "@" + tool["version"]],
                         environment=environment, record=command_record, timeout=300, cwd=project)
        record["installed"] = True
    else:
        record["installed"] = False
    actual = json.loads(metadata.read_text(encoding="utf-8"))
    if actual.get("name") != tool["package"] or actual.get("version") != tool["version"]:
        raise RuntimeError("project-local Node tool version changed; no reinstall")
    command_record = {}
    record["commands"].append(command_record)
    result = _run_preparation([str(executable), "--version"], environment=environment,
                              record=command_record, timeout=20)
    if result.stdout.strip() != tool["version"]:
        raise RuntimeError("project-local Node tool version probe disagrees")
    record["status"] = "ready"


def prepare_packages(manifest: dict, environment: dict[str, str], packages: Path,
                     command_log: list | None = None) -> dict:
    dependencies = [item for item in manifest["dependencies"] if item["kind"] == "python_module" and item.get("required")]
    checks = []
    for item in dependencies:
        checks.append(_check_python_module(item, env=environment))
    failures = [(item["id"], check) for item, check in zip(dependencies, checks)
                if check["status"] not in {"callable", "missing"}]
    if failures:
        raise RuntimeError("installed package cannot import; no reinstall: " + json.dumps(failures))
    missing = [item["install"]["package"] + "==" + item["install"]["version"]
               for item, check in zip(dependencies, checks) if check["status"] == "missing"]
    first_opencv_install = any(item['target'] == 'cv2'
        and item.get('install', {}).get('package') == 'opencv-python-headless' and check['status'] == 'missing'
        for item, check in zip(dependencies, checks))
    if missing:
        constraints = [check["distribution"] + "==" + check["distribution_version"]
                       for check in checks if check["status"] == "callable" and check.get("distribution_version")]
        with tempfile.TemporaryDirectory(prefix=".python-prepare-", dir=packages.parent) as temporary:
            path = Path(temporary) / "constraints.txt"
            path.write_text("\n".join(constraints) + "\n", encoding="utf-8")
            record = {}
            if command_log is not None:
                command_log.append(record)
            _run_preparation([
                sys.executable, "-m", "pip", "install", "--only-binary=:all:",
                "--disable-pip-version-check", "--no-input", "--constraint", str(path),
                "--target", str(packages), *missing,
            ], environment=environment, record=record, timeout=300)
        # Refresh in new processes. Do not mistake pip's exit code for usable imports.
        checks = []
        for item in dependencies:
            checked = _check_python_module(item, env=environment,
                initial_install=first_opencv_install and item['target'] == 'cv2'
                    and item.get('install', {}).get('package') == 'opencv-python-headless')
            if checked["status"] != "callable":
                raise RuntimeError(f"post-install import failed: {item['target']}: "
                                   + json.dumps(checked) + "; no automatic retry")
            checks.append(checked)
    safe_fields = {"status", "module", "python_executable", "version", "resolved_path",
                   "distribution", "distribution_version", "probe_stage", "probe_stage_seconds",
                   "probe_candidate_path", "probe_loaded_path", "probe_elapsed_seconds",
                   "probe_context", "probe_timeout_seconds"}
    return {"status": "ready", "installed": missing, "package_directory": str(packages),
            "checks": [{key: value for key, value in checked.items() if key in safe_fields}
                       for checked in checks]}


def preparation_selection(manifest: dict, selected_dependencies: set[str]) -> tuple[list[dict], list[dict]]:
    """Select setup actions from the same dependency IDs used by recipe probes."""
    known = {item.get("selection", {}).get("equals") for item in manifest["dependencies"]
             if item.get("selection", {}).get("component_kind") == "code_generated"} - {"*"}
    if selected_dependencies - known:
        raise ValueError("Unknown selected dependencies: " + ", ".join(sorted(selected_dependencies - known)))
    required = {item["id"] for item in manifest["dependencies"] if item.get("required")}
    entries = [entry for entry in manifest.get("preparation", [])
               if (bool(set(entry["dependency_ids"]) & selected_dependencies)
                   if "dependency_ids" in entry else entry["id"] in required)]
    checks = [item for item in manifest["dependencies"]
              if item["id"] in manifest.get("runtime_checks", [])
              and (item["id"] in required or item.get("selection", {}).get("equals") in selected_dependencies)]
    return entries, checks


def prepare_environment(project: Path, environment: dict[str, str], packages: Path,
                        selected_dependencies: set[str] | None = None,
                        selected_bindings: list[dict] | None = None) -> dict:
    skill = Path(__file__).resolve().parents[1]
    release = verify_release(skill)
    if release["status"] != "pass":
        raise RuntimeError("Skill release check failed; no installation attempted")
    manifest = _load_manifest(skill / "references/dependency-manifest.json")
    entries, checks = preparation_selection(manifest, set(selected_dependencies or ()))
    from edit.hd.tools.startup import assert_project_origin
    assert_project_origin(project)
    if packages.resolve() != packages.absolute() or not packages.resolve().is_relative_to(project):
        raise RuntimeError("Python package directory must be a regular project-local path")
    packages.parent.mkdir(parents=True, exist_ok=True)
    lock_path = packages.parent / ("." + packages.name + ".prepare.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    report = {"status": "preparing", "checked_at": datetime.now(timezone.utc).isoformat(),
              "python_executable": sys.executable, "package_directory": str(packages), "preparation": [],
              "runtime_checks": [], "commands": []}
    report_path = packages.parent / (packages.name + "-prepare.json")
    with os.fdopen(descriptor, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            from prepare_sources import prepare_sources
            report["sources"] = prepare_sources(project)
            report["python_packages"] = prepare_packages(manifest, environment, packages, report["commands"])
            native_environment = {key: value for key, value in environment.items()
                                  if key not in {"PYTHONPATH", "PYTHONHOME"}}
            for entry in entries:
                record = {"id": entry["id"]}
                report["preparation"].append(record)
                if "node_tool" in entry:
                    record["node_tool"] = {}
                    prepare_node_tool(project, entry["node_tool"], native_environment, record["node_tool"])
                _run_preparation([
                    sys.executable, str(skill / entry["script"]), "--project-root", str(project), *entry["arguments"],
                ], environment=native_environment, record=record, timeout=600)
            for item in checks:
                base = project if item["kind"] == "project_path" else project / "参考项目/B-roll开源方案"
                dependency_root = (base / item["target"]).resolve()
                bindings = ([binding for binding in selected_bindings
                             if binding["dependency_id"] == item["selection"]["equals"]]
                            if selected_bindings is not None else [
                    {"entrypoint": probe["entrypoint"], "producer_version": probe["producer_version"],
                     "dependency_id": item["selection"]["equals"],
                     "executor": probe["adapter_identity"]["approved_executor"],
                     "primary_renderer": probe["adapter_identity"]["primary_renderer"]}
                    for probe in item["binding_probes"]])
                for binding in bindings:
                    checked = _check_binding_probe(item, binding,
                        project_root=project, reference_root=project / "参考项目/B-roll开源方案",
                        dependency_root=dependency_root, env=environment)
                    report["runtime_checks"].append({"id": item["id"], "entrypoint": binding["entrypoint"],
                                                     "status": "callable" if checked["status"] == "bound" else checked["status"]})
                    if checked["status"] != "bound":
                        raise RuntimeError(f"runtime check failed: {item['id']}: " + json.dumps(checked))
            report["status"] = "ready"
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            report.update(status="failed", failure=str(exc))
            raise
        finally:
            if report_path.is_file():
                previous = json.loads(report_path.read_text(encoding="utf-8"))
                if previous.get("status") == "failed":
                    previous_path = report_path.with_name(report_path.stem + "-failed-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
                    _atomic_write_json(previous_path, previous)
            _atomic_write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path,
                        default=Path(__file__).resolve().parents[3])
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--dependency-id", action="append", default=[],
                        help="Prepare an optional selected dependency (repeatable)")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    project = args.project_root.expanduser().resolve()
    if any(not (project / "edit/hd/tools" / name).is_file()
           for name in ("state.py", "startup.py", "segment_render.py")):
        parser.error("project root has no full-v2 state engine")
    environment, packages = project_environment(project)
    if args.prepare:
        try:
            sys.path.insert(0, str(project))
            print(json.dumps(prepare_environment(project, environment, packages,
                set(args.dependency_id)), ensure_ascii=False), flush=True)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if command:
        os.execve(sys.executable, [sys.executable, *command], environment)
    elif not args.prepare:
        parser.error("provide a Python entrypoint after --, or use --prepare")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
