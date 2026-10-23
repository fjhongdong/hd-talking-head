import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class SemanticValidatorTests(unittest.TestCase):
    def test_execution_uses_snapshots_after_sources_are_replaced(self):
        from edit.hd.tools import semantic_validator as module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            renderer, node = root / "renderer", root / "node"
            renderer.write_bytes(b"original renderer")
            node.write_text("#!" + sys.executable + "\nimport sys\nprint(open(sys.argv[1]).read(),end='')\n")
            node.chmod(0o700)
            node_sha = hashlib.sha256(node.read_bytes()).hexdigest()
            renderer_sha = hashlib.sha256(renderer.read_bytes()).hexdigest()
            original = module.subprocess.Popen
            def replace_and_launch(*args, **kwargs):
                renderer.write_bytes(b"replacement renderer")
                node.write_text("#!/bin/sh\nexit 42\n")
                return original(*args, **kwargs)
            with patch.object(module.subprocess, "Popen", side_effect=replace_and_launch):
                self.assertEqual(module.validate_bytes(b"{}", node_executable=node, node_sha256=node_sha,
                    renderer=renderer, renderer_sha256=renderer_sha), b"original renderer")

    def test_identity_and_output_limits(self):
        name = "edit.hd.tools.semantic_validator"
        self.assertIsNotNone(importlib.util.find_spec(name), "bounded validator missing")
        module = importlib.import_module(name)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            renderer = root / "renderer.js"
            renderer.write_bytes(b"fixture")
            executable = root / "fake-node"
            for mode in ("echo", "flood", "wrong_hash"):
                with self.subTest(mode=mode):
                    executable.write_text("#!" + sys.executable + "\nimport sys\n" +
                        ("sys.stdout.write('x' * 1100000)\n" if mode == "flood" else
                         "sys.stdout.buffer.write(sys.stdin.buffer.read())\n"))
                    executable.chmod(0o700)
                    identity = hashlib.sha256(executable.read_bytes()).hexdigest()
                    kwargs = dict(node_executable=executable,
                        node_sha256="0" * 64 if mode == "wrong_hash" else identity,
                        renderer=renderer, renderer_sha256=hashlib.sha256(renderer.read_bytes()).hexdigest())
                    if mode == "echo":
                        self.assertEqual(module.validate_bytes(b"{}", **kwargs), b"{}")
                    else:
                        with self.assertRaisesRegex(ValueError, "limit|identity"):
                            module.validate_bytes(b"{}", **kwargs)
