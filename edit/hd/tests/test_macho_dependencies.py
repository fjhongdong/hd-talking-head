import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from edit.hd.tools import runtime_contracts


class MachODependencyTests(unittest.TestCase):
    def test_recursive_discovery_preserves_load_paths(self):
        self.assertTrue(callable(getattr(runtime_contracts, "discover_macho_libraries", None)), "discovery missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            entry, first, second = [root / name for name in ("entry", "first", "second")]
            for path in (entry, first, second):
                path.write_bytes(path.name.encode())
            alias = root / "current"
            alias.symlink_to(first)
            graph = {entry: [str(alias)], first: [str(second)], second: [str(alias), "/usr/lib/libSystem.B.dylib"]}
            def inspect(path, timeout):
                return str(path) + ":\n" + "".join("\t" + item + " (compatibility version 1.0.0, current version 1.0.0)\n" for item in graph[path])
            with patch.object(runtime_contracts, "_macho_output", side_effect=inspect):
                result = runtime_contracts.discover_macho_libraries(entry)
            self.assertEqual([item["path"] for item in result], [str(first), str(second)])
            self.assertEqual(result[0]["load_paths"], [str(alias)])
            self.assertEqual(result[1]["load_paths"], [str(second)])
            for item in result:
                runtime_contracts._verify_load_paths(item)
                runtime_contracts._verify_file(Path(item["path"]), item["sha256"], False)
            def mutate_during_inspection(path, timeout):
                text = inspect(path, timeout)
                if path == second:
                    first.write_bytes(b"changed")
                return text
            with patch.object(runtime_contracts, "_macho_output", side_effect=mutate_during_inspection):
                with self.assertRaisesRegex(ValueError, "identity"):
                    runtime_contracts.discover_macho_libraries(entry)

    def parse(self, text):
        self.assertTrue(callable(getattr(runtime_contracts, "parse_macho_dependencies", None)),
                        "Mach-O dependency parser missing")
        return runtime_contracts.parse_macho_dependencies(text)

    def test_universal_headers_and_duplicate_dependencies(self):
        text = "/tools/node (architecture x86_64):\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n/tools/node (architecture arm64):\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n\t/libs/codec.dylib (compatibility version 2.0.0, current version 2.1.0)\n"
        self.assertEqual(self.parse(text), ["/libs/codec.dylib", "/usr/lib/libSystem.B.dylib"])

    def test_unresolved_or_malformed_load_commands_rejected(self):
        for path in ("@rpath/lib.dylib", "@loader_path/lib.dylib", "@executable_path/lib.dylib", "relative", "/libs/../lib.dylib"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.parse("/tools/bin:\n\t" + path + " (compatibility version 1.0.0, current version 1.0.0)\n")
        for text in ("", "otool failed", "/tools/bin:\n\tunknown\n", "/tools/bin:\n",
                     "/tools/bin:\n\t/libs/a.dylib (compatibility version ., current version 1..2)\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)
