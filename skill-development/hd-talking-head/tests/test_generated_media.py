from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _env  # noqa: F401

from edit.hd.tools import broll_component_executor as executor
import broll_capability_router as router
import generated_media
from edit.hd.tests.test_broll_capability_router import (
    _compile_context,
    _strategy_component,
    _visual_strategy,
)
from edit.hd.tests.test_broll_component_executor import _Job
from lovart_existing_video_adapter import create_artifact_probe
from edit.hd.tools import visual_canary


class GeneratedMediaPublicSmoke(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_actual_media_record_compiles_and_runs_public_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = _Job(root)
            media_path = job.job_dir / "generated.mp4"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
                 "-i", "color=c=blue:s=1080x1920:r=24:d=2", "-frames:v", "48", "-an",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(media_path)],
                check=True, capture_output=True,
            )
            media_sha = hashlib.sha256(media_path.read_bytes()).hexdigest()
            prompt_sha = hashlib.sha256(b"a blue vertical explanatory scene").hexdigest()
            record = {
                "schema_version": 1, "status": "completed", "job_id": job.job_id,
                "segment_id": "seg-router", "component_id": "ai",
                "provider": "fixture-provider", "model": "fixture-video",
                "endpoint_id": "fixture-video-endpoint", "generation_id": "generation-001",
                "prompt_sha256": prompt_sha,
                "media": {"job_path": "generated.mp4", "sha256": media_sha,
                          "byte_count": media_path.stat().st_size, "media_type": "video"},
                "generation": {"request_id": "generation-001", "task_ids": ["task-001"]},
                "qa": {"passed": True, "observed_scene": "solid blue vertical scene"},
                "semantic_brief": {"observed_scene": "solid blue vertical scene"},
                "source_binding": {"aroll_sha256": "a" * 64, "start": 0, "end": 2},
                "source_dimensions": {"width": 1080, "height": 1920},
            }
            binding = generated_media.prepare_binding(record)
            self.assertEqual(binding["source_dimensions"], {"width": 1080, "height": 1920})

            component = _strategy_component("ai", "ai_generated", layout_slot="full_frame")
            component["media_type"] = "video"
            strategy = _visual_strategy([component], segment_id="seg-router")
            context = _compile_context([component], segment_frames=48, binding_overrides={"ai": binding})
            recipe = router.compile_strategy(strategy, context)
            self.assertEqual(recipe["components"][0]["executor"], "generated_media")

            adapters = generated_media.create_job_adapter(job, [record])
            probe = create_artifact_probe(shutil.which("ffprobe"))
            segment = {"segment_id": "seg-router", "start": 0, "end": 2, "shot_recipe": recipe}
            with patch.object(visual_canary, "load_approved_visual_plan", return_value={"segments": [segment]}), \
                 patch.object(visual_canary, "approved_aroll_record", return_value={"sha256": "a" * 64}):
                artifact = executor.execute_component(
                    job, executor.ComponentExecutionRequest(recipe, "ai"),
                    adapters={"ai_generated": adapters, "artifact_probe": probe},
                )
            self.assertEqual(artifact.output_sha256, media_sha)
            self.assertEqual(artifact.media_probe["width"], 1080)
            self.assertEqual(artifact.media_probe["height"], 1920)
            self.assertEqual(artifact.invocation_evidence["adapter_record"]["external_requests"], 0)


if __name__ == "__main__":
    unittest.main()
