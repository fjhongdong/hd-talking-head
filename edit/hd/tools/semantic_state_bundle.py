"""Freeze semantic sources and existing FD/watchdog support without changing old bundles."""
from __future__ import annotations

import base64
import argparse
import os
from pathlib import Path
import sys
import tempfile

if __package__:
    from .relation_motion_bundle import BOOTSTRAP as BROWSER_SUPPORT
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from edit.hd.tools.relation_motion_bundle import BOOTSTRAP as BROWSER_SUPPORT


SOURCES = (
    "semantic_state_cli.py", "semantic_state_pipeline.py", "semantic_state_renderer.cjs",
    "semantic_state_capture.cjs", "relation_motion_maintenance_render.py",
    "relation_browser_watchdog.py", "relation_browser_shim.py",
    "runtime_contracts.py", "semantic_validator.py",
)

SEMANTIC_ENTRY = r'''
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import base64
import json

def parse_runtime_contracts(raw):
    if len(raw.encode("utf-8")) > 65536:
        raise ValueError("runtime contracts too large")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate runtime contract key")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)

def semantic_main():
    parser = argparse.ArgumentParser(description="Frozen semantic-state renderer")
    for key in ("brief", "output", "node", "playwright", "browser", "ffmpeg", "ffprobe"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--runtime-contracts", required=True)
    args = parser.parse_args()
    support = {"__name__": "frozen_browser_support", "FROZEN_SOURCES": FROZEN_SOURCES}
    exec(compile(BROWSER_SUPPORT, "frozen_browser_support.py", "exec"), support)
    target = None
    watchdog = None
    heartbeat = -1
    try:
        source = support["descriptor"](args.brief)
        output = support["descriptor"](args.output)
        original, destination = os.fstat(source), os.fstat(output)
        if (os.path.samestat(original, destination) or destination.st_size != 0
                or original.st_size > 4 * 1024 * 1024
                or fcntl.fcntl(output, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY):
            raise ValueError("invalid input/output descriptors")
        target = output
        runtime = {"__name__": "frozen_runtime_contracts"}
        exec(compile(base64.b64decode(FROZEN_SOURCES["runtime_contracts.py"], validate=True), "runtime_contracts.py", "exec"), runtime)
        contracts = runtime["normalize_contracts"](parse_runtime_contracts(args.runtime_contracts))
        for key, contract in contracts.items():
            if getattr(args, key) != contract["path"]:
                raise ValueError("runtime argument differs from contract: " + key)
            if key in ("node", "ffmpeg", "ffprobe") and contract.get("library_discovery") != "mach_o_static_v1":
                raise ValueError("runtime requires static library discovery: " + key)
        runtime["verify_contracts"](contracts)
        watchdog, heartbeat, ready = support["start_watchdog"](Path(tempfile.gettempdir()).resolve(strict=True))
        root = Path(ready["root"])
        tools = root / "edit" / "hd" / "tools"
        tools.mkdir(parents=True)
        # Close namespace-package fallback into another Agent's project tree.
        for package in (root / "edit", root / "edit" / "hd", tools):
            (package / "__init__.py").write_bytes(b"")
        for name, encoded in FROZEN_SOURCES.items():
            data = base64.b64decode(encoded, validate=True)
            if name == "relation_browser_shim.py":
                data = b"#!" + os.fsencode(sys.executable) + b"\n" + data.split(b"\n", 1)[1]
            (tools / name).write_bytes(data)
        shim = tools / "relation_browser_shim.py"
        shim.chmod(0o700)
        validator = {"__name__": "frozen_snapshot"}
        exec(compile(base64.b64decode(FROZEN_SOURCES["semantic_validator.py"], validate=True), "semantic_validator.py", "exec"), validator)
        executables = {}
        for key in ("node", "ffmpeg", "ffprobe"):
            snapshot = root / key
            validator["_snapshot"](Path(contracts[key]["path"]), snapshot, contracts[key]["sha256"])
            executables[key] = str(snapshot)
        brief = root / "brief.json"
        brief.write_bytes(os.pread(source, original.st_size, 0))
        candidate = root / "candidate.mp4"
        command = [sys.executable, str(tools / "semantic_state_cli.py"),
            "--brief", str(brief), "--output", str(candidate), "--browser", str(shim)]
        for key in ("node", "playwright", "ffmpeg", "ffprobe"):
            command.extend(["--" + key, executables.get(key, getattr(args, key))])
        environment = dict(os.environ, HD_BROWSER_SOCKET=ready["socket"],
            HD_BROWSER_TOKEN=ready["token"], HD_BROWSER_REAL=args.browser,
            HD_RELATION_PARENT_GROUP=str(os.getpgrp()))
        if subprocess.run(command, env=environment, check=False).returncode:
            raise ValueError("semantic renderer failed")
        runtime["verify_contracts"](contracts)
        support["publish"](candidate, target)
        active, active_heartbeat = watchdog, heartbeat
        watchdog, heartbeat = None, -1
        support["stop_watchdog"](active, active_heartbeat)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        if watchdog is not None:
            try:
                support["stop_watchdog"](watchdog, heartbeat)
            except (OSError, RuntimeError) as cleanup:
                error = RuntimeError(str(error) + "; " + str(cleanup))
        try:
            support["rollback"](target)
        except OSError as cleanup:
            error = RuntimeError(str(error) + "; " + str(cleanup))
        print("frozen semantic render failed: " + str(error), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(semantic_main())
'''


def build_bundle() -> bytes:
    """Build deterministic bytes; no registration, filesystem publication or approval."""
    root = Path(__file__).resolve().parent
    sources = {name: (root / name).read_bytes() for name in SOURCES}
    if sources != {name: (root / name).read_bytes() for name in SOURCES}:
        raise ValueError("semantic sources changed during build")
    encoded = {name: base64.b64encode(data).decode("ascii") for name, data in sources.items()}
    return ("FROZEN_SOURCES = " + repr(encoded) + "\nBROWSER_SUPPORT = " + repr(BROWSER_SUPPORT)
            + "\nSEMANTIC_ENTRY = " + repr(SEMANTIC_ENTRY)
            + "\nexec(compile(SEMANTIC_ENTRY, 'semantic_entry.py', 'exec'))\n").encode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = build_bundle()
        with tempfile.NamedTemporaryFile(dir=args.output.parent, prefix=".semantic-bundle-") as staged:
            staged.write(payload)
            staged.flush()
            os.fsync(staged.fileno())
            os.link(staged.name, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, "semantic bundle build failed: " + str(exc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
