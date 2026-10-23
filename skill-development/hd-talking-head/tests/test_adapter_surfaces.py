"""Public-surface pinning for the thin wrapper adapters; no runtimes needed.

The four adapters below have no offline validate_brief surface. adapter_kit
refactoring must keep these module-level entrypoint names and identity
constants stable, which is exactly what this file freezes.
"""
import unittest

import _env  # noqa: F401
import official_video_adapter
import paper_collage_adapter
import paper_hyperframes_adapter
import whiteboard_adapter
import motion_graphics_adapter


SURFACES = {
    "official_video_adapter": {"create_adapter"},
    "paper_collage_adapter": {"create_adapter", "create_binding", "create_artifact_probe"},
    "paper_hyperframes_adapter": {"create_adapter", "create_binding"},
    "whiteboard_adapter": {"create_adapter", "create_binding", "create_artifact_probe"},
    "motion_graphics_adapter": {"create_adapter", "create_binding", "create_artifact_probe"},
}


class WrapperAdapterSurfaceTests(unittest.TestCase):
    def test_public_entrypoints_stay_importable_and_named(self):
        for module_name, expected in SURFACES.items():
            module = globals()[module_name]
            with self.subTest(module=module_name):
                for name in expected:
                    self.assertTrue(callable(getattr(module, name, None)),
                                    f"{module_name}.{name} is missing")


if __name__ == "__main__":
    unittest.main()
