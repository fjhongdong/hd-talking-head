import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "skill-development/hd-talking-head/scripts/hyperframes_native_adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("hyperframes_native_adapter_test", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HyperFramesNativeAdapterTest(unittest.TestCase):
    def test_factory_and_schema2_alpha_contract(self):
        adapter = load_adapter()
        created = adapter.create_adapter(ROOT, "/usr/bin/python3", lambda *_: b"")
        self.assertEqual(created.renderer_version, "0.8.167")
        manifest = json.loads((ADAPTER.parents[1] / "references/dependency-manifest.json").read_text())
        registered = next(item for item in manifest["dependencies"] if item["id"] == adapter.DEPENDENCY_ID)
        self.assertEqual(registered["binding_probes"][0]["producer_version"], created.producer_version)
        source = ROOT / "参考项目/B-roll开源方案/hyperframes/registry/components/notification-stack/notification-stack.html"
        record = {"media_ref": "entry", "job_path": "entry.html", "scene_path": "index.html", "sha256": "0" * 64}
        brief = {
            "schema_version": 2,
            "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-1", "start": 0, "end": 1},
            "template_request": {"semantic_family": "thesis", "information_units": 1, "numeric_values": [], "numeric_scale": "not_applicable"},
            "entry": record,
            "assets": [],
            "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 24, "alpha": True},
            "upstream_route": "hyperframes/notification-stack",
            "source_pins": {"route": "hyperframes/notification-stack", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        }
        self.assertTrue(adapter.validate_brief(json.dumps(brief))["composition"]["alpha"])
        brief["composition"]["alpha"] = False
        self.assertFalse(adapter.validate_brief(json.dumps(brief))["composition"]["alpha"])
        for route, relative in (
            ("hyperframes/chat-message", "components/chat-message/chat-message.html"),
            ("hyperframes/screen-flow-carousel", "components/screen-flow-carousel/screen-flow-carousel.html"),
        ):
            source = ROOT / "参考项目/B-roll开源方案/hyperframes/registry" / relative
            brief["upstream_route"] = route
            brief["source_pins"] = {"route": route, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
            self.assertEqual(adapter.validate_brief(json.dumps(brief))["upstream_route"], route)

    def test_unknown_route_is_rejected(self):
        adapter = load_adapter()
        with self.assertRaises(ValueError):
            adapter.validate_brief(json.dumps({"schema_version": 2, "upstream_route": "hyperframes/unknown"}))


if __name__ == "__main__":
    unittest.main()
