from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from edit.hd.tools import contract_artifacts


class ContractArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_canonical_json_and_hash_are_stable(self) -> None:
        first = {"中文": "内容", "items": [2, 1], "nested": {"b": 2, "a": 1}}
        second = {"nested": {"a": 1, "b": 2}, "items": [2, 1], "中文": "内容"}

        self.assertEqual(
            contract_artifacts.canonical_json_bytes(first),
            contract_artifacts.canonical_json_bytes(second),
        )
        self.assertEqual(
            contract_artifacts.sha256_json(first),
            contract_artifacts.sha256_json(second),
        )

    def test_read_json_rejects_duplicate_keys_nonfinite_and_non_object(self) -> None:
        cases = {
            "duplicate.json": b'{"a":1,"a":2}\n',
            "nan.json": b'{"value":NaN}\n',
            "array.json": b'[]\n',
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(payload)
                with self.assertRaises(contract_artifacts.ContractArtifactError):
                    contract_artifacts.read_json_artifact(path)

    def test_atomic_json_overwrite_matches_file_hash_and_leaves_no_temp(self) -> None:
        path = self.root / "nested" / "record.json"
        contract_artifacts.write_json_artifact(path, {"revision": 1})
        contract_artifacts.write_json_artifact(path, {"revision": 2, "ok": True})

        self.assertEqual(
            contract_artifacts.read_json_artifact(path),
            {"revision": 2, "ok": True},
        )
        self.assertEqual(
            contract_artifacts.sha256_file(path),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])


if __name__ == "__main__":
    unittest.main()
