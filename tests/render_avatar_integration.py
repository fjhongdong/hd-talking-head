"""Opt-in, serial FFmpeg avatar QA using a measured real-person still.

Creates controlled positions/motion, not a human approval or a lip-sync test.
The output directory must be new. No user Job or approved asset is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qa_position(profile, *, left):
    outer = profile["diameter"] + 2 * profile["border_width"]
    return {"x": 40 if left else 1080 - outer - 40, "y": 1700 - outer - 28}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--portrait-frame", type=Path, required=True)
    parser.add_argument("--calibration-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root.resolve()))
    from PIL import Image, ImageChops, ImageStat
    helper_path = Path(__file__).resolve().parents[1] / "scripts/avatar_profile.py"
    spec = importlib.util.spec_from_file_location("avatar_qa_helper", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    calibration = json.loads(args.calibration_json.read_text())
    helper.validate_avatar(calibration, frames=48)
    if calibration["profile"]["source_sha256"] != sha(args.portrait_frame):
        raise ValueError("calibration must bind the measured portrait frame")
    with Image.open(args.portrait_frame) as portrait:
        if portrait.size != (1080, 1920):
            raise ValueError("portrait must be 1080x1920 before calibration")
    from edit.hd.tools import segment_render
    args.output.mkdir(parents=True, exist_ok=False)
    records = []

    def run(argv):
        process = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        records.append({"argv": argv, "exit_code": process.returncode, "stderr": process.stderr[-4000:]})
        process.check_returncode()
        return process.stdout

    def encode(inputs, graph, destination, frames):
        run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
             "-filter_complex_threads", "1", "-threads", "1", *inputs,
             "-filter_complex", graph, "-map", "[out]", "-an", "-frames:v", str(frames),
             "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", "18",
             "-pix_fmt", "yuv420p", str(destination)])

    source = args.output / "controlled-source.mp4"
    crop = calibration["crop"]
    anchor = crop["anchors"][0]
    # t is the source clock in seconds; crop below uses the local 24fps n clock.
    x_motion = "if(lt(t,2),180,if(lt(t,4),0,if(lt(t,6),360,min(360,max(0,(t-6)*24*360/47)))))"
    graph = (f"[0:v]crop={crop['size']}:{crop['size']}:{anchor['x']}:{anchor['y']},"
             "scale=720:720,setsar=1[person];"
             "color=c=0x263238:s=1080x1920:r=24:d=8[canvas];"
             f"[canvas][person]overlay=x='{x_motion}':y=400:eval=frame:shortest=1,format=yuv420p[out]")
    encode(["-loop", "1", "-framerate", "24", "-i", str(args.portrait_frame)], graph, source, 192)
    cases, segments = [], []
    for index, name in enumerate(("center", "left", "right", "moving")):
        def xpos(frame):
            return (180, 0, 360)[index] if index < 3 else frame * 360 / 47

        def point(point, x):
            return [(point[0] - anchor["x"]) * 720 / crop["size"] + x,
                    (point[1] - anchor["y"]) * 720 / crop["size"] + 400]

        anchors = []
        for frame in (0, 24, 47):
            x = xpos(frame)
            lm = anchor["landmarks"]
            face = lm["face_box"]
            anchors.append({"frame": frame, "x": x, "y": 400, "landmarks": {
                "head_top": point(lm["head_top"], x), "chin": point(lm["chin"], x),
                "neck": point(lm["neck"], x),
                "shoulders": [point(p, x) for p in lm["shoulders"]],
                "face_box": point(face[:2], x) + [n * 720 / crop["size"] for n in face[2:]],
            }})
        avatar = {"profile": {**calibration["profile"], "source_sha256": sha(source)},
                  "position": qa_position(calibration["profile"], left=bool(index % 2)),
                  "crop": {"size": 720, "anchors": anchors}}
        composition = {"presenter_mode": "bottom_window", "avatar": avatar}
        segments.append({"start": index * 2, "end": index * 2 + 2,
                         "visual_strategy": {"composition": composition}})
        video = args.output / f"{name}.mp4"
        graph = segment_render.build_filter_graph({"composition": composition, "components": []}, (), frames=48)
        encode(["-ss", str(index * 2), "-i", str(source)], graph, video, 48)
        probe = json.loads(run([args.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(video)]))
        stream = probe["streams"][0]
        assert (stream["width"], stream["height"], stream["avg_frame_rate"], stream["nb_frames"]) == (1080, 1920, "24/1", "48")
        outer = avatar["profile"]["diameter"] + 2 * avatar["profile"]["border_width"]
        pos = avatar["position"]
        paths = []
        for frame in (2, 24, 34, 47):
            target = args.output / f"{name}-{frame:02}.png"
            run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-threads", "1",
                 "-i", str(video), "-vf", f"select=eq(n\\,{frame}),crop={outer}:{outer}:{pos['x']}:{pos['y']}",
                 "-frames:v", "1", "-threads", "1", str(target)])
            paths.append(target)
        with Image.open(paths[0]) as first, Image.open(paths[2]) as stable:
            mae = sum(ImageStat.Stat(ImageChops.difference(first.convert("RGB"), stable.convert("RGB"))).mean) / 3
        assert mae < 4, f"{name}: local crop drift MAE={mae}"
        cases.append({"case": name, "avatar": avatar, "probe": probe, "stable_crop_mae": mae,
                      "video": str(video), "sha256": sha(video),
                      "samples": [{"path": str(p), "sha256": sha(p)} for p in paths]})
    helper.validate_plan_avatars(segments, source_sha256=sha(source))
    receipt = {"scope": "controlled motion of a real still; not natural-motion or lip-sync approval",
               "project": str(args.project_root.resolve()), "source_sha256": sha(source),
               "portrait_sha256": sha(args.portrait_frame), "calibration_sha256": sha(args.calibration_json),
               "cases": cases, "invocations": records}
    (args.output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "cases": len(cases),
                      "stable_crop_mae": [case["stable_crop_mae"] for case in cases]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
