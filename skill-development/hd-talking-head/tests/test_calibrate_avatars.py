"""Regression tests for per-frame avatar geometry calibration."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Cascade:
    def __init__(self, boxes):
        self.boxes = iter(boxes)

    def detectMultiScale(self, *_args, **_kwargs):
        return [next(self.boxes)]


class _CV2:
    class data:
        haarcascades = "."

    COLOR_BGR2GRAY = 0

    def __init__(self, boxes):
        self.cascade = _Cascade(boxes)

    def CascadeClassifier(self, *_args):
        return self.cascade

    def imread(self, *_args):
        return object()

    def cvtColor(self, *_args):
        return object()

    def equalizeHist(self, *_args):
        return object()


class CalibrateAvatarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibrate = load("calibrate_avatars", ROOT / "scripts/calibrate_avatars.py")
        cls.profile = load("avatar_profile", ROOT / "scripts/avatar_profile.py")

    def _build(self, boxes):
        calls = []
        original = self.calibrate.subprocess.run

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            Path(command[-1]).touch()

        self.calibrate.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as directory:
                value = self.calibrate.build_avatar(
                    _CV2(boxes), self.profile, Path(directory) / "a.mp4",
                    0, 2, "0" * 64,
                )
            self.profile.validate_avatar(value, frames=48)
            return value
        finally:
            self.calibrate.subprocess.run = original

    def test_still_face_passes_real_builder_and_validator(self):
        self._build([(440, 400, 200, 200)] * 3)

    def test_middle_frame_vertical_shift_passes_real_builder_and_validator(self):
        self._build([(440, 400, 200, 200), (440, 430, 200, 200), (440, 400, 200, 200)])


if __name__ == "__main__":
    unittest.main()
