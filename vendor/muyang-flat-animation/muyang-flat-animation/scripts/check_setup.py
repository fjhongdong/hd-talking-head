#!/usr/bin/env python3
import importlib.metadata
import os
import shutil
import sys
from pathlib import Path

def version_tuple(value):
    parts = []
    for token in value.split(".")[:3]:
        digits = "".join(c for c in token if c.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (3 - len(parts)))

missing = []
if sys.version_info < (3, 10):
    missing.append("Python >= 3.10")
if not os.environ.get("GEMINI_API_KEY") and os.name == "nt":
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            user_key, _ = winreg.QueryValueEx(key, "GEMINI_API_KEY")
            if user_key:
                os.environ["GEMINI_API_KEY"] = user_key
    except OSError:
        pass
if not os.environ.get("GEMINI_API_KEY"):
    missing.append("GEMINI_API_KEY")
for executable in ("ffmpeg", "ffprobe"):
    if not shutil.which(executable):
        missing.append(executable)
venv_python = Path(__file__).resolve().parents[2] / ".gemini-venv" / "Scripts" / "python.exe"
try:
    if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
        result = __import__("subprocess").run(
            [str(venv_python), "-c", "import importlib.metadata; print(importlib.metadata.version('google-genai'))"],
            check=True, capture_output=True, text=True
        )
        installed = result.stdout.strip()
    else:
        installed = importlib.metadata.version("google-genai")
    if version_tuple(installed) < (2, 10, 0):
        missing.append(f"google-genai >= 2.10.0 (installed {installed})")
except importlib.metadata.PackageNotFoundError:
    missing.append("google-genai >= 2.10.0")

if missing:
    print("Missing requirements:")
    for item in missing:
        print(f"- {item}")
    raise SystemExit(1)
print("Setup OK: Gemini key is present; Python, google-genai, ffmpeg and ffprobe are available.")
