#!/usr/bin/env python3
"""Cut just one segment from a NASA source video URL (HTTP range reads, without downloading the whole file), and append the source to SOURCES.jsonl.
Usage: python3 tools/grab.py <nasa_id> <version orig|large|mobile> <start seconds> <duration seconds> <name> [--copy]
--copy: stream copy (the start snaps to the previous keyframe); by default, exact start with an x264 crf 14 re-encode."""
import json, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path
nid, ver, ss, dur, name = sys.argv[1:6]; copy = "--copy" in sys.argv
q = urllib.parse.quote(nid)
url = f"https://images-assets.nasa.gov/video/{q}/{q}~{ver}.mp4"
meta = json.load(urllib.request.urlopen(f"https://images-api.nasa.gov/search?nasa_id={q}", timeout=60))["collection"]["items"][0]["data"][0]
out = Path("raw") / f"{name}.mp4"; out.parent.mkdir(exist_ok=True)
enc = ["-c", "copy"] if copy else ["-c:v", "libx264", "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k"]
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", ss, "-t", dur, "-i", url, *enc, str(out)], check=True)
p = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(out)], capture_output=True, text=True).stdout)
v = next(s for s in p["streams"] if s["codec_type"] == "video")
rec = {"name": name, "file": str(out), "url": url, "input": f"nasa:{nid} ~{ver} [{ss}s +{dur}s]" + (" (stream copy)" if copy else ""),
       "page": f"https://images.nasa.gov/details/{q}", "title": meta.get("title"), "date": meta.get("date_created", "")[:10],
       "credit": meta.get("photographer") or meta.get("center") and f"NASA {meta['center']}" or "NASA",
       "license": "NASA media, generally not copyrighted (images.nasa.gov guidelines)", "w": v["width"], "h": v["height"], "fps": v["r_frame_rate"],
       "dur": float(p["format"]["duration"]), "audio": any(s["codec_type"] == "audio" for s in p["streams"]), "note": f"excerpt {ss}s +{dur}s of the {ver} file", "used": [],
       "fetched": time.strftime("%Y-%m-%d %H:%M")}
recs = [json.loads(l) for l in open("SOURCES.jsonl")] if Path("SOURCES.jsonl").exists() else []
recs = [r for r in recs if r["name"] != name] + [rec]
open("SOURCES.jsonl", "w").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
print(json.dumps({k: rec[k] for k in ("file", "w", "h", "fps", "dur", "audio")}))
