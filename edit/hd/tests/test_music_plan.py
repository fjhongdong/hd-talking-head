"""Music source binding uses the real canonical material index, not mocks."""

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from edit.hd.tools import contract_artifacts, preview_music
from edit.hd.tests.test_preview_music import OPTIONS


def fixture(root):
    root = root.resolve()
    records = []
    for number, kind, name, content in ((1, "audio", "music.wav", b"fixture-audio-identity"),
                                         (2, "documents", "license.txt", b"Test license fixture only")):
        path = root / "00-user-provided" / kind / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        records.append({"asset_id": f"asset-{number:04d}", "material_id": f"material-{number:04d}",
                        "original_name": name, "status": "active", "media_type": kind,
                        "imported_path": path.relative_to(root).as_posix(),
                        "sha256": contract_artifacts.sha256_file(path), "size_bytes": len(content)})
    index = {"schema_version": 1, "job_id": root.name, "material_revision": 0,
             "changes": [], "materials": records, "assets": copy.deepcopy(records)}
    contract_artifacts.write_json_artifact(root / "00-user-provided/material-index.json", index)
    options = {"material_id": records[0]["material_id"], "material_sha256": records[0]["sha256"],
               "license_material_id": records[1]["material_id"], "license_sha256": records[1]["sha256"],
               "title": "Test tone", "author": "Test fixture", "source": "User-provided test fixture",
               "user_confirmation": "测试夹具：同意使用本曲及所附许可，本记录不是生产批准",
               "selection": {"start_frame": 0, "end_frame": 48, "crossfade_frames": 6},
               "mix": copy.deepcopy(OPTIONS)}
    return SimpleNamespace(root=root, job_id="music-test-job"), options, index


class MusicPlanTests(unittest.TestCase):
    def test_unbounded_integer_parameters_are_domain_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            job, options, _ = fixture(Path(temp))
            options["mix"]["music_gain_db"] = 10 ** 1000
            with self.assertRaises(preview_music.MusicError):
                preview_music.plan_music(job, options, frames=144, voice_offset_frames=0)

    def test_plan_binds_music_license_and_final_clock(self):
        with tempfile.TemporaryDirectory() as temp:
            job, options, _ = fixture(Path(temp))
            self.assertTrue(hasattr(preview_music, "plan_music"), "formal music input contract is missing")
            plan = preview_music.plan_music(job, options, frames=144, voice_offset_frames=12)
            self.assertEqual(plan["total_frames"], 144)
            self.assertEqual(plan["body_offset_frames"], 12)
            self.assertEqual(plan["music"]["sha256"], options["material_sha256"])
            self.assertEqual(plan["license"]["sha256"], options["license_sha256"])
            self.assertEqual(plan["job_id"], job.job_id)
            options["mix"]["music_gain_db"] = -40
            self.assertEqual(plan["options"]["mix"]["music_gain_db"], -12)

    def test_changed_or_withdrawn_materials_fail_closed(self):
        self.assertTrue(hasattr(preview_music, "plan_music"))
        for target in (0, 1):
            for mode in ("withdrawn", "changed"):
                with tempfile.TemporaryDirectory() as temp, self.subTest(target=target, mode=mode):
                    job, options, index = fixture(Path(temp))
                    item = index["materials"][target]
                    if mode == "withdrawn":
                        item["status"] = mode
                        contract_artifacts.write_json_artifact(job.root / "00-user-provided/material-index.json", index)
                    else:
                        (job.root / item["imported_path"]).write_bytes(b"changed")
                    with self.assertRaises(preview_music.MusicError):
                        preview_music.plan_music(job, options, frames=144, voice_offset_frames=0)

    def test_missing_confirmation_unknown_fields_and_wrong_kinds_are_rejected(self):
        self.assertTrue(hasattr(preview_music, "plan_music"))
        with tempfile.TemporaryDirectory() as temp:
            job, options, _ = fixture(Path(temp))
            for change in ({"user_confirmation": " "}, {"license_sha256": "bad"},
                           {"source": ""}, {"other": True},
                           {"material_id": options["license_material_id"], "material_sha256": options["license_sha256"]},
                           {"license_material_id": options["material_id"], "license_sha256": options["material_sha256"]}):
                with self.subTest(change=change), self.assertRaises(preview_music.MusicError):
                    preview_music.plan_music(job, {**options, **change}, frames=144, voice_offset_frames=0)
            with self.assertRaises(preview_music.MusicError):
                preview_music.plan_music(job, options, frames=144, voice_offset_frames=True)

    def test_revalidation_rejects_tampering_and_material_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            job, options, index = fixture(Path(temp))
            plan = preview_music.plan_music(job, options, frames=144, voice_offset_frames=12)
            self.assertTrue(hasattr(preview_music, "validate_music_plan"))
            self.assertEqual(preview_music.validate_music_plan(job, plan), plan)
            changed = copy.deepcopy(plan)
            changed["total_frames"] += 1
            with self.assertRaises(preview_music.MusicError):
                preview_music.validate_music_plan(job, changed)
            changed = copy.deepcopy(plan)
            changed["schema_version"] = True
            with self.assertRaises(preview_music.MusicError):
                preview_music.validate_music_plan(job, changed)
            (job.root / index["materials"][1]["imported_path"]).write_bytes(b"updated permission")
            with self.assertRaises(preview_music.MusicError):
                preview_music.validate_music_plan(job, plan)


if __name__ == "__main__":
    unittest.main()
