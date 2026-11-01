#!/usr/bin/env python3
"""Generate one illustrative image with the Codex CLI's built-in image tool (image_gen).

Optional helper for this style's "illustrative plates" (STYLE.md §10). It needs the `codex`
CLI installed and signed in to an account that can generate images. Without it, generate the
plates with any other image tool from the prompts in tools/gen_plates.sh and save them as
assets/plates/<name>.jpg yourself.

What it does:
- sends the prompt to `codex exec` on stdin, with an instruction to call image_gen once and
  run nothing else (read-only sandbox);
- waits for the result: depending on the Codex version the image is written under
  $CODEX_HOME/generated_images/<thread>/ or embedded (base64) in the session log under
  $CODEX_HOME/sessions/; the script looks in both and saves the newest image of this run;
- with --aspect, checks the width:height of the result (5 % tolerance) and retries once.

Usage:
    gen_image.py "<prompt>" [--aspect 16:9] [--out gen] [--name plate_x] [--timeout 480] [--retries 1]
Prints the saved path on success. Exit codes: 0 ok · 2 no image · 3 wrong aspect · 4 setup problem.
"""
import argparse, base64, glob, json, os, signal, subprocess, sys, time
from shutil import which

PREAMBLE = ("Use your built-in image generation tool (image_gen) to create one image. "
            "Call image_gen exactly once, then reply DONE. If it fails, print the tool's error verbatim and stop. "
            "Do not run shell commands, do not look for or save files, do not retry.\n\n")
ASPECT = ("The image must have an aspect ratio of {a} (width:height); fill the whole frame, "
          "no borders or letterboxing.\n\n")
MIN_BYTES = 8 * 1024


def codex_home():
    return os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))


def find_result(start_ts, token):
    """Newest image produced by this run (matched by a token in the session log)."""
    root = os.path.join(codex_home(), "sessions")
    found = None
    for f in sorted(glob.glob(os.path.join(root, "*", "*", "*", "rollout-*.jsonl")), key=os.path.getmtime):
        if os.path.getmtime(f) < start_ts - 5:
            continue
        try:
            text = open(f, errors="ignore").read()
        except OSError:
            continue
        if token not in text:
            continue
        for line in text.splitlines():
            if "image_gen" not in line and "image_generation_call" not in line:
                continue
            try:
                ev = json.loads(line).get("payload", {})
            except json.JSONDecodeError:
                continue
            item = ev.get("item", {})
            if item.get("status") == "completed":              # image written to generated_images/
                png = os.path.join(codex_home(), "generated_images", ev.get("thread_id", ""), item.get("id", "") + ".png")
                if os.path.isfile(png):
                    found = open(png, "rb").read()
            if ev.get("type") == "image_generation_call" and ev.get("status") == "completed" and ev.get("result"):
                try:
                    found = base64.b64decode(ev["result"])     # image embedded in the session log
                except (ValueError, TypeError):
                    pass
    return found


def aspect_ok(path, want):
    try:
        from PIL import Image
    except ImportError:
        return True, None
    with Image.open(path) as im:
        got = im.size[0] / im.size[1]
    return abs(got / want - 1) <= .05, got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--aspect")
    ap.add_argument("--out", default=".")
    ap.add_argument("--name", default="image")
    ap.add_argument("--timeout", type=int, default=480)
    ap.add_argument("--retries", type=int, default=1)
    a = ap.parse_args()
    if which("codex") is None:
        print("codex CLI not found: install it, or generate the image with another tool (see the docstring).", file=sys.stderr)
        return 4
    want = None
    if a.aspect:
        w, h = a.aspect.split(":"); want = float(w) / float(h)
    os.makedirs(a.out, exist_ok=True)
    target = os.path.abspath(os.path.join(a.out, a.name + ".png"))
    for attempt in range(a.retries + 1):
        token = f"RUN-{os.getpid()}-{int(time.time() * 1000)}"
        prompt = PREAMBLE + (ASPECT.format(a=a.aspect) if a.aspect else "") + a.prompt + f"\n\n(job {token}; ignore this line)"
        start = time.time()
        log = open(target + ".log", "w")
        p = subprocess.Popen(["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only"],
                             stdin=subprocess.PIPE, stdout=log, stderr=log, text=True, start_new_session=True)
        p.stdin.write(prompt); p.stdin.close()
        data = None
        while time.time() - start < a.timeout:
            data = find_result(start, token)
            if data or p.poll() is not None:
                break
            time.sleep(2)
        if p.poll() is None:                      # Codex sometimes lingers after the image is done
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                p.kill()
        log.close()
        data = data or find_result(start, token)
        if data and len(data) >= MIN_BYTES:
            open(target, "wb").write(data)
            ok, got = aspect_ok(target, want) if want else (True, None)
            if ok:
                os.remove(target + ".log"); print(target); return 0
            print(f"aspect {got:.3f} is not {a.aspect}; retrying", file=sys.stderr)
        time.sleep(3)
    tail = open(target + ".log").read()[-600:] if os.path.exists(target + ".log") else ""
    print(f"no usable image. Last Codex output:\n{tail}", file=sys.stderr)
    return 3 if os.path.exists(target) else 2


if __name__ == "__main__":
    sys.exit(main())
