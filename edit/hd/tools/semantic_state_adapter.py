"""Construct a pinned semantic adapter; registration and approval remain external."""
import hashlib
import json
import os
from pathlib import Path

from .broll_component_executor import ReferenceProcessAdapter
from .semantic_state_binding import bind_brief
from .runtime_contracts import normalize_contracts, verify_contracts

DEPENDENCY_ID = "hd-talking-head-semantic-state"
VERSION = "1.0.0"
TOOLS = frozenset(("python", "node", "playwright", "browser", "ffmpeg", "ffprobe"))


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def create_adapter(*, dependency_root, entrypoint, entrypoint_sha256, tools, tool_hashes, brief_loader, runtime_contracts,
                   qualification_registry_path=None, qualification_registry_sha256=None):
    root = Path(dependency_root).resolve(strict=True)
    relative = Path(entrypoint)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != entrypoint:
        raise ValueError("invalid semantic entrypoint")
    entry = (root / relative).resolve(strict=True)
    if root not in entry.parents or not entry.is_file() or _sha(entry) != entrypoint_sha256:
        raise ValueError("semantic entrypoint identity mismatch")
    if set(tools) != TOOLS or set(tool_hashes) != TOOLS or not callable(brief_loader):
        raise ValueError("semantic dependency contract incomplete")
    paths = {key: Path(path).resolve(strict=True) for key, path in tools.items()}
    hashes = dict(tool_hashes)
    contracts = normalize_contracts(runtime_contracts)
    for key, contract in contracts.items():
        if contract["path"] != str(paths[key]):
            raise ValueError("semantic runtime path mismatch: " + key)
        if key in ("node", "ffmpeg", "ffprobe") and (contract["sha256"] != hashes[key]
                or contract.get("library_discovery") != "mach_o_static_v1"):
            raise ValueError("semantic runtime file contract mismatch: " + key)
    encoded_contracts = json.dumps(contracts, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded_contracts.encode("utf-8")) > 65536:
        raise ValueError("semantic runtime contract too large")

    def check_dependencies():
        if json.dumps(contracts, ensure_ascii=True, sort_keys=True, separators=(",", ":")) != encoded_contracts:
            raise ValueError("semantic runtime contract changed after construction")
        if _sha(entry) != entrypoint_sha256:
            raise ValueError("semantic entrypoint changed")
        for key, path in paths.items():
            if not path.is_file() or (key != "playwright" and not os.access(path, os.X_OK)) or _sha(path) != hashes[key]:
                raise ValueError("semantic dependency identity mismatch: " + key)
        verify_contracts(contracts)

    check_dependencies()

    def guarded_loader(job, recipe, component):
        check_dependencies()
        payload = brief_loader(job, recipe, component)
        recipe, component = json.loads(json.dumps(recipe)), json.loads(json.dumps(component))
        bound = bind_brief(job, payload, node_executable=paths["node"], node_sha256=hashes["node"],
                           template_id=component.get("template_id"))
        invocation = component.get("invocation_record")
        if type(invocation) is not dict or any(invocation.get(key) != bound[key]
            for key in ("semantic_motion", "template_request")):
            raise ValueError("semantic invocation differs from current approved binding")
        value = json.loads(payload)
        canvas = value["canvas"]
        window, contract = component.get("render_window"), component.get("artifact_contract")
        if (recipe.get("canvas") != {key: canvas[key] for key in ("width", "height", "fps")}
                or type(window) is not dict or type(window.get("start_frame")) is not int
                or type(window.get("end_frame")) is not int
                or window["end_frame"] - window["start_frame"] != canvas["duration_in_frames"]
                or type(contract) is not dict or any(contract.get(key) != expected
                    for key, expected in (("width",1080),("height",1920),("fps",24),("alpha",False)))):
            raise ValueError("semantic canvas or render window mismatch")
        check_dependencies()
        return payload

    argv = ["{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--output", "{output_path}"]
    for key in ("node", "playwright", "browser", "ffmpeg", "ffprobe"):
        argv.extend(["--" + key, str(paths[key])])
    argv.extend(["--runtime-contracts", encoded_contracts])
    return ReferenceProcessAdapter(adapter_id="native-semantic-state-v1", dependency_id=DEPENDENCY_ID,
        approved_executor="reference_adapter", dependency_root=root, entrypoint=entrypoint,
        entrypoint_sha256=entrypoint_sha256, producer_version=VERSION, primary_renderer="SemanticState",
        renderer_version=VERSION, artifact_media_type="video", launcher=paths["python"],
        launcher_sha256=hashes["python"], argv_template=tuple(argv), brief_loader=guarded_loader,
        self_contained_wrapper=True, timeout_seconds=300, runtime_contracts=contracts,
        qualification_registry_path=qualification_registry_path,
        qualification_registry_sha256=qualification_registry_sha256)
