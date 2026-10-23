from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import (
    broll_component_executor,
    confirmed_content,
    contract_artifacts,
    segment_render,
    subtitles_v2,
    visual_assets_v2,
    visual_canary,
)


def _overlay_segment(identifier: str = "seg-001") -> dict[str, object]:
    component = {
        "component_id": "caption-overlay",
        "kind": "code_generated",
        "semantic_role": "explanation",
        "layer_role": "annotation",
        "media_type": "animation",
        "render_window": {
            "start_frame": 0,
            "end_frame": 48,
            "z_index": 10,
            "layout_slot": "annotation",
            "opacity": 1.0,
            "safe_zone": {"top": 64, "bottom": 320, "left": 40, "right": 40},
        },
        "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": True},
        "dependency_id": "custom-talkcraft-overlay",
        "executor": "fixture-executor",
        "primary_renderer": "Remotion",
        "producer_version": "fixture-v1",
        "renderer_version": "fixture-v1",
        "entrypoint": "fixture/render.mjs",
        "invocation_record": {},
    }
    composition = {
        "family": "aroll_with_overlay",
        "presenter_mode": "full_frame",
        "reading_order": [component["component_id"]],
        "component_dependencies": [],
    }
    recipe = {
        "schema_version": 2,
        "segment_id": identifier,
        "strategy_revision": 1,
        "mode": "none",
        "composition": composition,
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": [component],
        "final_compositor": "ffmpeg",
    }
    return {
        "segment_id": identifier,
        "start": 0.0,
        "end": 2.0,
        "visual_strategy": {
            "segment_id": identifier,
            "mode": "none",
            "components": [component],
            "composition": composition,
        },
        "shot_recipe": recipe,
    }


class ArollOverlayPipelineTests(unittest.TestCase):
    def test_confirmed_overlay_and_opening_survive_unrelated_clock_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_dir = root / 'job'
            job = SimpleNamespace(root=root, job_dir=job_dir, job_id='job-confirmed')
            contract_artifacts.write_json_artifact(root / 'job-context.json', {})
            required = {'schema_version': 1, 'job_id': job.job_id,
                'source_words': [{'index': 0, 'text': '学AI'}],
                'visuals': [{'component_id': 'caption-overlay',
                    'composition_family': 'aroll_with_overlay', 'visible_text': ['标准'],
                    'binding': {'dependency_id': 'custom-talkcraft-overlay'}}]}
            contract_artifacts.write_json_artifact(job_dir / 'manifests/confirmed-content.json', required)
            contract_artifacts.write_json_artifact(job_dir / '05-speech-cleanup/word-transcript.json',
                {'words': [{'start': 3.14, 'end': 3.40, 'text': '学AI'}]})
            timeline_path = job_dir / '06-edit-structure/timeline-map.json'
            timeline = {'segments': [{'source_start': 3.06, 'source_end': 3.50,
                'timeline_start': 0, 'timeline_end': .44}]}
            contract_artifacts.write_json_artifact(timeline_path, timeline)
            segment = _overlay_segment()
            segment['visible_text'] = ['标准']
            segment['bindings'] = {'caption-overlay': {'dependency_id': 'custom-talkcraft-overlay'}}
            plan = {'segments': [segment]}
            confirmed_content.check_confirmed_content(job, plan)
            missing = copy.deepcopy(plan)
            missing['segments'][0]['shot_recipe']['components'] = []
            with self.assertRaisesRegex(confirmed_content.ConfirmedContentError, 'caption-overlay'):
                confirmed_content.check_confirmed_content(job, missing)
            changed_clock = copy.deepcopy(plan)
            changed_clock['segments'][0].update(start=1.5, end=3.5)
            changed_clock['segments'][0]['shot_recipe']['strategy_revision'] += 1
            confirmed_content.check_confirmed_content(job, changed_clock)
            draft = copy.deepcopy(plan)
            draft['segments'][0].pop('shot_recipe')
            confirmed_content.check_confirmed_content(job, draft)
            timeline['segments'][0]['source_start'] = 3.20
            contract_artifacts.write_json_artifact(timeline_path, timeline)
            with self.assertRaisesRegex(confirmed_content.ConfirmedContentError, 'word 0.*deleted'):
                confirmed_content.check_confirmed_content(job, plan)

    def test_canary_selects_overlay_but_skips_plain_no_broll(self) -> None:
        overlay = _overlay_segment("seg-001")
        plain = {
            "segment_id": "seg-002",
            "start": 2.0,
            "end": 4.0,
            "shot_recipe": {"mode": "none", "composition": {"family": "no_broll"}},
        }
        selected = visual_canary.select_representative_segments([plain, overlay])
        self.assertEqual([item["segment_id"] for item in selected], ["seg-001"])

    def test_overlay_component_execution_preserves_reading_order_and_recipe(self) -> None:
        segment = _overlay_segment()
        artifact = object()
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            return_value=artifact,
        ) as execute:
            result = visual_canary.execute_approved_components(
                SimpleNamespace(), segment, adapters={"artifact_probe": object()}
            )
        self.assertEqual(result, (artifact,))
        request = execute.call_args.args[1]
        self.assertIsInstance(request, broll_component_executor.ComponentExecutionRequest)
        self.assertEqual(request.component_id, "caption-overlay")
        self.assertIs(request.recipe, segment["shot_recipe"])

    def test_visual_assets_dispatches_overlay_components_to_arroll_renderer(self) -> None:
        segment = _overlay_segment()
        plan = {"segments": [segment], "visual_plan_sha256": "a" * 64}
        sentinel = RuntimeError("stop after dispatch")
        with tempfile.TemporaryDirectory() as directory:
            job = SimpleNamespace(
                job_dir=Path(directory),
                stages={"visual_assets": {"status": "pending", "artifact_scope": ["seg-001"]}},
            )
            with mock.patch.object(visual_assets_v2.state, "require_runnable"), \
                 mock.patch.object(visual_assets_v2, "_load_segments", return_value={}), \
                 mock.patch.object(visual_assets_v2.visual_canary, "approved_aroll_record",
                                   return_value={"path": directory + "/a.mp4", "sha256": "b" * 64, "bytes": 1}), \
                 mock.patch.object(visual_assets_v2.visual_canary, "execute_approved_components",
                                   return_value=("alpha-artifact",)) as execute, \
                 mock.patch.object(visual_assets_v2.segment_render, "render_arroll_segment",
                                   side_effect=sentinel) as render:
                with self.assertRaisesRegex(RuntimeError, "stop after dispatch"):
                    visual_assets_v2._prepare_visual_assets_v2_locked(
                        job, plan, {}, component_adapters={}
                    )
        execute.assert_called_once_with(job, segment, adapters={})
        self.assertEqual(render.call_args.kwargs["artifacts"], ("alpha-artifact",))

    def test_filter_graph_keeps_annotation_in_canvas_coordinates(self) -> None:
        component = _overlay_segment()["shot_recipe"]["components"][0]
        recipe = _overlay_segment()["shot_recipe"]
        artifact = broll_component_executor.ComponentArtifact(
            schema_version=1,
            status="success",
            job_id="job-001",
            segment_id="seg-001",
            component_id="caption-overlay",
            kind="code_generated",
            strategy_revision=1,
            media_type="animation",
            source_media_type="animation",
            artifact_media_type="video",
            layout_slot="annotation",
            safe_zone=component["render_window"]["safe_zone"],
            render_window=component["render_window"],
            z_index=10,
            opacity=1.0,
            artifact_contract={"width": 1080, "height": 1920, "fps": 24, "alpha": True},
            media_probe={"media_type": "video", "container": "mov", "codec": "qtrle",
                         "pixel_format": "argb", "alpha": True, "width": 1080,
                         "height": 1920, "fps": 24, "frame_count": 48, "duration": 2.0},
            input_sha256="a" * 64,
            job_path="09-visual-assets/components/caption-overlay.mov",
            byte_count=1,
            output_sha256="b" * 64,
            invocation_evidence={"primary_renderer": "Remotion"},
            qa={"passed": True},
            error_code=None,
        )
        graph = segment_render.build_filter_graph(recipe, (artifact,), frames=48)
        self.assertIn("scale=1080:1920", graph)
        self.assertIn("pad=1080:1920", graph)
        self.assertNotIn("scale=1000:1536", graph)

    def test_subtitle_classifier_keeps_overlay_in_a_roll_class(self) -> None:
        segment = _overlay_segment()
        self.assertEqual(subtitles_v2._shot_mode(segment), "none")


if __name__ == "__main__":
    unittest.main()
