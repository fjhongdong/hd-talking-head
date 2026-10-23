"""An approved render request is not evidence of an already successful process."""
import unittest

from edit.hd.tests.test_broll_component_executor import _code_component, _recipe
from edit.hd.tools.visual_strategy import VisualStrategyError, validate_shot_recipe_v2


class PlannedTemplateInvocationTests(unittest.TestCase):
    def test_planned_binding_does_not_claim_an_exit_code(self):
        component = _code_component(b"synthetic brief")
        component["invocation_record"].update(status="planned", exit_code=None)
        validate_shot_recipe_v2(_recipe([component]))

    def test_planned_binding_cannot_also_claim_success(self):
        component = _code_component(b"synthetic brief")
        component["invocation_record"].update(status="planned", exit_code=0)
        with self.assertRaises(VisualStrategyError):
            validate_shot_recipe_v2(_recipe([component]))

    def test_null_exit_requires_explicit_planned_status(self):
        component = _code_component(b"synthetic brief")
        component["invocation_record"]["exit_code"] = None
        with self.assertRaises(VisualStrategyError):
            validate_shot_recipe_v2(_recipe([component]))
