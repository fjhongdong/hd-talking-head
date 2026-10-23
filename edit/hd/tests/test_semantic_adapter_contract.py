"""Knowing a renderer must never grant an unreviewed template qualification."""
import unittest
from unittest import mock

from edit.hd.tools import broll_component_executor as executor
from edit.hd.tools.visual_plan import _load_router_module


class SemanticAdapterContractTests(unittest.TestCase):
    def test_native_engine_is_known_without_granting_qualification(self):
        dependency = "hd-talking-head-semantic-state"
        self.assertEqual(executor._DEPENDENCY_CONTRACTS.get(dependency),
                         ("reference_adapter", "SemanticState"))
        router = _load_router_module()
        self.assertEqual(router._executor("code_generated", {"dependency_id": dependency}), "reference_adapter")
        router._validate_renderer_binding(dependency, "SemanticState")
        with self.assertRaises(router.RouterError):
            router._validate_renderer_binding(dependency, "HyperFrames")
        component = {"dependency_id": dependency, "primary_renderer": "SemanticState",
            "entrypoint": "scripts/semantic_state_renderer_bundle.py", "template_origin": "verified_local_canonical",
            "invocation_record": {"argv": ["python3", "scripts/semantic_state_renderer_bundle.py"]}}
        record = {"render_contract": {"engine": "SemanticState"}, "upstream": {"project": dependency}}
        with mock.patch.object(router, "_registered_template", return_value=record) as lookup:
            router._validate_code_cross_fields(component)
            lookup.assert_called_once_with(component, None)
        with mock.patch.object(router, "_registered_template", side_effect=router.RouterError("unqualified")):
            with self.assertRaisesRegex(router.RouterError, "unqualified"):
                router._validate_code_cross_fields(component)
        for origin in ("custom_fallback", "verified_third_party", None):
            with self.subTest(origin=origin), self.assertRaises(router.RouterError):
                router._validate_code_cross_fields({**component, "template_origin": origin})
        with self.assertRaises(executor.BrollComponentExecutionError):
            executor._validate_code_adapter(object(), {"dependency_id": dependency})
