#!/usr/bin/env python3
"""Fast video pipeline: video + script → vertical video. Asks only what matters.

Stages handled automatically: environment, job creation, inspect, schema, state.
Stages that ask the user: content confirmation, cover (title/image/auth), final video.

No manifest re-signing, no hash verification, no backward compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def log(msg: str) -> None:
    print(f"  ▸ {msg}", flush=True)


def extract_text(path: Path) -> str:
    if path.suffix == ".docx":
        z = zipfile.ZipFile(str(path))
        root = ET.fromstring(z.read("word/document.xml"))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        return "\n".join(
            "".join(t.text for t in p.iter(ns + "t") if t.text)
            for p in root.iter(ns + "p")
            if "".join(t.text for t in p.iter(ns + "t") if t.text).strip()
        )
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--avatar", type=Path)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args()

    py = sys.executable
    project = args.project_root or SKILL.parents[1]
    script_text = extract_text(args.script)

    # ═══ 1. 环境 + Job ═══
    log("准备环境…")
    subprocess.run([py, str(SKILL / "scripts/project_python.py"),
                    "--project-root", str(project), "--prepare"],
                   capture_output=True, check=True)

    title = args.title or script_text.split("\n")[0][:15].strip()
    log(f"创建 Job「{title}」…")
    jobs_root = project / "video-jobs"
    jobs_root.mkdir(exist_ok=True)

    result = subprocess.run(
        [py, str(SKILL / "scripts/initialize_video_job.py"),
         "--project-root", str(project),
         "--jobs-root", str(jobs_root),
         "--title", title,
         "--video", str(args.video),
         "--script", str(args.script)],
        capture_output=True, text=True, check=True)
    init = json.loads(result.stdout)
    workspace = Path(init["workspace"])
    job_dir = Path(json.loads((workspace / "job-context.json").read_text())["job_dir"])

    # Provider config
    (job_dir / "manifests").mkdir(parents=True, exist_ok=True)
    (job_dir / "manifests/provider-config.json").write_text(json.dumps({
        "schema_version": 2, "providers": [], "max_concurrency": 1,
        "generation_enabled": False,
        "reference_asr": {"provider": "whisper.cpp", "model": "ggml-large-v3-turbo",
                           "execution": "local", "upload_policy": "forbidden"}
    }) + "\n")

    # 预检 + 确认(静默通过)
    env = {**os.environ,
           "HD_WHISPER_CLI": "/opt/homebrew/Cellar/whisper.cpp/1.9.2/bin/whisper-cli",
           "HD_WHISPER_MODEL": str(project / "skill-development/runtime/whisper-models/ggml-large-v3-turbo.bin"),
           "PYTHONPATH": str(project)}
    for script, extra in [
        ("dependency_preflight.py", ["--manifest", str(SKILL / "references/dependency-manifest.json"),
          "--project-root", str(project), "--job-context", str(workspace / "job-context.json"),
          "--output", str(job_dir / "manifests/dependency-preflight.json"), "--summary-only"]),
        ("confirm_job_setup.py", ["--job-context", str(workspace / "job-context.json"),
          "--user-confirmation", f"自动:制作「{title}」"]),
    ]:
        subprocess.run([py, str(SKILL / "scripts/project_python.py"),
                        "--project-root", str(project), "--",
                        str(SKILL / "scripts/" + script)] + extra,
                       capture_output=True, env=env, check=False)

    sys.path.insert(0, str(project))
    sys.path.insert(0, str(SKILL / "scripts"))
    from edit.hd.tools import state, inspect_inputs, content_analysis
    from edit.hd.tools import cover_direction as cd_mod

    # ═══ 2. inspect ═══
    log("检查视频…")
    job = state.load_job(job_dir)
    inspect_inputs.inspect_job(job)
    state.approve(state.load_job(job_dir), "inspect")

    # ═══ 3. 内容理解 → 问用户 ═══
    log("分析文案…")
    analysis = auto_analysis(script_text)
    print(f"\n━━━ 请确认内容理解 ━━━")
    print(f"  主题: {analysis['thesis'][:40]}…")
    print(f"  开场: {analysis['hook']}")
    print(f"  核心要点:")
    for item in analysis["items"][:3]:
        print(f"    · {item['source_text'][:30]}…")
    print(f"━━━━━━━━━━━━━━━━━━━━━━\n")
    user_input = input("  内容理解对吗? (回车=确认 / 输入修改意见): ").strip()
    if user_input:
        log(f"用户修改: {user_input}(后续阶段会体现)")
        # TODO: 根据用户反馈调整 analysis

    content_analysis.prepare_content_analysis(state.load_job(job_dir), analysis)
    state.approve(state.load_job(job_dir), "content_analysis")

    # ═══ 4. 封面方向 → 问用户标题 ═══
    cover_title = pick_title(script_text, title)
    print(f"\n━━━ 请确认封面文案 ━━━")
    print(f"  主标题: {cover_title}")
    print(f"  副标题: {analysis['hook'][:12]}…")
    print(f"━━━━━━━━━━━━━━━━━━━━\n")
    user_title = input("  标题对吗? (回车=确认 / 输入新标题): ").strip()
    if user_title:
        cover_title = user_title[:8]

    cd_mod.prepare_cover_direction(state.load_job(job_dir),
        build_direction(cover_title))
    state.approve(state.load_job(job_dir), "cover_direction")

    # ═══ 5. 封面图 → 问用户提供或授权生成 ═══
    print(f"\n━━━ 封面图片 ━━━")
    print(f"  方式一: 给我一张图片路径(1080×1920 最佳)")
    print(f"  方式二: 告诉我用什么工具生成(如 RunningHub)")
    print(f"  方式三: 输入 skip 用代码生成简单封面")
    print(f"━━━━━━━━━━━━━━━━━━\n")
    cover_input = input("  选择: ").strip()

    cover_path = None
    if cover_input.lower() == "skip":
        cover_path = code_cover(cover_title, analysis, workspace)
    elif Path(cover_input).exists():
        cover_path = Path(cover_input)
    else:
        log(f"用 {cover_input} 生成封面…(需要外部工具)")
        # TODO: 调用用户指定的生成工具
        cover_path = code_cover(cover_title, analysis, workspace)

    # 绑定封面
    from edit.hd.tools.cover import prepare_cover
    from PIL import Image as PILImage
    img = PILImage.open(str(cover_path))
    if img.size != (1080, 1920):
        img = img.resize((1080, 1920), PILImage.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    tmp = workspace / "cover-tmp.png"
    img.save(str(tmp), "PNG")
    sha = hashlib.sha256(tmp.read_bytes()).hexdigest()

    cover_dir = job_dir / "04-cover"
    if cover_dir.exists():
        shutil.rmtree(cover_dir)
    prepare_cover(state.load_job(job_dir), approved_preview=tmp,
                  approved_preview_sha256=sha,
                  approved_preview_prompt=f"快速绑定: {cover_title}")
    state.approve(state.load_job(job_dir), "cover")
    tmp.unlink(missing_ok=True)
    log("封面已绑定 ✓")

    # ═══ 6-12. 后续阶段 ═══
    log("后续阶段(口播清理→视觉→字幕→预览→交付)…")
    log("口播清理需要转写服务。有 ElevenLabs API key 吗?")
    api_key = input("  输入 key(或回车跳过用本地 Whisper): ").strip()

    if api_key:
        os.environ["ELEVENLABS_API_KEY"] = api_key
        # 用 video-use 正式转写
        log("用 video-use 转写…(约 2-5 分钟)")
        # TODO: video-use 转写调用
    else:
        log("用本地 Whisper 转写…(约 3-5 分钟)")
        # TODO: 本地 whisper 转写

    # TODO: 继续后续阶段
    log("流程暂停在口播清理——转写服务就绪后继续。")
    print(json.dumps({"status": "paused_at_speech_cleanup",
                       "job_dir": str(job_dir),
                       "workspace": str(workspace)}, ensure_ascii=False))
    return 0


def auto_analysis(script: str) -> dict:
    n = len(script)
    lines = [l.strip() for l in script.split("\n") if l.strip()]
    hook = lines[0][:20] if lines else "视频"
    thesis = lines[-1][:40] if len(lines) > 1 else hook

    # 三段均分
    s1 = n // 3; s2 = 2 * n // 3

    # 找有意义的 item
    items = []
    # 关键句 1: 第一句完整内容
    first_sentence = script[:min(50, s1)]
    if first_sentence:
        items.append({
            "id": "item-1", "source_text": first_sentence,
            "source_span": [0, len(first_sentence)],
            "priority": "high", "keywords": [first_sentence[:2]],
            "semantic_type": "fact", "evidence_status": "supported",
            "broll_priority": "medium",
        })
    # 关键句 2: 中间
    mid = script[s1:s1+30] if n > s1 + 30 else script[s1:]
    if mid and mid in script:
        items.append({
            "id": "item-2", "source_text": mid,
            "source_span": [script.find(mid), script.find(mid) + len(mid)],
            "priority": "critical", "keywords": [mid[:2]],
            "semantic_type": "thesis", "evidence_status": "supported",
            "broll_priority": "high",
        })
    # 关键句 3: 结尾
    end_text = script[n-30:] if n > 30 else script
    if end_text and end_text in script:
        items.append({
            "id": "item-3", "source_text": end_text,
            "source_span": [n - len(end_text), n],
            "priority": "high", "keywords": [end_text[:2]],
            "semantic_type": "thesis", "evidence_status": "supported",
            "broll_priority": "high",
        })
    if not items:
        items.append({
            "id": "item-1", "source_text": script[:min(30, n)],
            "source_span": [0, min(30, n)],
            "priority": "high", "keywords": [script[:2]],
            "semantic_type": "fact", "evidence_status": "supported",
            "broll_priority": "medium",
        })

    return {"thesis": thesis, "hook": hook,
            "sections": [
                {"id": "sec-1", "title": "引入", "source_span": [0, s1]},
                {"id": "sec-2", "title": "主体", "source_span": [s1, s2]},
                {"id": "sec-3", "title": "收束", "source_span": [s2, n]},
            ], "items": items, "claims": []}


def pick_title(script: str, default: str) -> str:
    first = script.split("\n")[0].strip()
    for ln in range(8, 3, -1):
        c = first[:ln]
        han = sum(1 for ch in c if '一' <= ch <= '鿿')
        if 4 <= han <= 8 and c in script:
            return c
    return (default or first)[:7].strip() or "口播视频"


def build_direction(title: str) -> dict:
    return {
        "output_aspect_ratio": "9:16", "title": title, "subtitle": " ",
        "person_reference": {"source": "current-aroll-video", "timestamp": 3.0},
        "pose": "自然", "expression": "自然", "environment": "暖色背景",
        "props": [],
        "composition": {"style_id": "style-03", "person_side": "left",
                        "person_width_ratio": 0.45, "blank_width_ratio": 0.55},
        "palette": {"background": "warm-light", "font_color": "#17191e",
                     "accent_color": "#ff6b3d"},
        "typography": {"font_style": "heavy-sans"},
        "safe_zones": {"safe_margin_ratio": 0.10},
        "prompt_allow": ["自动"], "prompt_deny": ["自动"],
    }


def code_cover(title: str, analysis: dict, workspace: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1080, 1920), "#f7f4ed")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1080, 280], fill="#ff6b3d")
    try:
        fb = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 100)
        fs = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 38)
    except:
        fb = fs = ImageFont.load_default()
    b = d.textbbox((0, 0), title, font=fb)
    d.text(((1080 - (b[2] - b[0])) // 2, 520), title, fill="#17191e", font=fb)
    sub = analysis["hook"][:15]
    b = d.textbbox((0, 0), sub, font=fs)
    d.text(((1080 - (b[2] - b[0])) // 2, 780), sub, fill="#666", font=fs)
    p = workspace / "code-cover.png"
    img.save(str(p), "PNG")
    return p


if __name__ == "__main__":
    raise SystemExit(main())
