"""Cover opening uses one offset for the actual media and exported subtitles."""

import io
import sys
import importlib.util
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from edit.hd.tools import contract_artifacts, event_audio, preview_opening, preview_v2, state


OPTIONS = {"hold_frames": 12, "transition_frames": 6,
           "user_confirmation": "测试夹具：使用已批准封面，停留12帧，淡出6帧"}
SRT = "1\n00:00:00,042 --> 00:00:00,750\n分享观点\n\n"
SKILL = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head"


def opening_job(root):
    """Only approved fixture records; never production user approvals."""
    root = root.resolve()
    files = {
        "cover": {"04-cover/cover-delivery-raster.png": None,
                  "04-cover/cover-report.json": None},
        "subtitles": {"10-subtitles/subtitles.srt": SRT.encode()},
    }
    stages = {}
    for stage_id, sources in files.items():
        records = []
        for relative, content in sources.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".png":
                Image.new("RGB", (1080, 1920), (220, 30, 40)).save(path)
            elif content is None:
                contract_artifacts.write_json_artifact(path, {
                    "output_sha256": {"cover-delivery-raster.png":
                        contract_artifacts.sha256_file(root / "04-cover/cover-delivery-raster.png")},
                })
            else:
                path.write_bytes(content)
            records.append({"path": relative, "sha256": contract_artifacts.sha256_file(path),
                            "bytes": path.stat().st_size})
        stages[stage_id] = {"status": "approved", "artifacts": records}
    return SimpleNamespace(job_id="opening-fixture", job_dir=root, stages=stages)


class OpeningContractTests(unittest.TestCase):
    def test_offset_is_hold_only_not_hold_plus_transition(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            plan = preview_opening.plan_opening(job, OPTIONS, body_frames=24)
            self.assertEqual(plan["body_offset_frames"], 12)
            self.assertEqual(plan["total_frames"], 36)
            self.assertEqual(plan["body_frames"], 24)
            self.assertEqual(plan["fps"], 24)
            self.assertEqual(plan["cover"]["path"], "04-cover/cover-delivery-raster.png")

    def test_shift_preserves_copy_and_uses_identical_offset(self):
        self.assertEqual(preview_opening.shift_srt(SRT, 12),
            "1\n00:00:00,542 --> 00:00:01,250\n分享观点\n\n".encode())
        self.assertEqual(preview_opening.shift_srt("", 12), b"")

    def test_invalid_options_fail_instead_of_silent_defaults(self):
        cases = ({"hold_frames": 0}, {"hold_frames": True},
                 {"transition_frames": -1}, {"transition_frames": 24},
                 {"transition_frames": float("nan")}, {"user_confirmation": " "},
                 {"background_music": True})
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            for changes in cases:
                with self.subTest(changes=changes), self.assertRaises(preview_opening.OpeningError):
                    preview_opening.plan_opening(job, {**OPTIONS, **changes}, body_frames=24)

    def test_unapproved_or_changed_cover_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            job.stages["cover"]["status"] = "ready_for_review"
            with self.assertRaises(preview_opening.OpeningError):
                preview_opening.plan_opening(job, OPTIONS, body_frames=24)
            job.stages["cover"]["status"] = "approved"
            (job.job_dir / "04-cover/cover-delivery-raster.png").write_bytes(b"changed")
            with self.assertRaises(preview_opening.OpeningError):
                preview_opening.plan_opening(job, OPTIONS, body_frames=24)

    def test_event_audio_uses_packaged_assets_for_independent_job(self):
        from edit.hd.tools import semantic_events
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            job.root = job.job_dir
            semantic = semantic_events.build_semantic_event_plan(
                visual_plan_sha256="a" * 64, transcript_identity="fixture-transcript",
                events=[{"event_id": "cue-01", "kind": "moment", "segment_id": "seg-001",
                    "span_id": None, "word_range": [0, 1], "start_frame": 6, "end_frame": 24,
                    "semantic_role": "emphasis", "trigger": "semantic_boundary",
                    "channels": {"visual": [], "caption": {}, "audio": ["impact-card-in"],
                                 "spatial": {}, "transition": {}}}],
            )
            packaged = Path(preview_v2.__file__).resolve().parents[1] / "integrations/talkcraft/runtime"
            audio = event_audio.build_default_plan(semantic, runtime_root=packaged,
                                                   job_id=job.job_id, total_frames=24)
            records = []
            for name, value in (("semantic-events.json", semantic), ("audio-event-plan.json", audio)):
                path = job.job_dir / "07-visual-direction" / name
                path.parent.mkdir(exist_ok=True)
                contract_artifacts.write_json_artifact(path, value)
                records.append({"path": str(path.relative_to(job.job_dir)),
                    "sha256": contract_artifacts.sha256_file(path), "bytes": path.stat().st_size})
            for explicit in (False, True):
                with self.subTest(explicit_plan=explicit):
                    job.stages["visual_direction"] = {"status": "approved",
                        "artifacts": records if explicit else records[:1]}
                    actual = preview_v2._approved_event_audio_plan(job, frames=24)
                    self.assertEqual(actual, audio)
                    self.assertTrue(Path(actual["cues"][0]["path"]).is_relative_to(packaged))

    def test_default_command_stays_body_only(self):
        command = preview_v2.build_preview_command_v2(
            Path("v.mp4"), Path("s.webm"), Path("a.mp4"), Path("out.mp4"),
            frames=24, duration=1,
        )
        self.assertEqual(command.count("-i"), 3)
        self.assertIn("2:a:0", command)
        self.assertNotIn("adelay", " ".join(command))

    def test_malformed_cover_report_is_a_domain_error(self):
        with tempfile.TemporaryDirectory() as temp:
            job = opening_job(Path(temp))
            report = job.job_dir / "04-cover/cover-report.json"
            for invalid in (None, [], "hash"):
                contract_artifacts.write_json_artifact(report, {"output_sha256": invalid})
                record = next(r for r in job.stages["cover"]["artifacts"]
                              if r["path"].endswith("cover-report.json"))
                record.update(sha256=contract_artifacts.sha256_file(report), bytes=report.stat().st_size)
                with self.subTest(invalid=invalid), self.assertRaises(preview_opening.OpeningError):
                    preview_opening.plan_opening(job, OPTIONS, body_frames=24)


class OpeningMediaTests(unittest.TestCase):
    def test_actual_frames_audio_and_subtitle_track_share_one_offset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            job = opening_job(root)
            plan = preview_opening.plan_opening(job, OPTIONS, body_frames=24)
            body, overlay = root / "body.mp4", root / "subtitles.webm"
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                "color=c=blue:s=1080x1920:r=24:d=1,"
                "drawbox=x=50:y=50:w=200:h=200:color=lime:t=fill:enable='lt(n,3)'", "-f", "lavfi", "-i",
                "sine=frequency=700:sample_rate=48000:duration=1", "-threads", "1",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(body),
            ], check=True, capture_output=True)
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                "color=c=black@0:s=1080x1920:r=24:d=1,format=rgba,"
                "drawbox=x=100:y=1400:w=800:h=100:color=yellow:t=fill:replace=1",
                "-threads", "1", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                "-auto-alt-ref", "0", "-deadline", "realtime", str(overlay),
            ], check=True, capture_output=True)
            output = root / "review.mp4"
            command = preview_v2.build_preview_command_v2(
                body, overlay, body, output, frames=24, duration=1,
                opening=plan, cover=job.job_dir / plan["cover"]["path"],
            )
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            media = preview_v2._validate_media(output, frames=36, duration=1.5,
                                               require_opening_contract=True)
            self.assertEqual(media["audio_streams"], 1)
            def frame(n):
                data = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", str(output), "-vf",
                    f"select=eq(n\\,{n})", "-frames:v", "1", "-f", "image2pipe",
                    "-c:v", "png", "-",
                ], check=True, capture_output=True).stdout
                return Image.open(io.BytesIO(data)).convert("RGB")
            first = frame(0)
            self.assertGreater(first.getpixel((500, 500))[0], 200)
            self.assertLess(first.getpixel((500, 500))[2], 60)
            stable = frame(20)
            self.assertGreater(stable.getpixel((500, 500))[2], 200)
            self.assertGreater(stable.getpixel((500, 1450))[0], 200)
            samples = np.frombuffer(subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:0",
                "-ar", "48000", "-ac", "1", "-f", "f32le", "-",
            ], check=True, capture_output=True).stdout, dtype=np.float32)
            self.assertLess(np.max(np.abs(samples[:23000])), .001)
            self.assertGreater(np.sqrt(np.mean(samples[25000:47000] ** 2)), .05)
            self.assertGreater(np.sqrt(np.mean(samples[65000:71000] ** 2)), .05)
            # Zero-transition opening must retain body frame zero and its order.
            cut_plan = preview_opening.plan_opening(job, {**OPTIONS, "transition_frames": 0}, body_frames=24)
            mixed = event_audio.prepare_stage_audio(
                {"total_frames": 24, "cues": [{"path": str(body), "start_frame": 6, "volume": .2}]},
                body, root / "event-audio.m4a", body_offset_frames=12,
            )
            atlas = preview_v2._write_number_atlas(root / "numbers.png", [1])
            subprocess.run(preview_v2.build_preview_command_v2(
                body, overlay, body, output, frames=24, duration=1, opening=cut_plan,
                mixed_audio=mixed, number_overlay={"atlas": atlas, "rows": [
                    {"start_frame": 0, "end_frame": 3, "slot": 0}]},
                cover=job.job_dir / cut_plan["cover"]["path"],
            ), check=True, capture_output=True, timeout=120)
            preview_v2._validate_media(output, frames=36, duration=1.5, require_opening_contract=True)
            self.assertGreater(frame(11).getpixel((100, 100))[0], 200)  # Last cover frame.
            self.assertGreater(frame(12).getpixel((100, 100))[1], 200)  # Body frame zero.
            self.assertGreater(frame(14).getpixel((100, 100))[1], 200)  # Body frame two.
            self.assertGreater(frame(15).getpixel((100, 100))[2], 200)  # Body frame three.
            self.assertGreater(frame(12).getpixel((1025, 1860))[0], 200)  # Body badge starts at body zero.
            self.assertLess(frame(15).getpixel((1025, 1860))[0], 30)  # Badge ends with body frame two.
            mixed_samples = np.frombuffer(subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:0",
                "-ar", "48000", "-ac", "1", "-f", "f32le", "-",
            ], check=True, capture_output=True).stdout, dtype=np.float32)
            self.assertLess(np.max(np.abs(mixed_samples[:23000])), .001)
            self.assertGreater(np.sqrt(np.mean(mixed_samples[25000:35000] ** 2)), .05)
            self.assertGreater(np.sqrt(np.mean(mixed_samples[65000:71000] ** 2)), .05)


class OpeningWorkflowTests(unittest.TestCase):
    def setUp(self):
        from edit.hd.tests import test_qa_delivery, test_visual_direction
        from edit.hd.tests.test_startup import approve_fixture_setup
        from edit.hd.tools import content_analysis, material_usage, motion_match_cache, visual_confirmation, visual_plan
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = SKILL.parents[1]
        sys.path.insert(0, str(SKILL / "scripts"))
        import run_stage
        self.runner = run_stage
        self.fixture_voice = self.root / "voice.aiff"
        subprocess.run(["say", "-v", "Tingting", "-o", str(self.fixture_voice), "开场。分享观点。"],
                       check=True, capture_output=True, timeout=30)
        video = self.root / "source.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "color=c=blue:s=1080x1920:r=24:d=3,drawbox=x=50:y=50:w=200:h=200:color=lime:t=fill:enable='lt(n,3)'",
            "-i", str(self.fixture_voice), "-f", "lavfi", "-i",
            "aevalsrc=0.12*sin(2*PI*1200*t)*between(t\\,2.8\\,2.98):s=48000:d=3",
            "-filter_complex", "[1:a]aresample=48000,apad,atrim=duration=3[voice];[voice][2:a]amix=inputs=2:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", "3", str(video),
        ], check=True, capture_output=True, timeout=60)
        script = self.root / "script.md"
        script.write_text("开场。分享观点。", encoding="utf-8")
        picture = Image.new("RGB", (1080, 1920), (0, 0, 255))
        from PIL import ImageDraw
        ImageDraw.Draw(picture).rectangle((50, 50, 250, 250), fill=(220, 0, 220))
        source_image = self.root / "fixture-image.png"
        picture.save(source_image)
        from create_job_workspace import create_workspace
        self.root = create_workspace(self.root / "jobs", "opening-fixture", [video, script, source_image])
        imported = contract_artifacts.read_json_artifact(self.root / "00-user-provided/material-index.json")["materials"]
        video, script = (self.root / record["imported_path"] for record in imported[:2])
        self.material = imported[2]
        self.job = state.create_job(self.root, video, script, profile="full-v2")
        approve_fixture_setup(self.job)
        def write(relative, value):
            path = self.job.job_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(value, bytes): path.write_bytes(value)
            else: contract_artifacts.write_json_artifact(path, value)
            return path
        def approve(stage, paths):
            state.mark_ready(self.job, stage, paths)
            state.approve(self.job, stage)
        approve("inspect", [write("01-inspect/report.json", {"development_fixture": True})])
        text = script.read_text()
        analysis = {"thesis": text, "hook": "开场。", "sections": [{"id": "s1", "title": "观点", "source_span": [0, len(text)]}],
            "items": [{"id": "idea-01", "source_text": text, "source_span": [0, len(text)], "priority": "critical",
                       "keywords": ["分享观点"], "semantic_type": "contrast", "evidence_status": "supported", "broll_priority": "high"}], "claims": []}
        content_analysis.prepare_content_analysis(self.job, analysis)
        state.approve(self.job, "content_analysis")
        approve("cover_direction", [write("03-cover-direction/cover-direction.json", {"development_fixture": True})])
        outputs, report_path, _ = test_qa_delivery._write_cover_contract(self.job.job_dir, "9:16")
        raster = self.job.job_dir / "04-cover/cover-delivery-raster.png"
        Image.new("RGB", (1080, 1920), (220, 30, 40)).save(raster)
        report = json.loads(report_path.read_text())
        record = next(r for r in report["artifacts"] if r["path"].endswith(raster.name))
        record.update(sha256=contract_artifacts.sha256_file(raster), bytes=raster.stat().st_size)
        report["output_sha256"][raster.name] = record["sha256"]
        contract_artifacts.write_json_artifact(report_path, report)
        material_usage.publish_and_mark_ready(self.job, "cover", [*outputs, report_path],
            producer="edit.hd.tools.cover", producer_version="test-v1",
            stage_input_records=material_usage.current_stage_input_records(self.job, "cover"), references=[])
        state.approve(self.job, "cover")
        words = [{"text": "开场。", "start": 1 / 24, "end": .35}, {"text": "分享观点。", "start": .55, "end": 2.5}]
        approve("speech_cleanup", [write("05-speech-cleanup/word-transcript.json", {"version": 1, "words": words}),
            write("05-speech-cleanup/diff-summary.json", {"version": 1, "original_script": text,
                "cleaned_script": text, "deleted_words": [], "deleted_word_count": 0})])
        approve("edit_structure", [write("06-edit-structure/edit-plan.json", {"canvas": {"width": 1080, "height": 1920, "fps": 24}}),
            write("06-edit-structure/timeline-map.json", {"version": 1, "source_duration": 3.0, "output_duration": 3.0,
                "has_deletion": False, "audio_policy": "copy-original-elementary", "render_adapter": "native-ffmpeg-no-cut", "segments": [{"source_start": 0., "source_end": 3., "timeline_start": 0., "timeline_end": 3.}]}),
            write("06-edit-structure/edited-aroll.mp4", video.read_bytes())])
        first = test_visual_direction.draft_segment((), end=.5)
        second = test_visual_direction.draft_segment(("local_material",), segment_id="seg-002", start=.5, end=3.)
        second["visual_intent"]["presenter_presence"] = "hidden"
        second["visual_strategy"]["composition"]["presenter_mode"] = "hidden"
        second["visual_strategy"]["composition"].pop("avatar")
        image = self.job.job_dir / second["bindings"]["component-1"]["job_path"]
        image.parent.mkdir(exist_ok=True)
        shutil.copyfile(self.root / self.material["imported_path"], image)
        second["bindings"]["component-1"].update(material_id=self.material["material_id"], sha256=self.material["sha256"])
        second["candidate_snapshots"]["component-1"][0]["asset_id"] = self.material["material_id"]
        director = {"schema_version": 3, "segments": [first, second]}
        treatment = {"numbering_scope_id": "opening-fixture", "semantic_lists": {"overlay": [], "broll": [{
            "row_id": "fixture-visual", "start_word": 1, "end_word": 2, "quote": "分享观点。", "semantic": "资料解释",
            "visual_task": "展示资料", "components": [{"segment_id": "seg-002", "component_id": "component-1"}]}]},
            "motion_queries": [{"segment_id": "seg-002", "component_id": "component-1", "tags": ["真实资料"]}],
            "beat_sheet": [{"start_word": 0, "end_word": 1, "quote": "开场。", "decision": "aroll", "visual": "真人开场", "components": [], "reason": "真人先开口"},
                {"start_word": 1, "end_word": 2, "quote": "分享观点。", "decision": "broll", "visual": "展示资料", "components": [{"segment_id": "seg-002", "component_id": "component-1"}]}],
            "motion_readability": [{"segment_id": "seg-002", "component_id": "component-1", "targets": [], "no_critical_text_reason": "Plain-color test material has no text"}],
            "skill_selection": {"schema_version": 1, "beats": [], "assignments": [], "overlay_beats": [], "overlay_assignments": [],
                "history_note": "isolated synthetic test fixture", "fixed_context": [{"segment_id": "seg-002", "component_id": "component-1", "start": .5, "end": 3., "skill_id": "local_material", "source_ref": self.material["material_id"], "visual_pattern": "source-evidence"}]}}
        treatment = motion_match_cache.match_once(self.project, director, treatment)
        self.director = write("fixture/director.json", director)
        self.treatment = write("fixture/treatment.json", treatment)
        write("manifests/confirmed-content.json", {"schema_version": 1, "job_id": self.job.job_id,
            "source_words": [{"index": i, "text": word["text"]} for i, word in enumerate(words)],
            "visuals": [{"component_id": "component-1", "composition_family": "single_full_frame",
                "visible_text": [], "binding": second["bindings"]["component-1"]}]})
        proposal = visual_confirmation.prepare_visual_confirmation(self.job, self.director, self.treatment)
        review = {"job_id": self.job.job_id, "job_dir": str(self.job.job_dir), "stage": "visual_direction",
                  "revision": self.job.revision, "artifacts": self.job.stages["visual_direction"]["artifacts"],
                  "passed": True, "note": "Synthetic fixture only; source list checked", "user_confirmation": "Synthetic test approval, not a user Job"}
        self.runner._review(self.job, "visual_direction", review)
        # Publish the existing optional semantic-event contract before freezing
        # the realized mapping. All approval records still come from public APIs.
        visual_plan.prepare_visual_direction(self.job, self.director, self.job.job_dir / "official-previews",
                                             treatment_path=self.treatment)
        plan = contract_artifacts.read_json_artifact(self.job.job_dir / "07-visual-direction/visual-plan.json")
        from edit.hd.tools import semantic_events
        events = semantic_events.build_semantic_event_plan(
            visual_plan_sha256=plan["visual_plan_sha256"], transcript_identity="opening-fixture-words",
            visual_plan=plan, events=[{"event_id": f"event-{i}", "kind": "segment", "segment_id": segment["segment_id"],
                "span_id": None, "word_range": [i, i + 1], "start_frame": round(segment["start"] * 24),
                "end_frame": round(segment["end"] * 24), "semantic_role": "emphasis", "trigger": "semantic_boundary",
                "channels": {"visual": [], "caption": {}, "audio": ["impact-card-in"] if i else [],
                             "spatial": {}, "transition": {}}} for i, segment in enumerate(plan["segments"])])
        state.revise(self.job, "visual_direction", "Fixture adds approved-source semantic audio events")
        visual_plan.prepare_visual_direction(self.job, self.director, self.job.job_dir / "official-previews",
            treatment_path=self.treatment, semantic_event_plan_payload=events)
        visual_confirmation.write_realization_mapping(self.job, host_qa_note="Synthetic fixture local sources checked",
            director_path=self.director, treatment_path=self.treatment)
        self.runner.resume_visual_direction(self.job, self.project)
        self.job = state.load_job(self.job.job_dir)
        approve_fixture_setup(self.job)
        adapters = self.runner.native_component_adapters(self.project, self.job)
        from edit.hd.tools import visual_canary, visual_assets_v2, subtitles
        visual_canary.prepare_visual_canary(self.job, component_adapters=adapters)
        state.approve(self.job, "visual_canary")
        visual_assets_v2.prepare_visual_assets_v2(self.job, component_adapters=adapters)
        state.approve(self.job, "visual_assets")
        subtitles.prepare_subtitles(self.job)
        state.approve(self.job, "subtitles")
        self.body_srt = (self.job.job_dir / "10-subtitles/subtitles.srt").read_text()
        self.proposal = json.loads(proposal.read_text())

    def render(self):
        real_run = subprocess.run
        def compose(command, **kwargs):
            if Path(command[0]).name != "ffmpeg":
                return real_run(command, **kwargs)
            Path(command[-1]).resolve().relative_to(self.job.job_dir)
            if Path(command[-1]).name != "review.mp4":
                return real_run(command, **kwargs)
            Path(command[-1]).write_bytes(b"cover-plus-body")
        def frames(video, directory, duration):
            directory.mkdir()
            paths = []
            for i in range(5):
                path = directory / f"frame-{i}.png"
                Image.new("RGB", (1080, 1920), "red").save(path)
                paths.append(path)
            return paths
        def opening_frames(video, directory, plan):
            paths = []
            for name in ("opening-first", "opening-hold-end", "opening-body-start", "opening-transition-end"):
                path = directory / f"{name}.png"
                Image.new("RGB", (1080, 1920), "red").save(path)
                paths.append(path)
            return paths
        with mock.patch.object(preview_v2.subprocess, "run", side_effect=compose), \
                mock.patch.object(preview_v2, "_validate_media", return_value={
                    "width": 1080, "height": 1920, "fps": 24, "frames": 84, "duration": 3.5,
                    "video_streams": 1, "audio_streams": 1,
                }), mock.patch.object(preview_v2, "_extract_frames", side_effect=frames), \
                mock.patch.object(preview_opening, "extract_evidence", side_effect=opening_frames, create=True):
            return preview_v2.prepare_preview_v2(self.job, opening=OPTIONS)

    def approve_preview(self):
        from edit.hd.tools import visual_review
        expected = visual_review.expected_observations(self.job, "preview")
        observations = [{**row, "playback_window": row["window"], "size_position_clear": True,
            "unobstructed": True, "semantics_clear": True, "conclusion": "Synthetic color fixture and subtitle boundaries checked",
            "design_review": {"verdict": "pass", "composition": "Full-frame test source retained",
                "typography": "Ordinary subtitle renderer used", "finish": "No test source clipping",
                "focus": "Test source and subtitle remain separate"}} for row in expected["observations"]]
        review = {"job_id": self.job.job_id, "job_dir": str(self.job.job_dir), "stage": "preview",
            "revision": self.job.revision, "artifacts": self.job.stages["preview"]["artifacts"], "passed": True,
            "note": "Isolated synthetic test fixture QA, not a user approval",
            "visual_review": {**expected, "observations": observations}}
        self.runner._review(self.job, "preview", review)
        self.job = state.load_job(self.job.job_dir)

    def test_formal_default_preview_delivery_with_event_audio(self):
        from edit.hd.tools import qa_delivery_v2
        command = [sys.executable, str(self.project / "run.py"), "run_stage", "--job-context",
                   str(self.root / "job-context.json"), "--stage", "preview"]
        # Deliberately omit input-json/opening: the formal resolver must apply 12 frames.
        completed = subprocess.run(command, cwd=self.project, capture_output=True, text=True, timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "ready_for_review")
        self.job = state.load_job(self.job.job_dir)
        directory = self.job.job_dir / "11-preview"
        manifest = contract_artifacts.read_json_artifact(directory / "opening-manifest.json")
        self.assertEqual(manifest["options"]["hold_frames"], 12)
        self.assertEqual(manifest["options"]["transition_frames"], 0)
        self.assertEqual(manifest["total_frames"], 84)
        self.assertEqual((directory / "subtitles.srt").read_bytes(), preview_opening.shift_srt(self.body_srt, 12))
        report = contract_artifacts.read_json_artifact(directory / "qa-report.json")
        self.assertEqual(report["number_badge_schedule"][0]["start_frame"], 24)
        audio_plan = contract_artifacts.read_json_artifact(directory / "event-audio-plan.json")
        self.assertEqual(audio_plan["cues"][0]["start_frame"], 12)
        self.assertEqual(report["audio_mix_layers"], 2)
        summary = self.proposal["semantic_summary"]
        routing = (self.job.job_dir / "07-visual-direction/visual-routing.md").read_text()
        self.assertIn(f"贴片{summary['overlay_count']}处 / B-roll{summary['broll_count']}项 / 合计{summary['overlay_count'] + summary['broll_count']}", routing)
        def frame(n):
            data = subprocess.run(["ffmpeg", "-v", "error", "-reinit_filter", "0", "-i", str(directory / "review.mp4"),
                "-vf", f"select=eq(n\\,{n})", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"],
                check=True, capture_output=True).stdout
            return Image.open(io.BytesIO(data)).convert("RGB")
        for n in (0, 11):
            pixel = frame(n).getpixel((100, 100))
            self.assertGreater(pixel[0], 200)
            self.assertLess(pixel[1], 60)
        self.assertGreater(frame(12).getpixel((100, 100))[1], 200)
        self.assertGreater(frame(83).getpixel((100, 100))[0], 180)
        # The normal subtitle renderer must preserve a fully transparent final frame.
        alpha = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i",
            str(self.job.job_dir / "10-subtitles/subtitles.webm"), "-vf", "select=eq(n\\,71),alphaextract",
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
        self.assertEqual(len(alpha), 1080 * 1920)
        self.assertEqual(max(alpha), 0)
        audio = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(directory / "review.mp4"),
            "-map", "0:a:0", "-ar", "48000", "-ac", "1", "-f", "f32le", "-"],
            check=True, capture_output=True).stdout, dtype=np.float32)
        self.assertLess(np.max(np.abs(audio[:23000])), .001)
        self.assertGreater(np.sqrt(np.mean(audio[158400:166080] ** 2)), .02)
        voice = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i",
            str(self.job.job_dir / "06-edit-structure/edited-aroll.mp4"), "-map", "0:a:0",
            "-ar", "48000", "-ac", "1", "-f", "f32le", "-"],
            check=True, capture_output=True).stdout, dtype=np.float32)
        shifted = audio[24000:24000 + len(voice)]
        self.assertEqual(len(shifted), len(voice))
        before_cue = slice(2400, 19200)  # Body .05..40s, before the .5s SFX cue.
        self.assertGreater(np.corrcoef(voice[before_cue], shifted[before_cue])[0, 1], .95)
        difference = shifted - voice
        quiet = np.sqrt(np.mean(difference[before_cue] ** 2))
        after_cue = np.sqrt(np.mean(difference[38400:76800] ** 2))
        self.assertLess(quiet, .005)
        self.assertGreater(after_cue, max(.005, quiet * 4))
        self.approve_preview()
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        self.assertEqual(contract_artifacts.sha256_file(delivery.directory / "final.mp4"),
                         contract_artifacts.sha256_file(directory / "review.mp4"))
        self.assertEqual((delivery.directory / "subtitles/subtitles.srt").read_bytes(),
                         (directory / "subtitles.srt").read_bytes())
        self.assertIn("plans/body-subtitles.webm", delivery.manifest["artifacts"])

    def test_preview_delivery_replay_and_exact_srt_identity(self):
        from edit.hd.tools import qa_delivery_v2, state
        result = self.render()
        directory = self.job.job_dir / "11-preview"
        opening = json.loads((directory / preview_opening.MANIFEST).read_text())
        self.assertEqual(opening["total_frames"], 84)
        self.assertEqual(opening["body_offset_frames"], 12)
        self.assertEqual(result.qa_report["opening_manifest_sha256"], opening["opening_manifest_sha256"])
        self.assertEqual((directory / "subtitles.srt").read_bytes(), preview_opening.shift_srt(self.body_srt, 12))
        records = self.job.stages["preview"]["artifacts"]
        self.assertIn("11-preview/opening-manifest.json", [r["path"] for r in records])
        real_run = subprocess.run
        def no_render(command, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                raise AssertionError("must not render")
            return real_run(command, **kwargs)
        with mock.patch.object(preview_v2.subprocess, "run", side_effect=no_render):
            preview_v2.prepare_preview_v2(self.job)
            preview_v2.prepare_preview_v2(self.job, opening=OPTIONS)
            with self.assertRaises(preview_v2.PreviewV2Error):
                preview_v2.prepare_preview_v2(self.job, opening={**OPTIONS, "hold_frames": 24})
        self.approve_preview()
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        artifacts = delivery.manifest["artifacts"]
        self.assertEqual(artifacts["subtitles/subtitles.srt"]["source"]["path"], "11-preview/subtitles.srt")
        self.assertIn("plans/body-subtitles.webm", artifacts)
        self.assertNotIn("subtitles/subtitles.webm", artifacts)
        self.assertIn("opening-manifest.json", artifacts)
        self.assertEqual((delivery.directory / "subtitles/subtitles.srt").read_bytes(),
                         (directory / "subtitles.srt").read_bytes())
        with mock.patch.object(qa_delivery_v2, "_copy", side_effect=AssertionError("must not copy")):
            qa_delivery_v2.prepare_delivery_v2(self.job)

    def test_changed_shifted_srt_cannot_be_replayed(self):
        self.render()
        (self.job.job_dir / "11-preview/subtitles.srt").write_text(SRT)
        with self.assertRaises(state.WorkflowError):
            preview_v2.prepare_preview_v2(self.job)

    def test_missing_opening_manifest_cannot_fall_back_to_body_only(self):
        self.render()
        (self.job.job_dir / "11-preview/opening-manifest.json").unlink()
        with self.assertRaises(state.WorkflowError):
            preview_v2.prepare_preview_v2(self.job)

    def test_interrupted_preview_publication_can_rebuild_without_partial_opening(self):
        before = (self.job.job_dir / "workflow.json").read_bytes()
        with mock.patch.object(state, "save_job", side_effect=OSError("test before commit")):
            with self.assertRaises(OSError):
                self.render()
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())
        self.assertFalse((self.job.job_dir / "11-preview/opening-manifest.json").exists())
        result = self.render()
        self.assertIn("opening_manifest_sha256", result.qa_report)
        self.assertEqual(state.load_job(self.job.job_dir).stages["preview"]["status"], "ready_for_review")

    def test_pending_final_approval_resumes_once_and_rejects_changed_srt(self):
        from edit.hd.tools import delivery_approval, qa_delivery_v2
        self.render()
        self.approve_preview()
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        options = dict(expected_revision=self.job.revision,
                       delivery_sha256=delivery.manifest["final_sha256"],
                       user_confirmation="测试夹具：确认本次封面成片")
        with mock.patch.object(state, "save_job", side_effect=OSError("test interruption")):
            with self.assertRaises(OSError):
                delivery_approval.approve_delivery(self.job, **options)
        before = (self.job.job_dir / "workflow.json").read_bytes()
        srt = delivery.directory / "subtitles/subtitles.srt"
        approved_bytes = srt.read_bytes()
        srt.write_text(SRT)
        with self.assertRaises(state.WorkflowError):
            delivery_approval.approve_delivery(self.job, **options)
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())
        srt.write_bytes(approved_bytes)
        delivery_approval.approve_delivery(self.job, **options)
        revision = self.job.revision
        delivery_approval.approve_delivery(self.job, **options)
        self.assertEqual(revision, self.job.revision)

    def test_completion_audit_checks_final_timeline(self):
        from edit.hd.tools import delivery_approval, qa_delivery_v2
        self.render()
        self.approve_preview()
        delivery = qa_delivery_v2.prepare_delivery_v2(self.job)
        delivery_approval.approve_delivery(self.job, expected_revision=self.job.revision,
            delivery_sha256=delivery.manifest["final_sha256"],
            user_confirmation="测试夹具：审批时间轴审计")
        spec = importlib.util.spec_from_file_location("opening_completion_audit",
            SKILL / "scripts/audit_job_completion.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        probe = {"width": 1080, "height": 1920, "fps": 24, "rotation": 0,
                 "duration_seconds": 3.5, "audio_streams": 1}
        before = (self.job.job_dir / "workflow.json").read_bytes()
        with mock.patch.object(audit, "_probe_media", return_value=probe):
            result = audit.audit_job_completion(self.root)
            self.assertEqual(result["status"], "formal_complete", result)
        for changes in ({"duration_seconds": 3}, {"audio_streams": 0}):
            with self.subTest(changes=changes), mock.patch.object(
                    audit, "_probe_media", return_value={**probe, **changes}):
                result = audit.audit_job_completion(self.root)
                self.assertEqual(result["status"], "inconsistent", result)
        self.assertEqual(before, (self.job.job_dir / "workflow.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
