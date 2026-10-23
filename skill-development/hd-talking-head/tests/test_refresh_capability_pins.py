"""refresh_capability_pins tool behavior: stale detection, write, refusal."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
TOOL = SKILL / "scripts" / "refresh_capability_pins.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("refresh_capability_pins", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RefreshCapabilityPinsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / "skill-development" / "hd-talking-head"
        self.current = _digest("current adapter bytes")
        self.stale = _digest("old adapter bytes")
        _write(self.skill / "scripts/alpha_adapter.py", "current adapter bytes")
        _write(self.skill / "scripts/beta_adapter.py", "beta bytes")
        index = {
            "schema_version": 2,
            "profiles": [
                {"candidate_id": "a:alpha", "reviewed_sources": {
                    "skill-development/hd-talking-head/scripts/alpha_adapter.py": self.stale}},
                {"candidate_id": "a:beta", "reviewed_sources": {
                    "skill-development/hd-talking-head/scripts/beta_adapter.py": _digest("beta bytes")}},
            ],
        }
        _write(self.skill / "references/motion-capability-index.json",
               json.dumps(index, ensure_ascii=False, indent=2) + "\n")

    def run_tool(self, *flags):
        return subprocess.run([sys.executable, str(TOOL),
                               "--skill-root", str(self.skill), *flags],
                              capture_output=True, text=True, check=False)

    def test_read_only_reports_stale_and_exits_nonzero(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("a:alpha", result.stdout)
        self.assertIn(self.current, result.stdout)
        self.assertNotIn("a:beta", result.stdout)
        original = (self.skill / "references/motion-capability-index.json").read_text()
        self.assertIn(self.stale, original)  # 未写入

    def test_write_repins_only_stale_entries(self):
        result = self.run_tool("--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads((self.skill / "references/motion-capability-index.json").read_text())
        self.assertEqual(data["profiles"][0]["reviewed_sources"]
                         ["skill-development/hd-talking-head/scripts/alpha_adapter.py"],
                         self.current)
        # 未受影响的钉值与文件格式保持不变
        self.assertEqual(data["profiles"][1]["reviewed_sources"]
                         ["skill-development/hd-talking-head/scripts/beta_adapter.py"],
                         _digest("beta bytes"))
        self.assertTrue((self.skill / "references/motion-capability-index.json")
                        .read_text().endswith("}\n"))
        again = self.run_tool()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('"stale_pins": 0', again.stdout)

    def test_same_file_pinned_by_two_profiles_updates_both(self):
        index_path = self.skill / "references/motion-capability-index.json"
        data = json.loads(index_path.read_text())
        data["profiles"].append({"candidate_id": "b:alpha", "reviewed_sources": {
            "skill-development/hd-talking-head/scripts/alpha_adapter.py": self.stale}})
        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        result = self.run_tool("--write")
        self.assertEqual(result.returncode, 0, result.stdout)
        refreshed = json.loads(index_path.read_text())
        for profile in refreshed["profiles"]:
            if not profile["candidate_id"].endswith("alpha"):
                continue
            self.assertEqual(profile["reviewed_sources"]
                             ["skill-development/hd-talking-head/scripts/alpha_adapter.py"],
                             self.current)

    def test_missing_evidence_file_is_an_error_not_a_repin(self):
        (self.skill / "scripts/beta_adapter.py").unlink()
        result = self.run_tool()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing evidence file", result.stderr + result.stdout)

    def test_self_referential_pin_is_rejected(self):
        index_path = self.skill / "references/motion-capability-index.json"
        data = json.loads(index_path.read_text())
        data["profiles"][1]["reviewed_sources"][
            "skill-development/hd-talking-head/references/motion-capability-index.json"] = _digest("x")
        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        result = self.run_tool()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("self-referential pin", result.stderr + result.stdout)

    def test_duplicate_candidate_ids_are_reported_without_blocking(self):
        index_path = self.skill / "references/motion-capability-index.json"
        data = json.loads(index_path.read_text())
        data["profiles"].append({"candidate_id": "a:alpha", "reviewed_sources": {
            "skill-development/hd-talking-head/scripts/beta_adapter.py": _digest("beta bytes")}})
        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        result = self.run_tool()
        self.assertEqual(result.returncode, 1)  # 只有真实 stale,重复仅警告
        self.assertIn("duplicate candidate_id", result.stderr)

    def test_collect_stale_matches_cli(self):
        module = _load_tool()
        index = json.loads((self.skill / "references/motion-capability-index.json").read_text())
        stale = module.collect_stale(self.skill, index)
        self.assertEqual([item["candidate_id"] for item in stale], ["a:alpha"])
        self.assertEqual(stale[0]["current"], self.current)


if __name__ == "__main__":
    unittest.main()
