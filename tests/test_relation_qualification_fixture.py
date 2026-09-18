"""Low-cost checks for the synthetic formal execution fixtures."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_relation_motion_integration import make_brief, create_synthetic_job
from edit.hd.tools import semantic_motion


class RelationQualificationFixtureTests(unittest.TestCase):
    def test_two_cases_change_content_and_bind_real_content_analysis(self):
        first, second = make_brief(2), make_brief(4)
        for key in ("title", "source_ids"):
            self.assertNotEqual(first[key], second[key])
        for key in ("source_text", "subjects"):
            self.assertNotEqual(first["motion"][key], second["motion"][key])
        for brief in (first, second):
            with self.subTest(count=len(brief["source_ids"])), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                source = root / "source.mp4"
                source.write_bytes(b"synthetic test input")
                job = create_synthetic_job(root / "fixture", source, brief)
                report = semantic_motion.plan_motion_for_job(job, brief["motion"])
                self.assertEqual(report["plan"], brief["motion"])
                self.assertTrue((job.job_dir / "SYNTHETIC-QUALIFICATION.json").is_file())

    def test_unqualified_capacity_is_not_silently_changed(self):
        for count in (0, 1, 3, 5):
            with self.assertRaises(ValueError):
                make_brief(count)


if __name__ == "__main__":
    unittest.main()
