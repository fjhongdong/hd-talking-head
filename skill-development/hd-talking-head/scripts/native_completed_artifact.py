"""Reuse a completed native component through the existing safe media snapshot."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat


_REFS = {
    "media": "completed-native-video",
    "original_brief": "original-native-brief",
    "generation_evidence": "native-generation-evidence",
}


def attach_completed(adapter, validate_brief, *, completed_record):
    """Keep native guards; replace generation with an explicit byte-copy invocation.

    The original brief describes the already generated pixels. Only source_binding
    can change when placing those pixels in a new approved composition. This does
    not grant semantic or visual approval to the new use.
    """
    from edit.hd.tools.broll_component_executor import ReferenceProcessMedia

    frozen = json.dumps(completed_record, sort_keys=True, separators=(",", ":"))
    record = json.loads(frozen)
    if (type(record) is not dict or set(record) != {"schema_version", *_REFS}
            or type(record["schema_version"]) is not int or record["schema_version"] != 1
            or adapter.dependency_id not in {"adu-motion-video", "hypit-native-chat"}
            or adapter.media_loader is not None):
        raise ValueError("Invalid completed native artifact record")
    for entry in _REFS:
        item = record[entry]
        if (type(item) is not dict or set(item) != {"job_path", "sha256"}
                or type(item["job_path"]) is not str or not item["job_path"]
                or PurePosixPath(item["job_path"]).is_absolute()
                or any(p in {"", ".", ".."} for p in item["job_path"].split("/"))
                or type(item["sha256"]) is not str
                or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None):
            raise ValueError("Invalid native reuse source reference")
    if len({record[k]["job_path"] for k in _REFS}) != len(_REFS):
        raise ValueError("Native reuse references must be distinct")

    helper = Path(__file__)
    helper_sha = hashlib.sha256(helper.read_bytes()).hexdigest()

    def original_brief(job):
        if hashlib.sha256(helper.read_bytes()).hexdigest() != helper_sha:
            raise ValueError("Native reuse helper changed after binding")
        root = Path(job.job_dir).resolve(strict=True)
        item = record["original_brief"]
        path = root / item["job_path"]
        metadata = path.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or not path.resolve(strict=True).is_relative_to(root)):
            raise ValueError("Native reuse brief is not a private Job file")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Original native brief changed")
        return validate_brief(raw)

    def guard(job, recipe, component):
        # The original native guard still owns plan, recipe, source and runtime.
        payload = adapter.brief_loader(job, recipe, component)
        current = dict(validate_brief(payload))
        original = dict(original_brief(job))
        current.pop("source_binding")
        original.pop("source_binding")
        if current != original:
            raise ValueError("Native reuse cannot change content, layout or clock")
        return payload

    def media_loader(job, recipe, component, payload):
        # execute_component opens and pins all three files, checking their hashes.
        original_brief(job)
        return tuple(ReferenceProcessMedia(media_ref=_REFS[key], **record[key])
                     for key in _REFS)

    record_sha = hashlib.sha256(frozen.encode()).hexdigest()
    return replace(adapter, adapter_id=adapter.adapter_id + "-reuse-" + record_sha[:12],
                   brief_loader=guard, media_loader=media_loader,
                   argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}",
                                  "--output", "{output_path}", "--reuse-media-manifest",
                                  "{media_manifest_fd}"))
