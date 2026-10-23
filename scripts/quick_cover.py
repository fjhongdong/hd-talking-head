#!/usr/bin/env python3
"""One-step cover binding: title + image → cover_direction + cover, done.

Usage:
  <python> quick_cover.py --job-context <ctx> --title "标题" --subtitle "副标" \
      --image <path-to-approved-png> [--prompt "生成提示词"]

Handles internally: cover_direction schema, image resize to 1080x1920,
cover binding, artifact creation, state approval. No manual steps needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--title", required=True, help="4-8 汉字封面主标题")
    parser.add_argument("--subtitle", default="", help="副标题")
    parser.add_argument("--image", type=Path, required=True, help="已确认的封面 PNG 路径")
    parser.add_argument("--prompt", default="", help="实际生成提示词(如有)")
    parser.add_argument("--style-id", default="style-03")
    parser.add_argument("--timestamp", type=float, default=3.0, help="人物参考帧时间")
    args = parser.parse_args()

    import platform
    if platform.system() == "Darwin" and "python3.12" in sys.executable:
        pass
    project_root = args.job_context.resolve().parent
    for candidate in [project_root, project_root.parent, project_root.parents[1]]:
        if (candidate / "edit/hd/tools").is_dir():
            sys.path.insert(0, str(candidate))
            break

    from edit.hd.tools import state, cover_direction, cover as cover_mod
    from PIL import Image

    job_dir = args.job_context
    if job_dir.suffix == ".json":
        job_dir = Path(json.loads(job_dir.read_text())["job_dir"])
    job = state.load_job(job_dir)

    # ── 1. cover_direction(自动构造合法 schema)──
    direction = {
        "output_aspect_ratio": "9:16",
        "title": args.title,
        "subtitle": args.subtitle or " ",
        "person_reference": {"source": "current-aroll-video", "timestamp": args.timestamp},
        "pose": "自动",
        "expression": "自然",
        "environment": "自动",
        "props": [],
        "composition": {"style_id": args.style_id, "person_side": "left",
                        "person_width_ratio": 0.45, "blank_width_ratio": 0.55},
        "palette": {"background": "warm-light", "font_color": "#17191e",
                     "accent_color": "#ff6b3d"},
        "typography": {"font_style": "heavy-sans"},
        "safe_zones": {"safe_margin_ratio": 0.10},
        "prompt_allow": ["自动"],
        "prompt_deny": ["自动"],
    }

    # 如果已有批准的 cover_direction,先修订
    if job.stages["cover_direction"]["status"] == "approved":
        state.revise(job, "cover_direction", "quick_cover: 重新绑定封面")
        job = state.load_job(args.job_context)

    cover_direction.prepare_cover_direction(job, direction)
    state.approve(state.load_job(args.job_context), "cover_direction")

    # ── 2. 封面图片处理(缩放到精确 1080x1920)──
    img = Image.open(args.image)
    if img.size != (1080, 1920):
        img = img.resize((1080, 1920), Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")

    tmp_path = args.job_context.parent / "quick-cover.png"
    img.save(str(tmp_path), "PNG")
    cover_sha = hashlib.sha256(tmp_path.read_bytes()).hexdigest()

    # ── 3. cover 绑定 ──
    job = state.load_job(args.job_context)
    if job.stages["cover"]["status"] == "approved":
        state.revise(job, "cover", "quick_cover: 重新绑定")
        job = state.load_job(args.job_context)

    cover_dir = args.job_context / "04-cover"
    if cover_dir.exists():
        shutil.rmtree(cover_dir)

    cover_mod.prepare_cover(
        job,
        approved_preview=tmp_path,
        approved_preview_sha256=cover_sha,
        approved_preview_prompt=args.prompt or f"快速绑定: {args.title}",
    )
    state.approve(state.load_job(args.job_context), "cover")

    # 清理临时文件
    tmp_path.unlink(missing_ok=True)

    result = state.load_job(args.job_context)
    print(json.dumps({
        "cover_direction": result.stages["cover_direction"]["status"],
        "cover": result.stages["cover"]["status"],
        "next": result.stages["speech_cleanup"]["status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
