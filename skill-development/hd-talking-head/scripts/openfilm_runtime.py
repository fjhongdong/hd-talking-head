"""Project-local readiness for the pinned OpenFilm motion-graphics runtime."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

PACKAGE_VERSION = "0.2.4"
RUNTIME_DIR = "openfilm-0.2.4"
PLAYWRIGHT_VERSION = "1.61.1"
PLAYWRIGHT_REVISION = "1228"
SKILL_SHA256 = "64ec633fc49c0e8f1e572d3dfae1b7d0854c4fb89e86706ce915bc818da406aa"
MANUAL_SHA256 = "f92be3da02f1724bbbef3bd70fa01c42b4c24e85aa6987fb8401e501bb61d7b9"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version(executable: str, args: list[str]) -> tuple[int, ...]:
    result = subprocess.run([executable, *args], check=False, capture_output=True,
                            text=True, timeout=20)
    if result.returncode:
        raise ValueError(f"{Path(executable).name} version probe failed")
    import re
    match = re.search(r"(\d+)(?:\.(\d+))(?:\.(\d+))?", result.stdout)
    if not match:
        raise ValueError(f"{Path(executable).name} version is unavailable")
    return tuple(int(value or 0) for value in match.groups())


def _browser(cache: Path) -> Path:
    candidates = (
        cache / f"chromium_headless_shell-{PLAYWRIGHT_REVISION}/chrome-headless-shell-mac-arm64/chrome-headless-shell",
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ValueError(f"Playwright Chromium revision {PLAYWRIGHT_REVISION} is unavailable")


def _browser_candidates(root: Path) -> list[Path]:
    caches = [root / "playwright-browsers"]
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        caches.append(Path(configured).expanduser())
    caches.append(Path.home() / "Library/Caches/ms-playwright")
    return [cache.resolve() for cache in caches]


def check_runtime(project_root: Path, executables=None, browser_cache=None) -> dict[str, str]:
    project = Path(project_root).resolve(strict=True)
    root = project / "skill-development/runtime" / RUNTIME_DIR
    package = root / "node_modules/openfilm/package.json"
    playwright = root / "node_modules/playwright-core/package.json"
    browsers = root / "node_modules/playwright-core/browsers.json"
    cli = root / "node_modules/openfilm/bin/openfilm.mjs"
    manual = root / "node_modules/openfilm/MANUAL.md"
    skill = root / "node_modules/openfilm/skills/motion-graphics/SKILL.md"
    source = root / "node_modules/openfilm/skills/SOURCE"
    for path in (package, playwright, browsers, cli, manual, skill, source):
        if not path.is_file():
            raise ValueError(f"OpenFilm runtime file is missing: {path}")
    package_data = json.loads(package.read_text(encoding="utf-8"))
    if package_data.get("name") != "openfilm" or package_data.get("version") != PACKAGE_VERSION:
        raise ValueError("OpenFilm runtime version changed")
    if (_sha(skill) != SKILL_SHA256 or _sha(manual) != MANUAL_SHA256
            or package_data.get("dependencies", {}).get("playwright-core") != PLAYWRIGHT_VERSION):
        raise ValueError("OpenFilm instructions or native dependency declaration changed")
    playwright_data = json.loads(playwright.read_text(encoding="utf-8"))
    if playwright_data.get("name") != "playwright-core" or playwright_data.get("version") != PLAYWRIGHT_VERSION:
        raise ValueError("OpenFilm Playwright version changed")
    browser_data = json.loads(browsers.read_text(encoding="utf-8"))
    revisions = {item.get("revision") for item in browser_data.get("browsers", [])
                 if item.get("name") in {"chromium", "chromium-headless-shell"}}
    if PLAYWRIGHT_REVISION not in revisions:
        raise ValueError("OpenFilm Playwright browser revision declaration changed")
    tools = {name: (executables[name] if executables else shutil.which(name))
             for name in ("node", "ffmpeg", "ffprobe")}
    node, ffmpeg, ffprobe = (tools[name] for name in ("node", "ffmpeg", "ffprobe"))
    if not node or _version(node, ["--version"]) < (22, 2, 0):
        raise ValueError("OpenFilm requires Node >=22.2")
    if not ffmpeg or not ffprobe:
        raise ValueError("OpenFilm requires ffmpeg and ffprobe")
    browser = None
    cache = None
    for candidate_cache in ([Path(browser_cache)] if browser_cache else _browser_candidates(root)):
        try:
            browser = _browser(candidate_cache)
            cache = candidate_cache
            break
        except ValueError:
            continue
    if browser is None or cache is None:
        raise ValueError(f"Playwright Chromium revision {PLAYWRIGHT_REVISION} is unavailable")
    implementation = tuple(sorted((root / "node_modules/openfilm").rglob("*.mjs")))
    implementation += tuple(sorted((root / "node_modules/openfilm").rglob("*.js")))
    files = (package, playwright, browsers, cli, manual, skill, source, browser,
             Path(node), Path(ffmpeg), Path(ffprobe), *implementation)
    identity = hashlib.sha256(b"\0".join(_sha(path).encode() for path in files)).hexdigest()
    return {"root": str(root), "cli": str(cli), "node": str(Path(node).resolve()),
            "ffmpeg": str(Path(ffmpeg).resolve()), "ffprobe": str(Path(ffprobe).resolve()),
            "browser": str(browser), "browser_cache": str(cache),
            "manual": str(manual), "skill": str(skill), "source": str(source),
            "identity": identity, "version": PACKAGE_VERSION}


def probe_runtime(project_root: Path, runtime: dict[str, str] | None = None) -> dict[str, str]:
    """Load OpenFilm's public modules and perform one bounded native browser launch.

    This is deliberately separate from ``check_runtime``: callers can run it once at
    startup, while per-frame execution remains free of process and browser probes.
    No Studio, asset server, render, provider call, file creation, or installation is
    involved.
    """
    project = Path(project_root).resolve(strict=True)
    info = runtime or check_runtime(project)
    root = Path(info["root"]).resolve(strict=True)
    node = Path(info["node"]).resolve(strict=True)
    browser_cache = Path(info["browser_cache"]).resolve(strict=True)
    if not node.is_file() or not root.is_dir() or not browser_cache.is_dir():
        raise ValueError("OpenFilm runtime probe inputs are unavailable")

    # Use a benign whitelist so provider credentials and unrelated host state never
    # enter the child process or browser environment.
    probe_env = {
        key: os.environ[key] for key in
        ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL") if key in os.environ
    }
    probe_env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    script = r"""
const phase = (name, error) => {
  const detail = error ? String(error?.message || error).split('\n')[0].slice(0, 240) : '';
  console.error(JSON.stringify({phase: name, detail}));
  process.exitCode = 1;
};
try {
  const [{ launch }, renderModule] = await Promise.all([
    import('openfilm/host'),
    import('openfilm/render'),
  ]);
  if (typeof launch !== 'function' || typeof renderModule.render !== 'function') {
    phase('module_load', 'public exports are unavailable');
  } else {
    try {
      const browser = await launch({ headed: false, env: process.env });
      try {
        // Startup only: no project assets, media files, Studio, or render call.
      } finally {
        await browser.close();
      }
      console.log(JSON.stringify({module_load: 'ok', browser_launch: 'ok'}));
    } catch (error) {
      phase('browser_launch', error);
    }
  }
} catch (error) {
  phase('module_load', error);
}
"""
    try:
        result = subprocess.run(
            [str(node), "--input-type=module", "-e", script],
            cwd=root,
            env=probe_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("OpenFilm runtime probe timed out") from error
    if result.returncode:
        detail = (result.stderr.strip().splitlines() or ["probe failed"])[-1][:320]
        raise ValueError(f"OpenFilm runtime probe failed: {detail}")
    try:
        output = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise ValueError("OpenFilm runtime probe returned invalid output") from error
    if output.get("module_load") != "ok" or output.get("browser_launch") != "ok":
        raise ValueError("OpenFilm runtime probe did not complete")
    return {"root": str(root), "node": str(node), "browser": info["browser"],
            "version": info["version"], "status": "ready"}


def prepare_runtime(project_root: Path) -> dict[str, str]:
    project = Path(project_root).resolve(strict=True)
    root = project / "skill-development/runtime" / RUNTIME_DIR
    if root.is_symlink() or not root.resolve().is_relative_to(project):
        raise ValueError("OpenFilm runtime must stay inside the project")
    # The runtime is prepared only when absent. Existing files are never replaced.
    package = root / "node_modules/openfilm/package.json"
    if root.exists() and any(root.iterdir()) and not package.is_file():
        raise ValueError("incomplete OpenFilm runtime directory; no overwrite")
    if not package.is_file():
        root.mkdir(parents=True, exist_ok=True)
        npm = shutil.which("npm")
        if not npm:
            raise ValueError("npm is unavailable; OpenFilm runtime was not installed")
        subprocess.run([npm, "install", "--prefix", str(root), "--global=false", "--no-save",
                        "--package-lock=false", "--ignore-scripts", "--no-audit", "--no-fund",
                        "openfilm@" + PACKAGE_VERSION], check=True, cwd=project, timeout=300)
    try:
        return check_runtime(project)
    except ValueError as error:
        if "Chromium revision" not in str(error):
            raise
        cache = root / "playwright-browsers"
        cache.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(cache)}
        node = shutil.which("node")
        if not node:
            raise ValueError("Node is unavailable; OpenFilm browser was not installed")
        subprocess.run([node, str(root / "node_modules/playwright-core/cli.js"), "install", "chromium"],
                       check=True, cwd=root, env=env, timeout=300)
        return check_runtime(project)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    result = prepare_runtime(args.project_root) if args.prepare else check_runtime(args.project_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
