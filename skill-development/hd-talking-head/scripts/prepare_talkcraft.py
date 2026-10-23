"""Restore bundled TalkCraft dependencies and check the existing runtime contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile


def prepare(project: Path) -> dict:
    root = project / "edit/hd/integrations/talkcraft"
    manifest = json.loads((project / "runtime-archives/talkcraft.json").read_text())
    if (sys.platform, platform.machine()) != (manifest["platform"], manifest["machine"]):
        raise RuntimeError("This bundled TalkCraft runtime requires macOS arm64")
    for entry in manifest["archives"]:
        target = project / entry["target"]
        if target.exists():
            continue
        with tempfile.TemporaryDirectory(prefix="hd-talkcraft-") as temporary:
            archive = Path(temporary) / "modules.tar.gz"
            digest = hashlib.sha256()
            with archive.open("wb") as output:
                for part in entry["parts"]:
                    with (project / part).open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                            output.write(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise RuntimeError("Bundled TalkCraft dependency archive changed")
            unpacked = Path(temporary) / "unpacked"
            unpacked.mkdir()
            with tarfile.open(archive) as bundle:
                if any(not Path(item.name).parts or Path(item.name).parts[0] != "node_modules"
                       for item in bundle.getmembers()):
                    raise RuntimeError("Unexpected TalkCraft dependency path")
                bundle.extractall(unpacked, filter="data")
            shutil.copytree(unpacked / "node_modules", target, symlinks=True)
    result = subprocess.run([sys.executable, str(root / "check_runtime.py")],
                            check=True, capture_output=True, text=True, timeout=60)
    subprocess.run(["node", "-e",
        "const {createRequire}=require('node:module');"
        "const req=createRequire(process.argv[1]);"
        "req('@remotion/renderer').ensureBrowser({logLevel:'error'}).catch(e=>{console.error(e.message);process.exit(1)});",
        str(root / "runtime/package.json")], cwd=project, check=True, timeout=300)
    return json.loads(result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path,
                        default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    print(json.dumps(prepare(args.project_root.resolve()), ensure_ascii=False))
