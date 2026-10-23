from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import user_materials


class UserMaterialBridgeTests(unittest.TestCase):
    def test_plan_and_apply_delegate_to_the_one_canonical_skill(self) -> None:
        lifecycle = mock.Mock()
        lifecycle.plan_material_change.return_value = {"plan_hash": "a" * 64}
        lifecycle.apply_material_change.return_value = {"phase": "workflow_revised"}
        job = SimpleNamespace(root="/tmp/managed-job")

        with mock.patch.object(user_materials, "_lifecycle_module", return_value=lifecycle):
            plan = user_materials.plan_material_change(
                job, "replace", operation_id="replace-1",
                source="/tmp/new.png", material_id="material-0003",
            )
            result = user_materials.apply_material_change(
                job, plan, confirmed_plan_hash="a" * 64,
            )

        lifecycle.plan_material_change.assert_called_once_with(
            "/tmp/managed-job", "replace", operation_id="replace-1",
            source="/tmp/new.png", material_id="material-0003",
        )
        lifecycle.apply_material_change.assert_called_once_with(
            "/tmp/managed-job", plan, confirmed_plan_hash="a" * 64,
        )
        self.assertEqual(result, {"phase": "workflow_revised"})

    def test_active_lookup_uses_the_same_bridge(self) -> None:
        lifecycle = mock.Mock()
        lifecycle.require_active_material.return_value = {"material_id": "material-0003"}
        job = SimpleNamespace(root="/tmp/managed-job")
        with mock.patch.object(user_materials, "_lifecycle_module", return_value=lifecycle):
            result = user_materials.require_active_material(
                job, "material-0003", "b" * 64,
            )
        lifecycle.require_active_material.assert_called_once_with(
            "/tmp/managed-job", "material-0003", "b" * 64,
        )
        self.assertEqual(result["material_id"], "material-0003")


if __name__ == "__main__":
    unittest.main()
