from __future__ import annotations

import copy
import contextlib
import io
import json
import multiprocessing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import contract_artifacts as artifacts, generation_queue as queue


def _claim_worker(job, request_id, config, start, results):
    # Only the already-tested startup gate is a fixture; file locking is real.
    with mock.patch.object(queue, "_approved", return_value=("synthetic", "config", config)):
        start.wait()
        results.put(queue.claim(job, request_id, 10))


def _retry_worker(job, plan, config, approval, start, results):
    with mock.patch.object(queue, "_approved", return_value=("synthetic", "config", config)):
        start.wait()
        result = queue.retry(job, plan, approval, artifacts.sha256_json(plan))
        results.put({"retry": result, "claim": queue.claim(job, result["id"], 10)})


class GenerationQueueTests(unittest.TestCase):
    def test_reference_upload_encodes_frozen_bytes_for_lovart(self):
        import base64
        from edit.hd.tools import generation_inputs
        source = self.job / "reference.png"
        source.write_bytes(b"actual frozen image bytes")
        bindings = artifacts.read_json_artifact(self.job / "manifests/generation-channels.json")
        bindings["video"].update(reference_mode="upload", upload={
            "tool": "mcp__lovart__upload_asset",
            "arguments": {"data_base64": {"$input": "base64"},
                          "filename": {"$input": "filename"}, "project_id": "synthetic-project"},
            "result_path": ["url"],
        })
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", bindings)
        request = self.request("reference-upload", "video")
        request["arguments"]["ref_images"] = [str(source)]
        request["input_files"] = [{"path": source.name, "sha256": artifacts.sha256_file(source),
                                   "bytes": source.stat().st_size}]
        action = generation_inputs.next_action(self.job, request)
        self.assertEqual(base64.b64decode(action["arguments"]["data_base64"]), source.read_bytes())
        self.assertEqual(action["arguments"]["filename"], source.name)
        self.assertEqual(generation_inputs.next_action(self.job, request)["status"], "input_upload_pending")
        generation_inputs.record_result(self.job, request, action, {"url": "https://example.test/reference.png"})
        self.assertEqual(generation_inputs.resolve_request(self.job, request)["arguments"]["ref_images"],
                         ["https://example.test/reference.png"])
        source.write_bytes(b"changed reference")
        with self.assertRaisesRegex(ValueError, "reference changed"):
            generation_inputs.resolve_request(self.job, request)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name).resolve()
        (self.job / "manifests").mkdir()
        self.config = {"max_concurrency": 2, "generation_enabled": True, "providers": [
            {"purpose": "image", "provider": "builtin", "endpoint_id": "image_gen.imagegen", "model": "builtin",
             "connection_status": "verified", "quota_status": "available"},
            {"purpose": "video", "provider": "Lovart", "endpoint_id": "mcp__lovart__generate_video", "model": "kling/kling-video-o1",
             "connection_status": "verified", "quota_status": "available"},
        ]}
        artifacts.write_json_artifact(self.job / "manifests/generation-channels.json", {
            "schema_version": 1,
            "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"},
            "video": {"model_binding": {"mode": "argument", "parameter": "model"}, "reference_mode": "local_path"},
        })
        self.gate = mock.patch.object(queue, "_approved", return_value=("synthetic", "config", self.config))
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def request(self, rid, purpose="image"):
        args = {"prompt": "synthetic input " + rid}
        if purpose == "video":
            args.update(model="kling/kling-video-o1", project_id="synthetic-project", duration=5)
        return {"id": rid, "purpose": purpose, "tool": next(p["endpoint_id"] for p in self.config["providers"] if p["purpose"] == purpose),
                "arguments": args, "input_files": []}

    def add(self, *requests):
        plan = {"requests": list(requests)}
        return queue.add(self.job, plan, "synthetic permission, not user approval", artifacts.sha256_json(plan))

    def complete(self, rid, token, purpose="image", queried=None):
        return queue.record(self.job, rid, token, {"status": "completed", "project_id": "synthetic-project"} |
                            ({"artifacts": [{"type": purpose, "url": "https://example.invalid/synthetic"}]}), queried)

    def test_real_processes_share_two_slots_then_refill(self):
        requests = [self.request("r" + str(i), "video" if i % 2 else "image") for i in range(4)]
        self.add(*requests)
        ctx = multiprocessing.get_context("fork")
        start, results = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_claim_worker, args=(self.job, r["id"], self.config, start, results)) for r in requests]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        answers = [results.get(timeout=2) for _ in processes]
        generated = [x for x in answers if x["action"] == "generate"]
        self.assertEqual(len(generated), 2)
        self.assertEqual(sum(x["status"] in queue.ACTIVE for x in queue.status(self.job)["items"].values()), 2)
        first = generated[0]
        item = queue.status(self.job)["items"][first["id"]]
        response = {"status": "completed", "artifacts": [{"type": item["request"]["purpose"], "url": "https://example.invalid/synthetic"}]}
        queue.record(self.job, first["id"], first["claim_token"], response)
        waiting = next(x["id"] for x in answers if x["action"] == "wait")
        self.assertEqual(queue.claim(self.job, waiting, 10)["action"], "generate")
        self.assertEqual(queue.claim(self.job, first["id"], 10)["action"], "blocked")

    def test_mixed_slots_pending_completion_poll_gate_and_recovery(self):
        self.add(self.request("image"), self.request("video", "video"), self.request("third"))
        image = queue.claim(self.job, "image")
        video = queue.claim(self.job, "video", 10)
        self.assertEqual(queue.claim(self.job, "third")["action"], "wait")
        response = {"status": "pending", "task_ids": ["synthetic-task"], "project_id": "synthetic-project", "poll_after_seconds": 10}
        queue.record(self.job, "video", video["claim_token"], response)
        self.assertTrue(queue.record(self.job, "video", video["claim_token"], response)["idempotent"])
        due = queue.status(self.job)["items"]["video"]["next_poll_at"]
        self.assertEqual(queue.poll(self.job, due - 1)["action"], "wait")
        group = queue.poll(self.job, due + 1)["groups"][0]
        self.assertEqual(group["task_ids"], ["synthetic-task"])
        self.assertEqual(queue.poll(self.job, due + 1)["action"], "wait")
        with self.assertRaises(queue.GenerationQueueError):
            self.complete("video", video["claim_token"], "video", ["wrong-task"])
        # Config drift blocks new generation, never collection of an existing result.
        with mock.patch.object(queue, "_approved", side_effect=queue.GenerationQueueError("changed")):
            self.complete("video", video["claim_token"], "video", ["synthetic-task"])
        completed = queue.status(self.job)["items"]["video"]
        self.assertEqual(completed["submission_response"], response)
        self.assertEqual(completed["completion_response"]["status"], "completed")
        self.assertEqual(queue.claim(self.job, "third")["action"], "generate")
        queue.record(self.job, "image", image["claim_token"], {"status": "unknown"})
        inspected = subprocess.run([sys.executable, "-m", "edit.hd.tools.generation_queue", "--job", str(self.job), "status"],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(inspected.stdout)["items"]["image"]["status"], "unknown")
        self.assertEqual(queue.claim(self.job, "image")["action"], "blocked")

    def test_id_content_and_cross_id_fingerprint_are_immutable(self):
        req = self.request("one")
        self.add(req)
        self.add(req)
        changed = copy.deepcopy(req)
        changed["arguments"]["prompt"] = "changed"
        with self.assertRaises(queue.GenerationQueueError):
            self.add(changed)
        changed = {**req, "id": "another"}
        with self.assertRaises(queue.GenerationQueueError):
            self.add(changed)

    def test_model_binding_rejects_wrong_argument_and_fixed_model(self):
        self.config["providers"][1]["provider"] = "Generic"
        self.config["providers"][1]["endpoint_id"] = "generic.video"
        video = self.request("video", "video")
        video["arguments"]["model"] = "model-B"
        with self.assertRaises(queue.GenerationQueueError):
            self.add(video)
        image = self.request("fixed")
        image["arguments"]["model"] = "unexpected"
        with self.assertRaises(queue.GenerationQueueError):
            self.add(image)
        correct = self.request("correct", "video")
        self.add(correct)
        self.assertEqual(queue.status(self.job)["items"]["correct"]["channel_identity"]["model"], "kling/kling-video-o1")
        missing = self.request("missing", "video")
        del missing["arguments"]["model"]
        with self.assertRaises(queue.GenerationQueueError):
            self.add(missing)

    def test_independent_cli_transmits_video_account_limit(self):
        import importlib.util
        entry = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/run_generation.py"
        spec = importlib.util.spec_from_file_location("run_generation_cli_test", entry)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        self.add(self.request("cli-video", "video"))
        argv = [str(entry), "--project-root", str(entry.parents[3]), "--job", str(self.job),
                "next", "--request-id", "cli-video", "--account-limit", "1"]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(queue.state, "load_job", return_value=SimpleNamespace(job_dir=self.job)), \
             contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["action"], "submit")
        self.assertEqual(result["arguments"]["model"], "kling/kling-video-o1")

    def test_input_drift_limit_failure_and_config_one(self):
        image = self.job / "reference.png"
        image.write_bytes(b"synthetic")
        req = self.request("one")
        req["arguments"]["referenced_image_paths"] = [str(image)]
        req["input_files"] = [{"path": image.name, "bytes": image.stat().st_size, "sha256": artifacts.sha256_file(image)}]
        self.add(req)
        image.write_bytes(b"changed")
        with self.assertRaises(queue.GenerationQueueError):
            queue.claim(self.job, "one")
        self.config["max_concurrency"] = 1
        self.add(self.request("video", "video"), self.request("two"))
        v = queue.claim(self.job, "video", 10)
        self.assertEqual(queue.claim(self.job, "two")["action"], "wait")
        queue.record(self.job, "video", v["claim_token"], {"status": "failed", "error": {"code": "CONCURRENCY_LIMIT"}})
        self.assertEqual(queue.claim(self.job, "two")["action"], "wait")
        self.assertEqual(queue.claim(self.job, "video", 10)["action"], "blocked")

    def test_startup_receives_loaded_job_not_a_path(self):
        loaded = mock.Mock(job_id="synthetic", root=self.job)
        (self.job / "job-context.json").write_text("{}")
        config_path = self.job / "provider-config.json"
        config_path.write_text(json.dumps(self.config))
        config_digest = artifacts.sha256_file(config_path)
        (self.job / "manifests/setup-approval.json").write_text(json.dumps({"provider_config_sha256": config_digest}))
        self.gate.stop()
        with mock.patch.object(queue.state, "load_job", return_value=loaded), \
             mock.patch.object(queue.startup, "require_startup") as gate, \
             mock.patch.object(queue.startup, "_config", return_value=(config_path, config_digest)):
            self.assertEqual(queue._approved(self.job)[0], "synthetic")
            gate.assert_called_once_with(loaded)
        self.gate.start()

    def test_completion_cannot_clear_rate_limit_without_permission(self):
        self.add(self.request("video", "video"), self.request("image"), self.request("next"))
        video = queue.claim(self.job, "video", 10)
        image = queue.claim(self.job, "image")
        queue.record(self.job, "video", video["claim_token"], {"status": "failed", "error": {"code": "CONCURRENCY_LIMIT"}})
        queue.record(self.job, "image", image["claim_token"], {"status": "completed", "artifacts": [{"type": "image", "url": "https://example.invalid/synthetic"}]})
        self.assertEqual(queue.claim(self.job, "next")["action"], "wait")
        with self.assertRaises(queue.GenerationQueueError):
            queue.resume(self.job, "")
        queue.resume(self.job, "synthetic explicit resume permission")
        self.assertEqual(queue.claim(self.job, "next")["action"], "generate")
        self.assertEqual(queue.claim(self.job, "video", 10)["action"], "blocked")


    def test_frozen_retry_preserves_predecessor_and_requires_a_new_decision(self):
        reference = self.job / "reference.png"
        reference.write_bytes(b"synthetic reference")
        req = self.request("video", "video")
        req["input_files"] = [{"path": reference.name, "bytes": reference.stat().st_size,
                               "sha256": artifacts.sha256_file(reference)}]
        self.add(req)
        original = queue.claim(self.job, "video", 10)
        queue.record(self.job, "video", original["claim_token"],
                     {"status": "pending", "task_ids": ["original-task"]})
        failed = {"status": "failed", "task_ids": ["original-task"], "error": {"code": "FAILED"}}
        queue.record(self.job, "video", original["claim_token"], failed, ["original-task"])
        predecessor = copy.deepcopy(queue.status(self.job)["items"]["video"])
        prepared = queue.prepare_retry(self.job, "video")
        plan, digest = prepared["plan"], prepared["plan_sha256"]
        self.assertEqual(prepared["request"], req)
        self.assertEqual(plan["failure_response_sha256"], artifacts.sha256_json(failed))
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, plan, "", digest)
        changed = {**plan, "count": 2}
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, changed, "synthetic retry decision", artifacts.sha256_json(changed))
        changed = {**plan, "from_id": "another"}
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, changed, "synthetic retry decision", digest)
        reference.write_bytes(b"changed reference")
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, plan, "synthetic retry decision", digest)
        reference.write_bytes(b"synthetic reference")
        with mock.patch.object(queue, "_approved", return_value=("synthetic", "changed config", self.config)):
            with self.assertRaises(queue.GenerationQueueError):
                queue.retry(self.job, plan, "synthetic retry decision", digest)
        child = queue.retry(self.job, plan, "synthetic retry decision", digest)
        self.assertFalse(child["idempotent"])
        self.assertEqual(child["plan_request_id"], "video")
        child_item = copy.deepcopy(queue.status(self.job)["items"][child["id"]])
        self.add(req, child_item["request"])
        self.assertEqual(queue.status(self.job)["items"][child["id"]], child_item)
        with self.assertRaises(queue.GenerationQueueError):
            self.add({**req, "id": "duplicate"})
        claimed = queue.claim(self.job, child["id"], 10)
        self.assertEqual(claimed["arguments"], original["arguments"])
        self.assertNotEqual(claimed["claim_token"], original["claim_token"])
        with self.assertRaises(queue.GenerationQueueError):
            queue.record(self.job, child["id"], original["claim_token"], failed)
        with self.assertRaises(queue.GenerationQueueError):
            queue.record(self.job, "video", original["claim_token"], {"status": "completed"})
        with self.assertRaises(queue.GenerationQueueError):
            queue.record(self.job, child["id"], claimed["claim_token"],
                         {"status": "pending", "task_ids": ["original-task"]})
        queue.record(self.job, child["id"], claimed["claim_token"],
                     {"status": "failed", "error": {"code": "FAILED_AGAIN"}})
        # Replaying permission cannot silently retarget the newest failure.
        replay = queue.retry(self.job, plan, "synthetic replay", digest)
        self.assertEqual(replay["id"], child["id"])
        self.assertTrue(replay["idempotent"])
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "video")
        next_plan = queue.prepare_retry(self.job, child["id"])
        with self.assertRaises(queue.GenerationQueueError):
            queue.retry(self.job, next_plan["plan"], "", next_plan["plan_sha256"])
        grandchild = queue.retry(self.job, next_plan["plan"], "synthetic separate new decision", next_plan["plan_sha256"])
        self.assertEqual(grandchild["retry_of"], child["id"])
        self.assertEqual(grandchild["plan_request_id"], "video")
        self.assertEqual(queue.status(self.job)["items"]["video"], predecessor)

    def test_concurrent_retry_decisions_create_and_claim_only_one_successor(self):
        self.add(self.request("video", "video"))
        original = queue.claim(self.job, "video", 10)
        queue.record(self.job, "video", original["claim_token"], {"status": "failed", "error": {"code": "FAILED"}})
        plan = queue.prepare_retry(self.job, "video")["plan"]
        ctx = multiprocessing.get_context("fork")
        start, results = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=_retry_worker,
                                 args=(self.job, plan, self.config, "synthetic decision " + str(i), start, results))
                     for i in range(2)]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        answers = [results.get(timeout=2) for _ in processes]
        self.assertEqual(len({x["retry"]["id"] for x in answers}), 1)
        self.assertEqual(sum(not x["retry"]["idempotent"] for x in answers), 1)
        self.assertEqual(sum(x["claim"]["action"] == "generate" for x in answers), 1)
        child = answers[0]["retry"]["id"]
        self.assertEqual(len(queue.status(self.job)["items"]), 2)
        claimed = next(x["claim"] for x in answers if x["claim"]["action"] == "generate")
        queue.record(self.job, child, claimed["claim_token"], {"status": "pending", "task_ids": ["retry-task"]})
        self.complete(child, claimed["claim_token"], "video", ["retry-task"])
        rows = queue.status(self.job)["items"]
        self.assertEqual(rows["video"]["status"], "failed")
        self.assertEqual(rows[child]["completion_response"]["status"], "completed")
        self.assertEqual(rows[child]["task_ids"], ["retry-task"])

    def test_paused_retry_and_not_found_keep_admission_closed(self):
        self.add(self.request("video", "video"), self.request("image"), self.request("next"))
        original = queue.claim(self.job, "video", 10)
        queue.record(self.job, "video", original["claim_token"],
                     {"status": "failed", "error": {"code": "CONCURRENCY_LIMIT"}})
        prepared = queue.prepare_retry(self.job, "video")
        child = queue.retry(self.job, prepared["plan"], "synthetic explicit resume and retry permission", prepared["plan_sha256"])
        self.assertTrue(queue.status(self.job)["paused"])
        self.assertEqual(queue.claim(self.job, child["id"], 10)["action"], "wait")
        queue.resume(self.job, "synthetic explicit resume and retry permission")
        claimed = queue.claim(self.job, child["id"], 10)
        image = queue.claim(self.job, "image")
        queue.record(self.job, "image", image["claim_token"], {"status": "unknown"})
        queue.record(self.job, child["id"], claimed["claim_token"],
                     {"status": "pending", "task_ids": ["missing-task"]})
        missing = {"status": "not_found", "task_ids": ["missing-task"]}
        self.assertEqual(queue.record(self.job, child["id"], claimed["claim_token"], missing, ["missing-task"])["status"], "unknown")
        item = queue.status(self.job)["items"][child["id"]]
        self.assertEqual(item["response"], missing)
        self.assertEqual(queue.poll(self.job, item["next_poll_at"] + 1000)["action"], "wait")
        self.assertEqual(queue.claim(self.job, "next")["action"], "wait")
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, child["id"])
        self.complete(child["id"], claimed["claim_token"], "video", ["missing-task"])
        self.assertEqual(queue.claim(self.job, "next")["action"], "generate")
        self.assertEqual(queue.status(self.job)["items"]["video"]["status"], "failed")

    def test_ambiguous_failure_and_nonfailed_states_cannot_be_retried(self):
        self.add(self.request("multi", "video"), self.request("partial", "video"),
                 self.request("moderated", "video"), self.request("completed", "video"))
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "multi")
        multi = queue.claim(self.job, "multi", 10)
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "multi")
        queue.record(self.job, "multi", multi["claim_token"], {"status": "pending", "task_ids": ["one", "two"]})
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "multi")
        queue.record(self.job, "multi", multi["claim_token"], {"status": "failed", "task_ids": ["one", "two"]}, ["one", "two"])
        self.assertEqual(queue.status(self.job)["items"]["multi"]["status"], "unknown")
        self.assertEqual(queue.poll(self.job, queue.status(self.job)["items"]["multi"]["next_poll_at"] + 1)["action"], "wait")
        partial = queue.claim(self.job, "partial", 10)
        queue.record(self.job, "partial", partial["claim_token"],
                     {"status": "failed", "artifacts": [{"type": "video", "url": "https://example.invalid/partial"}]})
        with self.assertRaises(queue.GenerationQueueError):
            queue.prepare_retry(self.job, "partial")
        self.complete("multi", multi["claim_token"], "video", ["one", "two"])
        for rid in ("moderated", "completed"):
            claimed = queue.claim(self.job, rid, 10)
            if rid == "completed":
                self.complete(rid, claimed["claim_token"], "video")
            else:
                queue.record(self.job, rid, claimed["claim_token"], {"status": "moderated"})
            with self.assertRaises(queue.GenerationQueueError):
                queue.prepare_retry(self.job, rid)


if __name__ == "__main__":
    unittest.main()
