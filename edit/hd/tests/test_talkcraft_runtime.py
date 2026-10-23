from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
import re

from edit.hd.tests.test_talkcraft_contract import brief
from edit.hd.tools import contract_artifacts, talkcraft_contract


RUNTIME = (
    Path(__file__).parents[1] / "integrations" / "talkcraft" / "runtime"
).resolve()


class TalkCraftDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("node") is None:
            raise unittest.SkipTest("Node is unavailable")
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_runtime_dispatch_index_is_the_unique_108_card_registry(self) -> None:
        registry_path = RUNTIME / "card-registry.json"
        script = """
import {readFile} from "node:fs/promises";
const {validateRegistrySnapshot} = await import(process.argv[2]);
const bytes = await readFile(process.argv[3]);
const result = validateRegistrySnapshot(bytes, {
  version: process.argv[4], sha256: process.argv[5],
});
process.stdout.write(JSON.stringify({count: result.cards.size}));
"""
        registry = talkcraft_contract.load_card_registry(registry_path)
        completed = subprocess.run(
            [
                "node", "--input-type=module", "-",
                (RUNTIME / "card-dispatch.mjs").as_uri(), str(registry_path),
                registry["registry_version"],
                contract_artifacts.sha256_file(registry_path),
            ],
            input=script, capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"count": 108})

    def test_pending_card_fails_before_renderer_or_output(self) -> None:
        registry_path = self.output / "pending-registry.json"
        registry = json.loads(
            (RUNTIME / "card-registry.json").read_text(encoding="utf-8")
        )
        pending = registry["cards"][0]["production"]
        pending["status"] = "pending_portrait_adapter"
        for key in (
            "derived_entrypoint",
            "implementation_sha256",
            "input_adapter_sha256",
            "adapter_version",
            "qualification_id",
        ):
            pending[key] = None
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        brief_path = self.output / "pending-brief.json"
        pending_brief = brief()
        pending_brief["registry"] = {
            "version": registry["registry_version"],
            "sha256": contract_artifacts.sha256_file(registry_path),
        }
        brief_path.write_text(json.dumps(pending_brief), encoding="utf-8")
        target = self.output / "must-not-exist.mov"
        script = """
const {resolveProductionCard} = await import(process.argv[2]);
await resolveProductionCard({
  briefPath: process.argv[3], registryPath: process.argv[4], runtimeRoot: process.argv[5],
});
"""
        completed = subprocess.run(
            [
                "node", "--input-type=module", "-",
                (RUNTIME / "card-dispatch.mjs").as_uri(),
                str(brief_path), str(registry_path), str(RUNTIME),
            ],
            input=script, cwd="/", capture_output=True, text=True,
            timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("[CARD_NOT_QUALIFIED]", completed.stderr)
        self.assertFalse(target.exists())

    def test_behind_text_title_geometry_rejects_changed_value_or_extra_field(self) -> None:
        runtime = self.output / "qualification-runtime"
        (runtime / "qualification-cases").mkdir(parents=True)
        (runtime / "src/cards").mkdir(parents=True)
        shutil.copy2(RUNTIME / "qualification-fixtures.json", runtime / "qualification-fixtures.json")
        for name in ("behind-text-title.tsx", "behind-text-title.contract.json"):
            shutil.copy2(RUNTIME / "src/cards" / name, runtime / "src/cards" / name)
        source = RUNTIME / "qualification-cases/behind-text-title.json"
        output = self.output / "must-not-render.mp4"
        script = """
const {run} = await import(process.argv[2]);
await run([
  "--probe-card", "behind-text-title", "--case", "contrast-a",
  "--alpha", "false", "--output", process.argv[4],
  "--browser", "/definitely/not/a/browser", "--runtime-root", process.argv[3],
], {runtimeRoot: process.argv[3]});
"""
        for field, value in (("width", 541), ("extra", 1)):
            with self.subTest(field=field):
                candidate = json.loads(source.read_text(encoding="utf-8"))
                candidate["cases"][0]["measurement"]["source_size"][field] = value
                (runtime / "qualification-cases/behind-text-title.json").write_text(
                    json.dumps(candidate), encoding="utf-8"
                )
                completed = subprocess.run(
                    ["node", "--input-type=module", "-", (RUNTIME / "render-core.mjs").as_uri(), str(runtime), str(output)],
                    input=script, capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("qualification candidate contract is invalid", completed.stderr)
                self.assertFalse(output.exists())

    def test_parallel_items_production_mapping_rejects_fallback_inputs(self) -> None:
        module = self.output / "production-input.mjs"
        bundled = subprocess.run(
            [
                str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                str(RUNTIME / "src" / "production-input.ts"),
                "--bundle", "--platform=node", "--format=esm",
                f"--outfile={module}",
            ],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const {buildProductionProps} = await import(process.argv[2]);
const medium = (index) => ({
  source_kind: index === 0 ? "presenter" : "local_material",
  width: index === 0 ? 540 : 1200, height: index === 0 ? 600 : 750,
  fps: 24, start_frame: 0, end_frame: 530,
  job_path: index === 0 ? "inputs/presenter.webm" : `inputs/item-${index}.jpg`,
});
const base = {
  card_id: "parallel-items-with-host",
  text: {display: "三个重点", spoken: "并列展开"},
  frame_scope: {global_start_frame: 0, global_end_frame: 530},
  events: [{type: "text", payload: {text: "并列展开"}}],
  media: [0,1,2,3].map(medium), style: {theme: "apple-dark"},
};
const staged = [0,1,2,3].map((index) => ({mediaRef: `media-${index}`, publicSrc: `production/${"a".repeat(64)}${index ? ".jpg" : ".webm"}`}));
const rejected = [];
for (const [name, value] of [
  ["unknown-theme", {...base, style: {theme: "brand-fallback"}}],
  ["shifted-presenter", {...base, media: base.media.map((item, index) => index ? item : {...item, start_frame: 1})}],
  ["missing-item", {...base, media: base.media.slice(0, 3)}],
]) { try { buildProductionProps(value, staged); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({rejected, good: buildProductionProps(base, staged)}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["rejected"], ["unknown-theme", "shifted-presenter", "missing-item"])
        self.assertEqual(
            [item["slot"] for item in result["good"]["sceneInputs"]],
            ["presenter", "item-1", "item-2", "item-3"],
        )

    def test_multi_media_cards_bind_every_real_media_slot_into_the_core(self) -> None:
        configurations = (
            ("filmstrip-conveyor", 192, [f"item-{index}" for index in range(1, 7)], 2),
            ("gallery-wall-dolly", 207, [f"item-{index}" for index in range(1, 4)], 1),
            ("split-compare-slider", 237, ["before", "after"], 1),
            ("stack-fan-out", 163, [f"item-{index}" for index in range(1, 6)], 1),
            ("timeline-photo-strip", 238, [f"item-{index}" for index in range(1, 5)], 1),
        )
        for card_id, duration, image_slots, core_render_count in configurations:
            with self.subTest(card_id=card_id):
                adapter_module = self.output / f"{card_id}-adapter.mjs"
                bundled = subprocess.run(
                    [
                        str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                        str(RUNTIME / "src" / "production-adapters" / f"{card_id}.ts"),
                        "--bundle", "--platform=node", "--format=esm",
                        f"--outfile={adapter_module}",
                    ],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(bundled.returncode, 0, bundled.stderr)
                adapter_script = r"""
const {default: adapt} = await import(process.argv[2]);
const cardId = process.argv[3], duration = Number(process.argv[4]), imageCount = Number(process.argv[5]);
const media = [{source_kind:"presenter",width:540,height:600,fps:24,start_frame:0,end_frame:duration,job_path:"inputs/presenter.webm"}];
for (let i=1;i<=imageCount;i++) media.push({source_kind:"local_material",width:1200,height:750,fps:24,start_frame:0,end_frame:duration,job_path:`inputs/item-${i}.jpg`});
const base = {card_id:cardId,text:{display:"真实素材",spoken:"逐项进入核心"},frame_scope:{global_start_frame:0,global_end_frame:duration},events:[{anchor_id:"subtitle",type:"text",frame:8,payload:{text:"逐项进入核心"}}],media,style:{theme:"apple-dark"}};
const staged = media.map((_,i)=>({mediaRef:`media-${i}`,publicSrc:`production/${String(i).padStart(64,"a")}${i?".jpg":".webm"}`}));
const rejected=[];
for (const [name, brief, stagedInput] of [
  ["missing-image", {...base,media:media.slice(0,-1)}, staged.slice(0,-1)],
  ["wrong-kind", {...base,media:media.map((item,i)=>i===1?{...item,source_kind:"presenter"}:item)}, staged],
  ["zero-width", {...base,media:media.map((item,i)=>i===1?{...item,width:0}:item)}, staged],
  ["payload-extra", {...base,events:[{...base.events[0],payload:{text:"逐项进入核心",rawProps:{}}}]}, staged],
]) { try { adapt(brief,stagedInput); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good:adapt(base,staged),rejected}));
"""
                completed = subprocess.run(
                    ["node", "--input-type=module", "-", adapter_module.as_uri(), card_id, str(duration), str(len(image_slots))],
                    input=adapter_script, capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result["rejected"], ["missing-image", "wrong-kind", "zero-width", "payload-extra"])
                self.assertEqual(
                    [item["slot"] for item in result["good"]["sceneInputs"]],
                    ["presenter", *image_slots],
                )

                shim = self.output / f"{card_id}-media-remotion-shim.tsx"
                shim.write_text(
                    f'import React from {json.dumps(str(RUNTIME / "node_modules" / "react" / "index.js"))};\n' + '''
export const AbsoluteFill = (props) => <div {...props}/>;
export const Img = (props) => <img {...props}/>;
export const useCurrentFrame = () => 72;
''',
                    encoding="utf-8",
                )
                render_entry = self.output / f"{card_id}-media-entry.tsx"
                nodes = ",".join(f'{json.dumps(slot)}:<span data-media-slot={json.dumps(slot)}/>' for slot in ["presenter", *image_slots])
                render_entry.write_text(
                    f'''import React from {json.dumps(str(RUNTIME / "node_modules" / "react" / "index.js"))};
import {{renderToStaticMarkup}} from {json.dumps(str(RUNTIME / "node_modules" / "react-dom" / "server.node.js"))};
import Card, {{prepareCard}} from {json.dumps(str(RUNTIME / "src" / "cards" / f"{card_id}.tsx"))};
const context={{width:1080,height:1920,fps:24,durationInFrames:{duration}}};
const prepared=prepareCard({{title:"真实素材",subtitle:"逐项进入核心",accent:"#007AFF"}},context);
export const markup=renderToStaticMarkup(<Card prepared={{prepared}} sceneInputs={{{{{nodes}}}}}/>);
''',
                    encoding="utf-8",
                )
                render_module = self.output / f"{card_id}-media-render.cjs"
                rendered_bundle = subprocess.run(
                    [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(render_entry), "--bundle", "--platform=node", "--format=cjs", f"--alias:remotion={shim}", f"--outfile={render_module}"],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(rendered_bundle.returncode, 0, rendered_bundle.stderr)
                rendered = subprocess.run(
                    ["node", "-e", f"process.stdout.write(require({json.dumps(str(render_module))}).markup)"],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                for slot in ["presenter", *image_slots]:
                    expected = 1 if slot == "presenter" else core_render_count
                    self.assertEqual(rendered.stdout.count(f'data-media-slot="{slot}"'), expected)

    def test_split_60_40_binds_real_video_into_the_core(self) -> None:
        adapter_module = self.output / "split-60-40-story-adapter.mjs"
        bundled = subprocess.run(
            [
                str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                str(RUNTIME / "src" / "production-adapters" / "split-60-40-story.ts"),
                "--bundle", "--platform=node", "--format=esm", f"--outfile={adapter_module}",
            ],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        adapter_script = r'''
const {default: adapt} = await import(process.argv[2]);
const duration=173;
const media=[
  {source_kind:"presenter",width:540,height:600,fps:24,start_frame:0,end_frame:duration,job_path:"inputs/presenter.webm"},
  {source_kind:"local_material",width:960,height:540,fps:24,start_frame:0,end_frame:duration,job_path:"inputs/subject.webm"},
];
const base={card_id:"split-60-40-story",text:{display:"核心故事",spoken:"三项结果"},frame_scope:{global_start_frame:0,global_end_frame:duration},events:[{anchor_id:"subtitle",type:"text",frame:8,payload:{text:"三项结果"}}],media,style:{theme:"apple-dark"}};
const staged=media.map((_,i)=>({mediaRef:`media-${i}`,publicSrc:`production/${String(i).padStart(64,"a")}.webm`}));
const rejected=[];
for(const [name,brief,stagedInput] of [
  ["missing-video",{...base,media:media.slice(0,1)},staged.slice(0,1)],
  ["wrong-kind",{...base,media:[media[0],{...media[1],source_kind:"presenter"}]},staged],
  ["zero-width",{...base,media:[media[0],{...media[1],width:0}]},staged],
  ["payload-extra",{...base,events:[{...base.events[0],payload:{text:"三项结果",rawProps:{}}}]},staged],
]){try{adapt(brief,stagedInput)}catch{rejected.push(name)}}
process.stdout.write(JSON.stringify({good:adapt(base,staged),rejected}));
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "-", adapter_module.as_uri()], input=adapter_script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["rejected"], ["missing-video", "wrong-kind", "zero-width", "payload-extra"])
        self.assertEqual([item["slot"] for item in result["good"]["sceneInputs"]], ["presenter", "subject-video"])
        self.assertEqual(result["good"]["sceneInputs"][1]["kind"], "video-cover")

        shim = self.output / "split-60-40-story-remotion-shim.tsx"
        shim.write_text(
            f'import React from {json.dumps(str(RUNTIME / "node_modules" / "react" / "index.js"))};\n' + '''
export const AbsoluteFill = (props) => <div {...props}/>;
export const Loop = (props) => <div {...props}/>;
export const OffthreadVideo = (props) => <video {...props}/>;
export const useCurrentFrame = () => 72;
''',
            encoding="utf-8",
        )
        render_entry = self.output / "split-60-40-story-media-entry.tsx"
        render_entry.write_text(
            f'''import React from {json.dumps(str(RUNTIME / "node_modules" / "react" / "index.js"))};
import {{renderToStaticMarkup}} from {json.dumps(str(RUNTIME / "node_modules" / "react-dom" / "server.node.js"))};
import Card, {{prepareCard}} from {json.dumps(str(RUNTIME / "src" / "cards" / "split-60-40-story.tsx"))};
const prepared=prepareCard({{title:"核心故事",subtitle:"三项结果",accent:"#007AFF"}},{{width:1080,height:1920,fps:24,durationInFrames:173}});
export const markup=renderToStaticMarkup(<Card prepared={{prepared}} sceneInputs={{{{presenter:<span data-media-slot="presenter"/>,"subject-video":<span data-media-slot="subject-video"/>}}}}/>);
''',
            encoding="utf-8",
        )
        render_module = self.output / "split-60-40-story-media-render.cjs"
        rendered_bundle = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(render_entry), "--bundle", "--platform=node", "--format=cjs", f"--alias:remotion={shim}", f"--outfile={render_module}"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(rendered_bundle.returncode, 0, rendered_bundle.stderr)
        rendered = subprocess.run(
            ["node", "-e", f"process.stdout.write(require({json.dumps(str(render_module))}).markup)"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(rendered.stdout.count('data-media-slot="presenter"'), 1)
        self.assertEqual(rendered.stdout.count('data-media-slot="subject-video"'), 1)

    def test_batch_30_blocked_cards_bind_inputs_into_their_core_effects(self) -> None:
        expected_bindings = {
            "bed-echo-blur": ('mediaNode={sceneInputs["subject-image"]}', "title={[prepared.title", "note={prepared.items"),
            "chapter-progress-list": ("accent={prepared.accent}",),
            "chat-gpt": ('mediaNode={sceneInputs["subject-image"]}', "title={prepared.title}", "accent={prepared.accent}"),
            "chat-message-flow": ('mediaNode={sceneInputs["subject-image"]}', "title={prepared.title}", "accent={prepared.accent}"),
            "chip-grid-single-select": ("p.items.map",),
            "claude-code": ('mediaNode={sceneInputs["subject-image"]}', "title={prepared.title}", "accent={prepared.accent}"),
            "cursor-actor-demo": ('mediaNode={sceneInputs["subject-image"]}', "title={prepared.title}"),
            "evidence-scroll-tour": ('mediaNode={sceneInputs["subject-image"]}', "detail={prepared.detail}"),
            "glass-code-walk": ('mediaNode={sceneInputs["subject-image"]}', "title={prepared.title}"),
        }
        for card_id, bindings in expected_bindings.items():
            with self.subTest(card_id=card_id):
                source = (RUNTIME / "src" / "cards" / f"{card_id}.tsx").read_text(encoding="utf-8")
                for binding in bindings:
                    self.assertIn(binding, source)

    def test_batch_30_production_adapters_accept_exact_core_input_and_reject_bypass(self) -> None:
        card_ids = (
            "alt-block-lines", "bar-chart-growth", "bed-echo-blur", "behind-text-title",
            "black-slam-transition", "callout-line-label", "caret-wipe-transition",
            "chapter-progress-list", "chapter-title-card", "chart-grow", "chat-gpt",
            "chat-message-flow", "chip-grid-single-select", "claude-code",
            "color-slam-beat-card", "converging-arrows", "corner-bracket-frame",
            "count-badge-title", "countdown-arc-scatter", "crash-zoom-punch",
            "cursor-actor-demo", "cursor-locked-zoom", "danmu-bubble-praise",
            "doc-park-left-pill-deal", "douyin-follow-card", "error-retype",
            "evidence-scroll-tour", "flying-words", "focus-dim-spotlight",
            "glass-code-walk",
        )
        primary_paths = {
            "alt-block-lines": ("lines", 0), "bar-chart-growth": ("title",),
            "bed-echo-blur": ("title",), "behind-text-title": ("title_lines", 0),
            "black-slam-transition": ("labelB",),
            "callout-line-label": ("annotations", 0, "title"),
            "chapter-title-card": ("chapters", 0, "name"),
            "count-badge-title": ("number",), "countdown-arc-scatter": ("pick",),
            "crash-zoom-punch": ("label",), "converging-arrows": ("text",),
            "error-retype": ("prefix",), "flying-words": ("words", 0),
        }
        aggregator = self.output / "batch-30-adapters.ts"
        imports = [
            f'import a{index} from {json.dumps(str(RUNTIME / "src" / "production-adapters" / f"{card_id}.ts"))};'
            for index, card_id in enumerate(card_ids)
        ]
        exports = ",".join(f'{json.dumps(card_id)}:a{index}' for index, card_id in enumerate(card_ids))
        aggregator.write_text("\n".join(imports) + f"\nexport default {{{exports}}};\n", encoding="utf-8")
        module = self.output / "batch-30-adapters.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(aggregator),
             "--bundle", "--platform=node", "--format=esm", f"--outfile={module}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        fixtures = json.loads((RUNTIME / "qualification-fixtures.json").read_text(encoding="utf-8"))
        fixture_by_id = {item["asset_id"]: item for item in fixtures["assets"]}
        payloads = []
        for card_id in card_ids:
            case_set = json.loads((RUNTIME / "qualification-cases" / f"{card_id}.json").read_text(encoding="utf-8"))
            case = case_set["cases"][0]
            duration = case["duration_frames"]
            raw = case["raw"]
            current = raw
            for key in primary_paths.get(card_id, ("title",)):
                current = current[key]
            media = []
            staged = []
            for index, binding in enumerate(case["scene_inputs"]):
                fixture = fixture_by_id[binding["fixture_id"]]
                suffix = Path(fixture["source"]).suffix
                width = fixture.get("width", 960)
                height = fixture.get("height", 540)
                media.append({
                    "source_kind": "presenter" if binding["kind"] == "presenter-alpha" else "local_material",
                    "width": width, "height": height, "fps": 24,
                    "start_frame": 0, "end_frame": duration,
                    "job_path": f"inputs/media-{index}{suffix}",
                })
                staged.append({
                    "mediaRef": f"media-{index}",
                    "publicSrc": f"production/{fixture['sha256']}{suffix}",
                })
            payloads.append({
                "card_id": card_id, "duration": duration, "raw": raw, "primary": current,
                "media": media, "staged": staged,
                "slots": [binding["slot"] for binding in case["scene_inputs"]],
            })
        payload_path = self.output / "batch-30-adapters.json"
        payload_path.write_text(json.dumps(payloads, ensure_ascii=False), encoding="utf-8")
        script = r"""
import {readFileSync} from "node:fs";
const adapters = (await import(process.argv[2])).default;
const payloads = JSON.parse(readFileSync(process.argv[3], "utf8"));
for (const item of payloads) {
  const brief = {
    card_id: item.card_id,
    text: {display: item.primary, spoken: "生产输入验收"},
    frame_scope: {global_start_frame: 0, global_end_frame: item.duration},
    events: [{anchor_id: "core-input", type: "data", frame: 0, payload: {raw: item.raw}}],
    media: item.media,
    style: {theme: "apple-light"},
  };
  const result = adapters[item.card_id](brief, item.staged);
  if (result.cardId !== item.card_id || result.durationInFrames !== item.duration ||
      JSON.stringify(result.raw) !== JSON.stringify(item.raw) ||
      result.sceneInputs.map((entry) => entry.slot).join(",") !== item.slots.join(",")) {
    throw new Error(`valid mapping failed: ${item.card_id}`);
  }
  const mutations = [
    (value) => value.events.push({...value.events[0], anchor_id: "bypass"}),
    (value) => { value.events[0].payload.raw = {...value.events[0].payload.raw, sceneInputs: []}; },
  ];
  if (brief.media.length) mutations.push(
    (value) => { value.media[0] = {...value.media[0], start_frame: 1}; },
  );
  for (const mutate of mutations) {
    const invalidBrief = structuredClone(brief);
    mutate(invalidBrief);
    let rejected = false;
    try { adapters[item.card_id](invalidBrief, item.staged); } catch { rejected = true; }
    if (!rejected) {
      throw new Error(`bypass accepted: ${item.card_id}`);
    }
  }
}
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", str(module), str(payload_path)],
            input=script, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_presenter_identity_adapters_bind_core_text_and_reject_raw_props(self) -> None:
        for card_id, duration in (
            ("lower-third-nameplate", 86),
            ("chevron-lower-third", 86),
            ("host-card-glass-board", 168),
            ("host-shrink-to-chip", 91),
            ("info-card-assemble", 173),
            ("word-relay-filmstrip", 163),
        ):
            with self.subTest(card_id=card_id):
                module = self.output / f"{card_id}.mjs"
                bundled = subprocess.run(
                    [
                        str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                        str(RUNTIME / "src" / "production-adapters" / f"{card_id}.ts"),
                        "--bundle", "--platform=node", "--format=esm",
                        f"--outfile={module}",
                    ],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(bundled.returncode, 0, bundled.stderr)
                script = r"""
const {default: adapt} = await import(process.argv[2]);
const cardId = process.argv[3];
const brief = {
  card_id: cardId, text: {display: "林工", spoken: "AI内容导演"},
  frame_scope: {global_start_frame: 0, global_end_frame: Number(process.argv[4])},
  events: [{anchor_id: "identity", type: "data", frame: 10, payload: {role: "AI内容导演"}}],
  media: [{source_kind: "presenter", width: 540, height: 600, fps: 24,
    start_frame: 0, end_frame: Number(process.argv[4]), job_path: "inputs/presenter.webm"}],
  style: {theme: "apple-dark"},
};
const staged = [{mediaRef: "media-0", publicSrc: `production/${"a".repeat(64)}.webm`}];
const good = adapt(brief, staged);
let rejected = false;
try {
  adapt({...brief, events: [{...brief.events[0], payload: {role: "AI内容导演", rawProps: {}}}]}, staged);
} catch { rejected = true; }
let rejectedSize = false;
try {
  adapt({...brief, media: [{...brief.media[0], width: 0}]}, staged);
} catch { rejectedSize = true; }
process.stdout.write(JSON.stringify({good, rejected, rejectedSize}));
"""
                completed = subprocess.run(
                    ["node", "--input-type=module", "-", module.as_uri(), card_id, str(duration)],
                    input=script, capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertTrue(result["rejected"])
                if card_id in {
                    "host-card-glass-board",
                    "host-shrink-to-chip",
                    "info-card-assemble",
                    "word-relay-filmstrip",
                }:
                    self.assertTrue(result["rejectedSize"])
                self.assertEqual(result["good"]["cardId"], card_id)
                self.assertEqual(result["good"]["raw"], {
                    "title": "林工", "subtitle": "AI内容导演", "accent": "#007AFF",
                })
                self.assertEqual(
                    [item["slot"] for item in result["good"]["sceneInputs"]],
                    ["presenter"],
                )

                shim = self.output / f"{card_id}-remotion-shim.tsx"
                shim.write_text(
                    f'import React from {json.dumps(str(RUNTIME / "node_modules" / "react" / "index.js"))};\n' + '''
export const AbsoluteFill = (props) => <div {...props}/>;
export const Img = (props) => <img {...props}/>;
export const Loop = (props) => <div {...props}/>;
export const OffthreadVideo = (props) => <video {...props}/>;
export const useCurrentFrame = () => 24;
''',
                    encoding="utf-8",
                )
                render_entry = self.output / f"{card_id}-render-entry.tsx"
                card_path = RUNTIME / "src" / "cards" / f"{card_id}.tsx"
                render_entry.write_text(
                    f'''import React from {json.dumps(str(RUNTIME / "node_modules" / "react" / "index.js"))};
import {{renderToStaticMarkup}} from {json.dumps(str(RUNTIME / "node_modules" / "react-dom" / "server.node.js"))};
import Card, {{prepareCard}} from {json.dumps(str(card_path))};
const context = {{width:1080,height:1920,fps:24,durationInFrames:{duration}}};
export const renderCard = (raw, presenterId) => renderToStaticMarkup(
  <Card prepared={{prepareCard(raw, context)}} sceneInputs={{{{presenter:<div data-presenter-id={{presenterId}}/>}}}}/>
);
''',
                    encoding="utf-8",
                )
                render_module = self.output / f"{card_id}-render.cjs"
                rendered_bundle = subprocess.run(
                    [
                        str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                        str(render_entry), "--bundle", "--platform=node", "--format=cjs",
                        f"--alias:remotion={shim}", f"--outfile={render_module}",
                    ],
                    cwd=RUNTIME,
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(rendered_bundle.returncode, 0, rendered_bundle.stderr)
                render_script = r"""
const {renderCard} = await import(process.argv[2]);
const a = renderCard({title:"林工",subtitle:"AI内容导演",accent:"#007AFF"}, "presenter-a");
const b = renderCard({title:"陈知远",subtitle:"内容系统顾问",accent:"#FF2D55"}, "presenter-b");
process.stdout.write(JSON.stringify({a,b}));
"""
                rendered = subprocess.run(
                    ["node", "--input-type=module", "-", render_module.as_uri()],
                    input=render_script, capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                markup = json.loads(rendered.stdout)
                for expected in ("林工", "AI内容导演", "#007aff", "presenter-a"):
                    self.assertIn(expected.lower(), markup["a"].lower())
                for expected in ("陈知远", "内容系统顾问", "#ff2d55", "presenter-b"):
                    self.assertIn(expected.lower(), markup["b"].lower())
                self.assertNotEqual(markup["a"], markup["b"])

    def test_business_registry_is_not_part_of_common_runtime_closure(self) -> None:
        manifest = json.loads(
            (RUNTIME / "closure-manifest.json").read_text(encoding="utf-8")
        )
        paths = {record["path"] for record in manifest["files"]}
        self.assertIn("card-dispatch.mjs", paths)
        self.assertNotIn("card-registry.json", paths)
        self.assertFalse(any(path.startswith("src/cards/") for path in paths))

    def test_foundation_contract_matches_the_pinned_upstream_inventory(self) -> None:
        contract = json.loads(
            (RUNTIME / "foundation-contract.json").read_text(encoding="utf-8")
        )
        upstream = json.loads(
            (RUNTIME.parent / "upstream-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(contract["backdrops"], upstream["auxiliary"]["backdrops"]["ids"])
        self.assertEqual(contract["frames"], upstream["auxiliary"]["video_frames"]["ids"])
        self.assertEqual(contract["source_frames"], [0, 24, 48])

    def test_unknown_foundation_fails_before_browser_or_output(self) -> None:
        target = self.output / "unknown-foundation.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-foundation", "unknown",
                "--alpha", "false",
                "--output", str(target),
                "--browser", "/definitely/not/a/browser",
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("probe foundation is invalid", completed.stderr)
        self.assertNotIn("browser is unavailable", completed.stderr)
        self.assertFalse(target.exists())

    def test_scene_foundation_contract_fixes_theme_planes_camera_and_budgets(self) -> None:
        contract = json.loads(
            (RUNTIME / "scene-foundation-contract.json").read_text(encoding="utf-8")
        )
        token_keys = {
            "canvas", "canvas_alt", "ink", "ink_muted", "hairline",
            "accent", "positive", "negative", "marker",
        }
        self.assertEqual(contract["schema_version"], "talkcraft-scene-foundation/v1")
        self.assertEqual(set(contract["themes"]["light"]), token_keys)
        self.assertEqual(set(contract["themes"]["dark"]), token_keys)
        self.assertEqual(
            contract["plane_order"],
            ["background.screen", "background.world", "subject.world", "text.screen"],
        )
        self.assertEqual(contract["safe_lines"], {
            "critical_text_max_y": 1700, "decoration_max_y": 1800,
        })
        self.assertEqual(contract["budgets"], {
            "active_subject_groups_max": 3,
            "hero_groups_max": 1,
            "demoted_groups_max": 1,
        })
        self.assertEqual(contract["camera"]["directions"], ["push", "pull"])
        self.assertEqual(contract["camera"]["end_overshoot_frames"], 24)

    def test_unknown_scene_probe_fails_before_browser_or_output(self) -> None:
        target = self.output / "unknown-scene.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-scene", "unknown",
                "--alpha", "false",
                "--output", str(target),
                "--browser", "/definitely/not/a/browser",
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("probe scene is invalid", completed.stderr)
        self.assertNotIn("browser is unavailable", completed.stderr)
        self.assertFalse(target.exists())

    def test_text_layout_contract_requires_real_measurement_and_no_clipping(self) -> None:
        contract = json.loads(
            (RUNTIME / "text-layout-contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(contract["schema_version"], "talkcraft-text-layout/v1")
        self.assertEqual(contract["allowed_plane"], "text.screen")
        self.assertEqual(contract["measurement"], "rendered-node-dom-range-and-scroll")
        self.assertEqual(contract["overflow_policy"], "reject")
        self.assertEqual(
            contract["forbidden_clipping"],
            ["hidden", "clip", "ellipsis", "line-clamp"],
        )
        self.assertEqual(contract["measurement_scope"], "public-static-dom-text-only")

    def test_unknown_text_layout_probe_fails_before_browser_or_output(self) -> None:
        target = self.output / "unknown-text-layout.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-text-layout", "unknown",
                "--alpha", "false",
                "--output", str(target),
                "--browser", "/definitely/not/a/browser",
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("probe text layout is invalid", completed.stderr)
        self.assertNotIn("browser is unavailable", completed.stderr)
        self.assertFalse(target.exists())

    def test_time_domain_contract_is_explicit_and_not_connected_to_production(self) -> None:
        contract = json.loads(
            (RUNTIME / "time-domain-contract.json").read_text(encoding="utf-8")
        )
        runtime_contract = json.loads(
            (RUNTIME / "runtime-contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(contract["schema_version"], "talkcraft-time-domain/v1")
        self.assertEqual(contract["timeline_fps"], 24)
        self.assertEqual(contract["frame_intervals"], "half-open")
        self.assertEqual(contract["seconds_input"], "finite-non-negative-timestamp")
        self.assertEqual(contract["seconds_to_frame_quantization"], "round-half-even")
        self.assertEqual(contract["anchor_policy"]["unknown"], "reject")
        self.assertIsNone(contract["anchor_policy"]["fallback_frame"])
        self.assertEqual(contract["media_policy"]["supported_source_timebase"], "cfr")
        self.assertEqual(contract["playback_bridge"]["supported_playback_rates"], [1])
        self.assertEqual(contract["playback_bridge"]["supported_source_fps"], "positive-integer-cfr")
        self.assertEqual(contract["playback_bridge"]["source_start_alignment"], "exact-composition-frame")
        self.assertFalse(contract["production_brief_connected"])
        self.assertEqual(runtime_contract["time_domain"]["media_mapping"], "explicit-cfr-only")
        self.assertEqual(
            runtime_contract["time_domain"]["media_playback"],
            "offthread-video-integer-cfr-rate-1-aligned-source-start",
        )
        self.assertFalse(runtime_contract["time_domain"]["production_brief_connected"])

    def test_time_domain_media_fixture_has_the_pinned_cfr_identity(self) -> None:
        contract = json.loads(
            (RUNTIME / "time-domain-contract.json").read_text(encoding="utf-8")
        )
        expected = contract["playback_bridge"]["verified_fixture"]
        fixture = RUNTIME / expected["path"]
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), expected["sha256"])
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_streams", "-of", "json",
                str(fixture),
            ],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        streams = json.loads(completed.stdout)["streams"]
        video = next(item for item in streams if item["codec_type"] == "video")
        self.assertEqual(
            {key: video[key] for key in ("codec_name", "pix_fmt", "width", "height", "r_frame_rate", "avg_frame_rate", "nb_frames")},
            {"codec_name": "h264", "pix_fmt": "yuv420p", "width": 180, "height": 320, "r_frame_rate": "20/1", "avg_frame_rate": "20/1", "nb_frames": "90"},
        )
        self.assertFalse(any(item["codec_type"] == "audio" for item in streams))

    def test_unknown_time_domain_probe_fails_before_browser_or_output(self) -> None:
        target = self.output / "unknown-time-domain.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-time-domain", "unknown",
                "--alpha", "false",
                "--output", str(target),
                "--browser", "/definitely/not/a/browser",
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("probe time domain is invalid", completed.stderr)
        self.assertNotIn("browser is unavailable", completed.stderr)
        self.assertFalse(target.exists())

    def test_determinism_contract_and_dependencies_are_exact(self) -> None:
        contract = json.loads((RUNTIME / "determinism-contract.json").read_text(encoding="utf-8"))
        runtime = json.loads((RUNTIME / "runtime-contract.json").read_text(encoding="utf-8"))
        package = json.loads((RUNTIME / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["schema_version"], "talkcraft-determinism/v1")
        self.assertEqual(contract["timeline_fps"], 24)
        self.assertEqual(contract["animation_time_domain"], "resolved-animation-local-frame")
        self.assertEqual(contract["lead_compensation"], "bridge-only-once")
        self.assertEqual(contract["animejs"], {
            "version": "4.5.0", "clock": "external-frame-seek", "autoplay": False,
            "default_main_loop": False, "pause_on_document_hidden": False,
            "initial_dom_target_visibility": "hidden-until-first-seek",
        })
        self.assertEqual(contract["three"]["chromium_gl"], "angle")
        self.assertEqual(contract["three"]["scene_camera_owner"], "scene-foundation-only")
        self.assertEqual(contract["probe"], {
            "animation_local_frames": [0, 24, 47], "scene_global_start": 48,
            "sample_orders": ["sequential", "shuffled"],
        })
        self.assertFalse(contract["production_brief_connected"])
        self.assertEqual(package["dependencies"]["animejs"], "4.5.0")
        self.assertEqual(package["dependencies"]["three"], "0.186.0")
        self.assertEqual(package["devDependencies"]["@types/three"], "0.186.0")
        self.assertEqual(runtime["runtime_version"], "0.9.0")
        self.assertFalse(runtime["determinism"]["production_brief_connected"])
        owned_sources = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted((RUNTIME / "src").glob("**/*"))
            if path.suffix in {".ts", ".tsx"}
        )
        executable_sources = re.sub(
            r"/\*[\s\S]*?\*/|//[^\n]*", "", owned_sources
        )
        self.assertNotIn("Math.random", executable_sources)
        self.assertNotRegex(executable_sources, r"\banimation\s*:")

    def test_unknown_determinism_probe_fails_before_browser_or_output(self) -> None:
        target = self.output / "unknown-determinism.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-determinism", "unknown", "--sample-order", "sequential",
                "--alpha", "false", "--output", str(target),
                "--browser", "/definitely/not/a/browser", "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("probe determinism is invalid", completed.stderr)
        self.assertNotIn("browser is unavailable", completed.stderr)
        self.assertFalse(target.exists())

    def test_isolation_seed_and_animation_seek_are_pure_and_fail_closed(self) -> None:
        isolation_module = self.output / "isolation.mjs"
        anime_module = self.output / "anime-bridge.mjs"
        for source, output in (
            (RUNTIME / "src" / "isolation.ts", isolation_module),
            (RUNTIME / "src" / "anime-bridge.ts", anime_module),
        ):
            bundled = subprocess.run(
                [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source),
                 "--bundle", "--platform=node", "--format=esm", f"--outfile={output}"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const isolation = await import(process.argv[2]);
const anime = await import(process.argv[3]);
const values = [0, 1, 2].map((i) => isolation.seededUnit("seed", "particles", i));
const repeated = [0, 1, 2].map((i) => isolation.seededUnit("seed", "particles", i));
const result = {
  className: isolation.scopedClass("scene-a", "target"),
  selector: isolation.scopedSelector("scene-a", "target"),
  idA: isolation.svgId("scene-a", "paint"), idB: isolation.svgId("scene-b", "paint"),
  urlA: isolation.svgUrl("scene-a", "paint"), values, repeated,
  changed: isolation.seededUnit("seed", "other", 1),
  seeks: [anime.animationSeekMs(0), anime.animationSeekMs(24), anime.animationSeekMs(47, 2)],
};
for (const call of [
  () => isolation.scopedClass("BAD", "target"),
  () => isolation.seededUnit("", "stream", 0),
  () => isolation.seededUnit("seed", "stream", -1),
  () => anime.animationSeekMs(1.5),
  () => anime.animationSeekMs(1, 0, 30),
]) {
  try { call(); result.rejected = false; } catch { result.rejected = result.rejected !== false; }
}
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", isolation_module.as_uri(), anime_module.as_uri()],
            input=script, capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["className"], "scene-a--target")
        self.assertEqual(result["selector"], '[data-talkcraft-scope="scene-a"] .scene-a--target')
        self.assertNotEqual(result["idA"], result["idB"])
        self.assertEqual(result["urlA"], "url(#scene-a--svg--paint)")
        self.assertEqual(result["values"], result["repeated"])
        self.assertNotEqual(result["values"][1], result["changed"])
        self.assertEqual(result["seeks"], [0, 1000, 1875])
        self.assertTrue(result["rejected"])

    def test_alt_block_candidate_identity_and_capacity_fail_closed(self) -> None:
        source = RUNTIME / "src" / "cards" / "alt-block-lines.tsx"
        contract = RUNTIME / "src" / "cards" / "alt-block-lines.contract.json"
        cases = json.loads((RUNTIME / "qualification-cases" / "alt-block-lines.json").read_text(encoding="utf-8"))
        registry = json.loads((RUNTIME / "card-registry.json").read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract.read_bytes()).hexdigest())
        self.assertEqual(len(cases["cases"]), 2)
        self.assertEqual(cases["adapter_version"], "1.1.0")
        self.assertTrue(all(case["scene"]["layout"] == "full-frame" for case in cases["cases"]))
        self.assertTrue(all(case["presenter"] is None for case in cases["cases"]))
        self.assertTrue(all([item["slot"] for item in case["scene_inputs"]] == ["presenter"] for case in cases["cases"]))
        self.assertEqual(
            cases["cases"][0]["sfx"],
            [
                {"cueId": "block-0-complete", "frame": 16, "anchor": "block-0-complete", "name": "click", "assetKey": "talkcraft-click", "src": "qualification/talkcraft-click.mp3", "sha256": "dcb764a9be9ac69e64c8a4736513d019ce270dd9e62ffea311a8abfa0efb8e60", "volume": 0.4, "playbackRate": 1.0},
                {"cueId": "block-1-complete", "frame": 19, "anchor": "block-1-complete", "name": "click", "assetKey": "talkcraft-click", "src": "qualification/talkcraft-click.mp3", "sha256": "dcb764a9be9ac69e64c8a4736513d019ce270dd9e62ffea311a8abfa0efb8e60", "volume": 0.36, "playbackRate": 1.1},
            ],
        )
        pending_count = sum(
            card["production"]["status"] == "pending_portrait_adapter"
            for card in registry["cards"]
        )
        qualified_count = sum(
            card["production"]["status"] == "qualified"
            for card in registry["cards"]
        )
        self.assertEqual(pending_count + qualified_count, 108)
        self.assertGreaterEqual(qualified_count, 1)
        self.assertNotIn("先做减法", source.read_text(encoding="utf-8"))
        module = self.output / "alt-block-lines.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node",
             "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:72};
const raw = {lines:["以前追流量","现在做信任"],accent:"#7a5af8",canvas:"#ffffff",ink:"#17171a",outline:"#b7b2c8"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["long", {...raw, lines:["这是一行超过六字的文字","现在做信任"]}, context],
  ["short", raw, {...context, durationInFrames:49}],
  ["extra", {...raw, extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,sfxCues:card.sfxCues}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["lines"], ["以前追流量", "现在做信任"])
        self.assertEqual(result["rejected"], ["long", "short", "extra"])
        self.assertEqual([cue["anchor"] for cue in result["sfxCues"]], ["block-0-complete", "block-1-complete"])

    def test_count_badge_candidate_identity_capacity_and_native_timing(self) -> None:
        source = RUNTIME / "src" / "cards" / "count-badge-title.tsx"
        contract = RUNTIME / "src" / "cards" / "count-badge-title.contract.json"
        cases = json.loads((RUNTIME / "qualification-cases" / "count-badge-title.json").read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract.read_bytes()).hexdigest())
        self.assertEqual(len(cases["cases"]), 2)
        self.assertEqual(cases["adapter_version"], "1.1.0")
        self.assertEqual(cases["cases"][0]["scene"]["layout"], "full-frame")
        self.assertIsNone(cases["cases"][0]["presenter"])
        self.assertEqual([item["slot"] for item in cases["cases"][0]["scene_inputs"]], ["presenter"])
        source_text = source.read_text(encoding="utf-8")
        self.assertIn('data-track="line1"', source_text)
        self.assertIn('alignItems: "baseline"', source_text)
        line1_start = source_text.index('data-track="line1"')
        number_start = source_text.index('data-track="number"')
        quantifier_start = source_text.index('data-track="quantifier"')
        line1_end = source_text.index('</div>', line1_start)
        line2_start = source_text.index('data-track="line2"')
        self.assertLess(line1_start, number_start)
        self.assertLess(number_start, quantifier_start)
        self.assertLess(quantifier_start, line1_end)
        self.assertLess(line1_end, line2_start)
        self.assertEqual(
            cases["cases"][0]["sfx"],
            [{
                "frame": 15, "anchor": "number-color-lock", "name": "ui-pop",
                "assetKey": "talkcraft-ui-pop", "cueId": "number-color-lock",
                "src": "qualification/talkcraft-ui-pop.mp3",
                "sha256": "e19e3e04563c470068ee8fd179fb4d0ac2a6e51724cb60fd2e92237c456eacd4",
                "volume": 0.32, "playbackRate": 1.0,
            }],
        )
        module = self.output / "count-badge-title.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node",
             "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:80};
const raw = {number:"12",quantifier:"个步骤",line2:"完成升级",accent:"#7a5af8",canvas:"#ffffff",ink:"#1d1d1f"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["number", {...raw, number:"100"}, context],
  ["quantifier", {...raw, quantifier:"个"}, context],
  ["line2", {...raw, line2:"字数超过六个汉字"}, context],
  ["short", raw, {...context, durationInFrames:79}],
  ["extra", {...raw, extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,sfxCues:card.sfxCues}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["number"], "12")
        self.assertEqual(result["rejected"], ["number", "quantifier", "line2", "short", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["sfxCues"], [{"cueId": "number-color-lock", "frame": 15, "anchor": "number-color-lock", "name": "ui-pop", "assetKey": "talkcraft-ui-pop", "volume": 0.32, "playbackRate": 1}])

    def test_shape_wipe_candidate_requires_real_ab_inputs_and_absolute_timing(self) -> None:
        source = RUNTIME / "src" / "cards" / "shape-wipe-transition.tsx"
        contract = RUNTIME / "src" / "cards" / "shape-wipe-transition.contract.json"
        cases = json.loads((RUNTIME / "qualification-cases" / "shape-wipe-transition.json").read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract.read_bytes()).hexdigest())
        self.assertEqual(len(cases["cases"]), 2)
        self.assertTrue(all(case["scene"]["layout"] == "full-frame" for case in cases["cases"]))
        self.assertTrue(all(case["presenter"] is None for case in cases["cases"]))
        self.assertEqual(
            [[item["slot"] for item in case["scene_inputs"]] for case in cases["cases"]],
            [["a", "b"], ["a", "b"]],
        )
        self.assertEqual(
            [[item["kind"] for item in case["scene_inputs"]] for case in cases["cases"]],
            [["presenter-on-white", "video-cover"], ["presenter-on-white", "video-cover"]],
        )
        source_text = source.read_text(encoding="utf-8")
        for placeholder in ("季度营收", "SCENE A", "SCENE B", "chapter-tag", "chart-card"):
            self.assertNotIn(placeholder, source_text)
        module = self.output / "shape-wipe-transition.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node",
             "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:59};
const raw = {colors:["#d8d8dc","#8a8a8e","#1d1d1f"],direction:"left-to-right"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["colors", {...raw, colors:["#fff","#888888","#111111"]}, context],
  ["rainbow", {...raw, colors:["#ffdddd","#00aa00","#000088"]}, context],
  ["order", {...raw, colors:["#1d1d1f","#8a8a8e","#d8d8dc"]}, context],
  ["direction", {...raw, direction:"up"}, context],
  ["short", raw, {...context, durationInFrames:58}],
  ["extra", {...raw, extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.transitionFrames,sfx:card.sfxCues}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["rejected"], ["colors", "rainbow", "order", "direction", "short", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["a", "b"])
        self.assertEqual(result["frames"], {"starts": [22, 23, 25], "centers": [27, 29, 30], "ends": [32, 34, 36], "swap": 29})
        self.assertEqual(result["sfx"][0]["frame"], 22)
        self.assertEqual(result["sfx"][0]["volume"], 0.35)

    def test_bar_chart_growth_candidate_requires_five_real_values_and_preserves_dense_timing(self) -> None:
        source = RUNTIME / "src" / "cards" / "bar-chart-growth.tsx"
        contract = RUNTIME / "src" / "cards" / "bar-chart-growth.contract.json"
        cases = json.loads((RUNTIME / "qualification-cases" / "bar-chart-growth.json").read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract.read_bytes()).hexdigest())
        self.assertEqual(len(cases["cases"]), 2)
        self.assertTrue(all(case["scene"]["layout"] == "full-frame" for case in cases["cases"]))
        self.assertTrue(all(case["presenter"] is None for case in cases["cases"]))
        self.assertTrue(all([item["slot"] for item in case["scene_inputs"]] == ["presenter"] for case in cases["cases"]))
        self.assertTrue(all(len(case["raw"]["values"]) == 5 and case["raw"]["unit"] and case["raw"]["source"] for case in cases["cases"]))
        source_text = source.read_text(encoding="utf-8")
        self.assertIn('transformOrigin: "50% 100%"', source_text)
        self.assertNotIn("data-value", source_text)
        module = self.output / "bar-chart-growth.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node",
             "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:80};
const raw = {title:"课程完成率",labels:["第1周","第2周","第3周","第4周","第5周"],values:[28,41,55,71,86],maxValue:100,conclusion:"提升58个百分点",unit:"%",source:"资格测试输入 A",accent:"#e8720c",ink:"#1d1d1f"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["count", {...raw, values:[1,2,3,4]}, context],
  ["zigzag", {...raw, values:[1,3,2,4,5]}, context],
  ["range", {...raw, values:[1,2,3,4,101]}, context],
  ["source", {...raw, source:""}, context],
  ["short", raw, {...context, durationInFrames:79}],
  ["extra", {...raw, extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,frames:card.animationFrames,sfx:card.sfxCues}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["values"], [28, 41, 55, 71, 86])
        self.assertEqual(result["rejected"], ["count", "zigzag", "range", "source", "short", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["frames"], {"title": 7, "baseline": 10, "bars": [15, 16, 18, 19, 21], "conclusion": 28})
        self.assertEqual([cue["frame"] for cue in result["sfx"]], [10, 15, 16, 18, 19, 21, 28])
        self.assertLessEqual(max(cue["volume"] for cue in result["sfx"]), 0.32)

    def test_callout_line_label_binds_measured_image_geometry_and_serial_timing(self) -> None:
        source = RUNTIME / "src" / "cards" / "callout-line-label.tsx"
        contract_path = RUNTIME / "src" / "cards" / "callout-line-label.contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads((RUNTIME / "qualification-cases" / "callout-line-label.json").read_text(encoding="utf-8"))
        fixtures = json.loads((RUNTIME / "qualification-fixtures.json").read_text(encoding="utf-8"))
        fixtures_by_id = {asset["asset_id"]: asset for asset in fixtures["assets"]}
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["trusted_geometry"], "case-measured-targets-v1")
        self.assertEqual(contract["scene_input_slots"], ["subject-image", "presenter"])
        self.assertEqual([cue["frame"] for cue in contract["sfx_cues"]], [14, 19, 29, 34, 38, 48])
        self.assertLessEqual(max(cue["volume"] for cue in contract["sfx_cues"]), 0.28)
        for case in cases["cases"]:
            self.assertEqual(case["scene"], {"layout": "full-frame", "presenterRect": None})
            self.assertIsNone(case["presenter"])
            self.assertEqual([item["slot"] for item in case["scene_inputs"]], ["subject-image", "presenter"])
            image_input = case["scene_inputs"][0]
            image = fixtures_by_id[image_input["fixture_id"]]
            self.assertEqual(image_input["kind"], "image-contain")
            self.assertEqual(case["measurement"]["fixture_id"], image_input["fixture_id"])
            self.assertEqual(case["measurement"]["source_size"], {"width": image["width"], "height": image["height"]})
            self.assertEqual(case["measurement"]["target_boxes"], [item["targetBox"] for item in case["raw"]["annotations"]])
            self.assertEqual(case["measurement"]["label_rects"], [item["labelRect"] for item in case["raw"]["annotations"]])

        module = self.output / "callout-line-label.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node",
             "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const metadata = {"subject-image":{width:1200,height:750}};
const context = {width:1080,height:1920,fps:24,durationInFrames:118,sceneInputMetadata:metadata};
const raw = {annotations:[
  {title:"显示区域",subtitle:"画面主体位于这里",side:"right",targetBox:{x:273,y:109,width:385,height:386},labelRect:{x:760,y:260,width:260,height:104}},
  {title:"随身设备",subtitle:"位于桌面左下方",side:"right",targetBox:{x:91,y:588,width:266,height:82},labelRect:{x:520,y:480,width:260,height:104}},
],color:"#ff453a",ink:"#1d1d1f"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["metadata", raw, {...context,sceneInputMetadata:{}}],
  ["bounds", {...raw,annotations:[{...raw.annotations[0],targetBox:{x:1100,y:109,width:385,height:386}},raw.annotations[1]]}, context],
  ["line", {...raw,annotations:[{...raw.annotations[0],labelRect:{x:580,y:309,width:260,height:104}},raw.annotations[1]]}, context],
  ["target-label", {...raw,annotations:[raw.annotations[0],{...raw.annotations[1],side:"left",targetBox:{x:1000,y:150,width:100,height:100},labelRect:{x:480,y:300,width:220,height:96}}]}, context],
  ["labels", {...raw,annotations:[raw.annotations[0],{...raw.annotations[1],labelRect:raw.annotations[0].labelRect}]}, context],
  ["text", {...raw,annotations:[{...raw.annotations[0],title:"这是一个超过容量的标题"},raw.annotations[1]]}, context],
  ["short", raw, {...context,durationInFrames:117}],
  ["extra", {...raw,extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.animationFrames}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["rejected"], ["metadata", "bounds", "line", "target-label", "labels", "text", "short", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["subject-image", "presenter"])
        self.assertEqual(result["frames"], {"dots":[14,34],"lines":[19,38],"labels":[29,48],"texts":[31,50],"outs":[95,98]})
        self.assertAlmostEqual(result["good"]["annotations"][0]["target"]["x"], 574.8)
        self.assertAlmostEqual(result["good"]["annotations"][1]["target"]["y"], 557.4)

    def test_behind_text_title_binds_real_alpha_geometry_and_preserves_source_timing(self) -> None:
        source = RUNTIME / "src" / "cards" / "behind-text-title.tsx"
        contract_path = RUNTIME / "src" / "cards" / "behind-text-title.contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads((RUNTIME / "qualification-cases" / "behind-text-title.json").read_text(encoding="utf-8"))
        fixtures = json.loads((RUNTIME / "qualification-fixtures.json").read_text(encoding="utf-8"))
        presenter = next(asset for asset in fixtures["assets"] if asset["asset_id"] == "alt-block-lines-presenter")
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["trusted_geometry"], "case-measured-alpha-overlap-v1")
        self.assertEqual(contract["scene_input_slots"], ["presenter"])
        self.assertEqual(contract["sfx_cues"][0]["frame"], 10)
        self.assertLessEqual(contract["sfx_cues"][0]["volume"], 0.3)
        self.assertEqual(contract["geometry"]["presenter_rect"], {"x": 180, "y": 850, "width": 720, "height": 800})
        self.assertEqual(contract["geometry"]["title_rect"], {"x": 40, "y": 300, "width": 1000, "height": 830})
        self.assertLessEqual(contract["geometry"]["max_overlap_ratio"], 0.22)
        self.assertEqual((presenter["width"], presenter["height"]), (540, 600))
        for case in cases["cases"]:
            self.assertEqual(case["scene_inputs"], [{"slot": "presenter", "kind": "presenter-alpha", "fixture_id": "alt-block-lines-presenter"}])
            self.assertIsNone(case["presenter"])
            measurement = case["measurement"]
            self.assertEqual(measurement["source_size"], {"width": presenter["width"], "height": presenter["height"]})
            self.assertEqual(measurement["source_alpha_bbox"], contract["geometry"]["source_alpha_bbox"])
            self.assertEqual(measurement["presenter_rect"], contract["geometry"]["presenter_rect"])
            self.assertEqual(measurement["title_rect"], contract["geometry"]["title_rect"])
            self.assertGreaterEqual(measurement["overlap_ratio"], contract["geometry"]["min_overlap_ratio"])
            self.assertLessEqual(measurement["overlap_ratio"], contract["geometry"]["max_overlap_ratio"])
            self.assertEqual(len(case["raw"]["title_lines"]), 2)
            self.assertTrue(all(2 <= len(line) <= 3 for line in case["raw"]["title_lines"]))

        source_text = source.read_text(encoding="utf-8")
        self.assertLess(source_text.index('data-track="title"'), source_text.index('data-track="presenter"'))
        self.assertIn("Array.from({length: 20}", source_text)
        self.assertIn("const depth = index + 1", source_text)
        self.assertIn("const shade = 212 - index * 5", source_text)
        self.assertIn('"30px 38px 48px rgba(0,0,0,0.18)"', source_text)
        self.assertIn('data-title-depth="true"', source_text)
        self.assertIn('data-title-face="true"', source_text)
        self.assertIn("linear-gradient(180deg", source_text)
        self.assertIn('textShadow: "none"', source_text)
        self.assertIn('WebkitTextFillColor: "transparent"', source_text)
        self.assertIn('fontFamily: \'"Yuanti SC", "PingFang SC", sans-serif\'', source_text)
        self.assertIn("fontWeight: 700", source_text)
        extrusion_layers = re.search(r"Array\.from\(\{length: (\d+)\}", source_text)
        line_gap = re.search(r"const TITLE_LINE_GAP = (\d+);", source_text)
        self.assertIsNotNone(extrusion_layers)
        self.assertIsNotNone(line_gap)
        self.assertGreaterEqual(int(line_gap.group(1)), 28)
        self.assertGreater(int(line_gap.group(1)), int(extrusion_layers.group(1)))
        self.assertIn("lineHeight: 0.93", source_text)
        self.assertIn("gap: TITLE_LINE_GAP", source_text)
        self.assertNotIn("host-placeholder", source_text)
        module = self.output / "behind-text-title.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node",
             "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:76,sceneInputMetadata:{presenter:{width:540,height:600}}};
const raw = {title_lines:["真实","表达"],subtitle:"真实表达先于漂亮形式",accent:"#007aff"};
const good = card.prepareCard(raw, context);
const mixed = card.prepareCard({...raw,title_lines:["真实","在场感"]}, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["title-count", {...raw,title_lines:["真实"]}, context],
  ["title-length", {...raw,title_lines:["四个汉字","表达"]}, context],
  ["subtitle", {...raw,subtitle:"短"}, context],
  ["metadata", raw, {...context,sceneInputMetadata:{}}],
  ["short", raw, {...context,durationInFrames:75}],
  ["extra", {...raw,extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,mixed,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.animationFrames,rects:card.layoutRects}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["fontSizes"], [430, 430])
        self.assertEqual(result["good"]["titleLines"], ["真实", "表达"])
        self.assertEqual(result["mixed"]["fontSizes"], [430, 310])
        self.assertEqual(result["rejected"], ["title-count", "title-length", "subtitle", "metadata", "short", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["presenter"])
        self.assertEqual(result["frames"], {"titleStart":10,"titleEnd":24,"subtitleStart":18,"subtitleEnd":28,"driftStart":24,"driftPeriod":192})

    def test_behind_text_title_evidence_has_no_near_black_title_edge(self) -> None:
        if shutil.which("ffmpeg") is None:
            raise unittest.SkipTest("ffmpeg is unavailable")
        evidence = RUNTIME.parent / "qualification-evidence" / "behind-text-title"
        report = json.loads((evidence / "candidate-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["implementation_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "behind-text-title.tsx").read_bytes()).hexdigest())
        self.assertEqual(report["case_definition_sha256"], hashlib.sha256((RUNTIME / "qualification-cases" / "behind-text-title.json").read_bytes()).hexdigest())
        for case_id in ("contrast-a", "contrast-b"):
            case_report = next(item for item in report["cases"] if item["case_id"] == case_id)
            for artifact in ("composite_preview", "settled_frame", "contact_sheet"):
                record = case_report[artifact]
                self.assertEqual(record["sha256"], hashlib.sha256((evidence / record["path"]).read_bytes()).hexdigest())
            rgb = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(evidence / f"{case_id}.settled-frame.png"),
                 "-vf", "crop=1000:550:40:300", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=10, check=True,
            ).stdout
            pixels = zip(rgb[0::3], rgb[1::3], rgb[2::3])
            self.assertLess(sum(max(pixel) < 45 for pixel in pixels), 100, case_id)

    def test_impact_open_title_preserves_single_slam_and_portrait_contract(self) -> None:
        source = RUNTIME / "src" / "cards" / "impact-open-title.tsx"
        contract_path = RUNTIME / "src" / "cards" / "impact-open-title.contract.json"
        cases_path = RUNTIME / "qualification-cases" / "impact-open-title.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        fixtures = json.loads((RUNTIME / "qualification-fixtures.json").read_text(encoding="utf-8"))
        presenter = next(asset for asset in fixtures["assets"] if asset["asset_id"] == "alt-block-lines-presenter")
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["scene"], "full-frame")
        self.assertEqual(contract["scene_input_slots"], ["presenter"])
        self.assertEqual(contract["geometry"]["presenter_rect"], {"x": 180, "y": 850, "width": 720, "height": 800})
        self.assertEqual([(cue["frame"], cue["assetKey"], cue["volume"]) for cue in contract["sfx_cues"]], [
            (10, "talkcraft-impact-deep-whoosh", 0.3),
            (17, "talkcraft-impact-hit-fast-exciting", 0.26),
        ])
        for case in cases["cases"]:
            self.assertEqual(case["duration_frames"], 76)
            self.assertEqual(case["scene"], {"layout": "full-frame", "presenterRect": None})
            self.assertIsNone(case["presenter"])
            self.assertEqual(case["scene_inputs"], [{"slot": "presenter", "kind": "presenter-alpha", "fixture_id": "alt-block-lines-presenter"}])
            self.assertEqual(len(case["sfx"]), 2)
            self.assertEqual((presenter["width"], presenter["height"]), (540, 600))

        source_text = source.read_text(encoding="utf-8")
        self.assertIn("slamStart: 10, slamEnd: 14", source_text)
        self.assertIn("cornerStart: 10, cornerEnd: 17", source_text)
        self.assertIn("wordStart: 17, wordEnd: 21", source_text)
        self.assertIn("dotsStart: 19, dotsEnd: 29", source_text)
        self.assertIn("subtitleStart: 23, subtitleEnd: 30", source_text)
        self.assertIn('[["tl", -1, -1], ["br", 1, 1]]', source_text)
        self.assertIn("const DOTS_OPACITY = 0.5", source_text)
        self.assertIn('transformOrigin: "0% 50%"', source_text)
        self.assertNotIn("host-placeholder", source_text)

        module = self.output / "impact-open-title.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node", "--format=esm", f"--outfile={module}"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:76,sceneInputMetadata:{presenter:{width:540,height:600}}};
const raw = {lead:"三秒抓住",impact:"重点",subtitle:"接下来只讲清楚一件事情",accent:"#ff5a36"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["lead-short", {...raw,lead:"两字"}, context],
  ["lead-long", {...raw,lead:"六个汉字超长"}, context],
  ["impact-short", {...raw,impact:"重"}, context],
  ["subtitle-short", {...raw,subtitle:"太短"}, context],
  ["metadata", raw, {...context,sceneInputMetadata:{}}],
  ["duration", raw, {...context,durationInFrames:75}],
  ["duration-long", raw, {...context,durationInFrames:77}],
  ["extra", {...raw,extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.animationFrames,rects:card.layoutRects}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["lead"], "三秒抓住")
        self.assertEqual(result["good"]["impact"], "重点")
        self.assertEqual(result["rejected"], ["lead-short", "lead-long", "impact-short", "subtitle-short", "metadata", "duration", "duration-long", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["presenter"])

    def test_impact_open_title_evidence_is_hash_bound_and_stays_candidate(self) -> None:
        evidence = RUNTIME.parent / "qualification-evidence" / "impact-open-title"
        report = json.loads((evidence / "candidate-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "candidate_not_qualified")
        self.assertIsNone(report["human_visual_approval"])
        self.assertFalse(report["registry_updated"])
        self.assertEqual(report["implementation_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "impact-open-title.tsx").read_bytes()).hexdigest())
        self.assertEqual(report["contract_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "impact-open-title.contract.json").read_bytes()).hexdigest())
        self.assertEqual(report["case_definition_sha256"], hashlib.sha256((RUNTIME / "qualification-cases" / "impact-open-title.json").read_bytes()).hexdigest())
        for comparison in report["upstream_comparison"].values():
            self.assertEqual(comparison["sha256"], hashlib.sha256((evidence / comparison["path"]).read_bytes()).hexdigest())
        for case_id in ("contrast-a", "contrast-b"):
            case_report = next(item for item in report["cases"] if item["case_id"] == case_id)
            for artifact in ("composite_preview", "settled_frame", "contact_sheet"):
                record = case_report[artifact]
                self.assertEqual(record["sha256"], hashlib.sha256((evidence / record["path"]).read_bytes()).hexdigest())

    def test_keyword_pop_highlight_preserves_delayed_overshoot_and_single_keyword_contract(self) -> None:
        source = RUNTIME / "src" / "cards" / "keyword-pop-highlight.tsx"
        contract_path = RUNTIME / "src" / "cards" / "keyword-pop-highlight.contract.json"
        cases_path = RUNTIME / "qualification-cases" / "keyword-pop-highlight.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["scene"], "full-frame")
        self.assertEqual(contract["scene_input_slots"], ["presenter"])
        self.assertEqual(contract["geometry"]["presenter_rect"], {"x": 90, "y": 360, "width": 900, "height": 1000})
        self.assertEqual(contract["geometry"]["caption_rect"], {"x": 60, "y": 1370, "width": 960, "height": 180})
        self.assertEqual(contract["geometry"]["bottom_caption_safe_px"], 270)
        self.assertEqual(contract["sfx_cues"], [{
            "cueId": "keyword-impact", "frame": 13, "anchor": "keyword-impact",
            "name": "wind-swoosh-short", "assetKey": "talkcraft-wind-swoosh-short",
            "volume": 0.5, "playbackRate": 1.0,
        }])
        for case in cases["cases"]:
            self.assertEqual(case["duration_frames"], 48)
            self.assertEqual(case["scene"], {"layout": "full-frame", "presenterRect": None})
            self.assertIsNone(case["presenter"])
            self.assertEqual(case["scene_inputs"], [{"slot": "presenter", "kind": "presenter-alpha", "fixture_id": "alt-block-lines-presenter"}])
            self.assertEqual(len(case["sfx"]), 1)

        source_text = source.read_text(encoding="utf-8")
        self.assertIn("popStart: 13, popEnd: 18", source_text)
        self.assertIn("shakeStart: 13, shakeEnd: 19", source_text)
        self.assertIn("settleStart: 19, settleEnd: 24", source_text)
        self.assertIn("const POP_SCALE = 1.65", source_text)
        self.assertIn("const REST_SCALE = 1.15", source_text)
        self.assertIn("const SHAKE_PX = 7", source_text)
        self.assertIn('transformOrigin: "50% 80%"', source_text)
        self.assertIn('transform: "skewX(-6deg)"', source_text)
        self.assertIn('margin: "0 0.36em"', source_text)
        self.assertNotIn("host-placeholder", source_text)

        module = self.output / "keyword-pop-highlight.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node", "--format=esm", f"--outfile={module}"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:48,sceneInputMetadata:{presenter:{width:540,height:600}}};
const raw = {before:"一年真正需要",keyword:"三个重点",after:"就够了",ink:"#1d1d1f",keywordColor:"#ffffff",blockColor:"#ff5a36"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["keyword-short", {...raw,keyword:"重"}, context],
  ["keyword-long", {...raw,keyword:"这个关键词明显太长"}, context],
  ["combined-long", {...raw,before:"这是一段明显过长前文",after:"再加一段明显过长后文"}, context],
  ["metadata", raw, {...context,sceneInputMetadata:{}}],
  ["duration-short", raw, {...context,durationInFrames:47}],
  ["duration-long", raw, {...context,durationInFrames:49}],
  ["extra", {...raw,extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.animationFrames,rects:card.layoutRects,shakeOffsets:card.shakeOffsets}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["keyword"], "三个重点")
        self.assertEqual(result["rejected"], ["keyword-short", "keyword-long", "combined-long", "metadata", "duration-short", "duration-long", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["presenter"])
        self.assertEqual(result["shakeOffsets"], [0, 7, -7, 7, -7, 7, 0])

    def test_keyword_pop_highlight_evidence_is_hash_bound_and_stays_candidate(self) -> None:
        evidence = RUNTIME.parent / "qualification-evidence" / "keyword-pop-highlight"
        report = json.loads((evidence / "candidate-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "candidate_not_qualified")
        self.assertIsNone(report["human_visual_approval"])
        self.assertFalse(report["registry_updated"])
        self.assertEqual(report["implementation_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "keyword-pop-highlight.tsx").read_bytes()).hexdigest())
        self.assertEqual(report["contract_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "keyword-pop-highlight.contract.json").read_bytes()).hexdigest())
        self.assertEqual(report["case_definition_sha256"], hashlib.sha256((RUNTIME / "qualification-cases" / "keyword-pop-highlight.json").read_bytes()).hexdigest())
        for comparison in report["upstream_comparison"].values():
            self.assertEqual(comparison["sha256"], hashlib.sha256((evidence / comparison["path"]).read_bytes()).hexdigest())
        for case_id in ("contrast-a", "contrast-b"):
            case_report = next(item for item in report["cases"] if item["case_id"] == case_id)
            for artifact in ("composite_preview", "settled_frame", "contact_sheet"):
                record = case_report[artifact]
                self.assertEqual(record["sha256"], hashlib.sha256((evidence / record["path"]).read_bytes()).hexdigest())

    def test_slab_punch_title_preserves_center_slab_hard_cut_and_two_line_contract(self) -> None:
        source = RUNTIME / "src" / "cards" / "slab-punch-title.tsx"
        contract_path = RUNTIME / "src" / "cards" / "slab-punch-title.contract.json"
        cases_path = RUNTIME / "qualification-cases" / "slab-punch-title.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["scene"], "full-frame")
        self.assertEqual(contract["scene_input_slots"], ["presenter"])
        self.assertEqual(contract["geometry"]["presenter_rect"], {"x": 180, "y": 850, "width": 720, "height": 800})
        self.assertEqual(contract["geometry"]["title_rect"], {"x": 90, "y": 250, "width": 900, "height": 570})
        self.assertEqual(contract["geometry"]["bottom_caption_safe_px"], 270)
        self.assertEqual([cue["frame"] for cue in contract["sfx_cues"]], [16, 21])
        self.assertEqual([cue["assetKey"] for cue in contract["sfx_cues"]], ["talkcraft-paper-slice-quick", "talkcraft-camera-lens-shutter"])
        for case in cases["cases"]:
            self.assertEqual(case["duration_frames"], 64)
            self.assertEqual(case["scene"], {"layout": "full-frame", "presenterRect": None})
            self.assertIsNone(case["presenter"])
            self.assertEqual(case["scene_inputs"], [{"slot": "presenter", "kind": "presenter-alpha", "fixture_id": "alt-block-lines-presenter"}])
            self.assertEqual(len(case["sfx"]), 2)

        source_text = source.read_text(encoding="utf-8")
        self.assertIn("line1Start: 10, line1End: 14", source_text)
        self.assertIn("slabStart: 16, slabEnd: 21", source_text)
        self.assertIn("punchStart: 21, punchEnd: 25", source_text)
        self.assertIn('transformOrigin: "50% 50%"', source_text)
        self.assertIn('transform: "rotate(-2.5deg)"', source_text)
        self.assertIn('marginLeft: -44', source_text)
        self.assertIn('padding: "20px 44px 24px"', source_text)
        self.assertIn("animationLocalFrame < animationFrames.punchStart ? 0 : 1", source_text)
        self.assertNotIn("host-placeholder", source_text)

        module = self.output / "slab-punch-title.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node", "--format=esm", f"--outfile={module}"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:64,sceneInputMetadata:{presenter:{width:540,height:600}}};
const raw = {line1:"先看清楚",line2:"核心价值",accent:"#ff5a36",ink:"#1d1d1f",wordColor:"#ffffff"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["line1-short", {...raw,line1:"一"}, context],
  ["line1-long", {...raw,line1:"这一行太长了"}, context],
  ["line2-short", {...raw,line2:"重"}, context],
  ["line2-long", {...raw,line2:"这一行明显太长"}, context],
  ["metadata", raw, {...context,sceneInputMetadata:{}}],
  ["duration-short", raw, {...context,durationInFrames:63}],
  ["duration-long", raw, {...context,durationInFrames:65}],
  ["extra", {...raw,extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.animationFrames,rects:card.layoutRects}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()], input=script,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["line2"], "核心价值")
        self.assertEqual(result["rejected"], ["line1-short", "line1-long", "line2-short", "line2-long", "metadata", "duration-short", "duration-long", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["presenter"])

    def test_slab_punch_title_evidence_is_hash_bound_and_stays_candidate(self) -> None:
        evidence = RUNTIME.parent / "qualification-evidence" / "slab-punch-title"
        report = json.loads((evidence / "candidate-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "candidate_not_qualified")
        self.assertIsNone(report["human_visual_approval"])
        self.assertFalse(report["registry_updated"])
        self.assertEqual(report["implementation_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "slab-punch-title.tsx").read_bytes()).hexdigest())
        self.assertEqual(report["contract_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "slab-punch-title.contract.json").read_bytes()).hexdigest())
        self.assertEqual(report["case_definition_sha256"], hashlib.sha256((RUNTIME / "qualification-cases" / "slab-punch-title.json").read_bytes()).hexdigest())
        for comparison in report["upstream_comparison"].values():
            self.assertEqual(comparison["sha256"], hashlib.sha256((evidence / comparison["path"]).read_bytes()).hexdigest())
        for case_id in ("contrast-a", "contrast-b"):
            case_report = next(item for item in report["cases"] if item["case_id"] == case_id)
            for artifact in ("composite_preview", "settled_frame", "contact_sheet"):
                record = case_report[artifact]
                self.assertEqual(record["sha256"], hashlib.sha256((evidence / record["path"]).read_bytes()).hexdigest())

    def test_type_contrast_emphasis_preserves_shared_baseline_and_uneven_word_beats(self) -> None:
        source = RUNTIME / "src" / "cards" / "type-contrast-emphasis.tsx"
        contract_path = RUNTIME / "src" / "cards" / "type-contrast-emphasis.contract.json"
        cases_path = RUNTIME / "qualification-cases" / "type-contrast-emphasis.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["scene"], "full-frame")
        self.assertEqual(contract["scene_input_slots"], ["presenter"])
        self.assertEqual(contract["geometry"]["presenter_rect"], {"x": 180, "y": 850, "width": 720, "height": 800})
        self.assertEqual(contract["geometry"]["caption_rect"], {"x": 60, "y": 260, "width": 960, "height": 520})
        self.assertEqual([cue["frame"] for cue in contract["sfx_cues"]], [28, 40])
        for case in cases["cases"]:
            self.assertEqual(case["duration_frames"], 54)
            self.assertEqual(case["scene_inputs"], [{"slot": "presenter", "kind": "presenter-alpha", "fixture_id": "alt-block-lines-presenter"}])
            self.assertEqual(len(case["raw"]["words"]), 5)
            self.assertEqual([word["emphasis"] for word in case["raw"]["words"]], ["normal", "normal", "serif", "normal", "color"])
            self.assertEqual([word["frame"] for word in case["raw"]["words"]], [4, 21, 28, 36, 40])

        source_text = source.read_text(encoding="utf-8")
        self.assertIn('alignItems: "baseline"', source_text)
        self.assertIn('transformOrigin: "50% 100%"', source_text)
        self.assertIn('word.emphasis === "serif" ? serifFamily : sansFamily', source_text)
        self.assertIn('skewX(-7deg)', source_text)
        self.assertIn("WORD_FROM_SCALE = 0.95", source_text)
        self.assertIn("ACCENT_FROM_SCALE = 0.92", source_text)
        self.assertIn("Math.pow(1 - clamp01(value), 3)", source_text)  # GSAP power2.out = cubic
        self.assertIn("Math.pow(1 - clamp01(value), 4)", source_text)  # GSAP power3.out = quartic
        self.assertNotIn("backOut", source_text)
        self.assertNotIn("host-placeholder", source_text)

        module = self.output / "type-contrast-emphasis.mjs"
        bundled = subprocess.run(
            [str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node", "--format=esm", f"--outfile={module}"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:54,sceneInputMetadata:{presenter:{width:540,height:600}}};
const raw = {words:[
  {text:"能留住人的",frame:4,emphasis:"normal"},{text:"不是",frame:21,emphasis:"normal"},
  {text:"流量",frame:28,emphasis:"serif"},{text:"是",frame:36,emphasis:"normal"},{text:"信任",frame:40,emphasis:"color"}
],accent:"#0066cc",ink:"#1d1d1f"};
const good = card.prepareCard(raw, context);
const rejected = [];
for (const [name, value, ctx] of [
  ["timing", {...raw,words:raw.words.map((w,i)=>({...w,frame:[4,21,28,35,40][i]}))}, context],
  ["emphasis", {...raw,words:raw.words.map((w,i)=>({...w,emphasis:i===2?"serif":"normal"}))}, context],
  ["long", {...raw,words:raw.words.map((w,i)=>({...w,text:i===0?"这是一段过长的文字内容":w.text}))}, context],
  ["metadata", raw, {...context,sceneInputMetadata:{}}],
  ["duration", raw, {...context,durationInFrames:53}],
  ["extra", {...raw,extra:true}, context],
]) { try { card.prepareCard(value, ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots}));
"""
        completed = subprocess.run(["node", "--input-type=module", "-", module.as_uri()], input=script, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["words"][2]["text"], "流量")
        self.assertEqual(result["rejected"], ["timing", "emphasis", "long", "metadata", "duration", "extra"])
        self.assertEqual(result["scene"], "full-frame")
        self.assertEqual(result["slots"], ["presenter"])

    def test_type_contrast_emphasis_evidence_is_hash_bound_and_stays_candidate(self) -> None:
        evidence = RUNTIME.parent / "qualification-evidence" / "type-contrast-emphasis"
        report = json.loads((evidence / "candidate-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "candidate_not_qualified")
        self.assertIsNone(report["human_visual_approval"])
        self.assertFalse(report["registry_updated"])
        self.assertEqual(report["implementation_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "type-contrast-emphasis.tsx").read_bytes()).hexdigest())
        self.assertEqual(report["contract_sha256"], hashlib.sha256((RUNTIME / "src" / "cards" / "type-contrast-emphasis.contract.json").read_bytes()).hexdigest())
        self.assertEqual(report["case_definition_sha256"], hashlib.sha256((RUNTIME / "qualification-cases" / "type-contrast-emphasis.json").read_bytes()).hexdigest())
        for comparison in report["upstream_comparison"].values():
            self.assertEqual(comparison["sha256"], hashlib.sha256((evidence / comparison["path"]).read_bytes()).hexdigest())
        for case_id in ("contrast-a", "contrast-b"):
            case_report = next(item for item in report["cases"] if item["case_id"] == case_id)
            for artifact in ("composite_preview", "settled_frame", "contact_sheet"):
                record = case_report[artifact]
                self.assertEqual(record["sha256"], hashlib.sha256((evidence / record["path"]).read_bytes()).hexdigest())

    def test_line_by_line_slide_preserves_pass_through_exit_and_shared_left_edge(self) -> None:
        source = RUNTIME / "src" / "cards" / "line-by-line-slide.tsx"
        contract_path = RUNTIME / "src" / "cards" / "line-by-line-slide.contract.json"
        cases_path = RUNTIME / "qualification-cases" / "line-by-line-slide.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertEqual(cases["implementation_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(cases["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(contract["scene_input_slots"], ["presenter"])
        self.assertEqual(contract["geometry"]["presenter_rect"], {"x": 180, "y": 900, "width": 720, "height": 800})
        self.assertEqual(contract["geometry"]["text_rect"], {"x": 90, "y": 240, "width": 900, "height": 580})
        self.assertEqual([cue["frame"] for cue in contract["sfx_cues"]], [7, 10, 14])
        for case in cases["cases"]:
            self.assertEqual(case["duration_frames"], 87)
            self.assertEqual(len(case["raw"]["lines"]), 3)
            self.assertEqual(case["scene_inputs"], [{"slot": "presenter", "kind": "presenter-alpha", "fixture_id": "alt-block-lines-presenter"}])

        source_text = source.read_text(encoding="utf-8")
        self.assertIn("enterStarts: [7, 10, 14]", source_text)
        self.assertIn("enterTravelEnds: [18, 22, 25]", source_text)
        self.assertIn("enterOpacityEnds: [29, 32, 35]", source_text)
        self.assertIn("exitStarts: [69, 70, 72]", source_text)
        self.assertIn("exitTravelStarts: [75, 77, 80]", source_text)
        self.assertIn("exitEnds: [83, 85, 86]", source_text)
        self.assertIn('textAlign:"left"', source_text)
        self.assertIn('transformOrigin:"0% 50%"', source_text)
        self.assertIn("opacity = enterP * (1 - exitP)", source_text)
        self.assertIn("xEnter + xExit", source_text)
        self.assertNotIn("host-placeholder", source_text)

        module = self.output / "line-by-line-slide.mjs"
        bundled = subprocess.run([str(RUNTIME / "node_modules" / ".bin" / "esbuild"), str(source), "--bundle", "--platform=node", "--format=esm", f"--outfile={module}"], capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const card = await import(process.argv[2]);
const context = {width:1080,height:1920,fps:24,durationInFrames:87,sceneInputMetadata:{presenter:{width:540,height:600}}};
const raw = {lines:["第一，写下问题","第二，只留变量","第三，跑小实验"],ink:"#171717"};
const good = card.prepareCard(raw, context); const rejected=[];
for (const [name,value,ctx] of [["two",{...raw,lines:raw.lines.slice(0,2)},context],["four-long",{...raw,lines:[...raw.lines,"这是一行明显过长的文字"]},context],["duration",raw,{...context,durationInFrames:86}],["metadata",raw,{...context,sceneInputMetadata:{}}],["extra",{...raw,extra:true},context]]) { try { card.prepareCard(value,ctx); } catch { rejected.push(name); } }
process.stdout.write(JSON.stringify({good,rejected,scene:card.candidateScene,slots:card.sceneInputSlots,frames:card.animationFrames}));
"""
        completed = subprocess.run(["node", "--input-type=module", "-", module.as_uri()], input=script, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["lines"][2], "第三，跑小实验")
        self.assertEqual(result["rejected"], ["two", "four-long", "duration", "metadata", "extra"])

    def test_line_by_line_slide_evidence_is_hash_bound_and_stays_candidate(self) -> None:
        evidence=RUNTIME.parent/"qualification-evidence"/"line-by-line-slide"
        report=json.loads((evidence/"candidate-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"],"candidate_not_qualified");self.assertIsNone(report["human_visual_approval"]);self.assertFalse(report["registry_updated"])
        self.assertEqual(report["implementation_sha256"],hashlib.sha256((RUNTIME/"src"/"cards"/"line-by-line-slide.tsx").read_bytes()).hexdigest())
        self.assertEqual(report["contract_sha256"],hashlib.sha256((RUNTIME/"src"/"cards"/"line-by-line-slide.contract.json").read_bytes()).hexdigest())
        self.assertEqual(report["case_definition_sha256"],hashlib.sha256((RUNTIME/"qualification-cases"/"line-by-line-slide.json").read_bytes()).hexdigest())
        for item in report["upstream_comparison"].values():self.assertEqual(item["sha256"],hashlib.sha256((evidence/item["path"]).read_bytes()).hexdigest())
        for case in report["cases"]:
            for key in ("composite_preview","settled_frame","contact_sheet"):
                item=case[key];self.assertEqual(item["sha256"],hashlib.sha256((evidence/item["path"]).read_bytes()).hexdigest())

    def test_qualification_fixture_identity_is_explicit_and_outside_common_closure(self) -> None:
        fixtures = json.loads((RUNTIME / "qualification-fixtures.json").read_text(encoding="utf-8"))
        closure = json.loads((RUNTIME / "closure-manifest.json").read_text(encoding="utf-8"))
        closure_paths = {record["path"] for record in closure["files"]}
        self.assertEqual(fixtures["schema_version"], "talkcraft-qualification-fixtures/v2")
        self.assertEqual(len(fixtures["assets"]), 16)
        self.assertEqual({asset["kind"] for asset in fixtures["assets"]}, {"audio", "image", "video", "video-alpha"})
        for asset in fixtures["assets"]:
            source = RUNTIME / asset["source"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), asset["sha256"])
            self.assertNotIn(asset["source"], closure_paths)

    def test_unknown_card_candidate_fails_before_browser_or_output(self) -> None:
        target = self.output / "unknown-card.mov"
        completed = subprocess.run(
            ["node", str(RUNTIME / "render.mjs"), "--probe-card", "unknown-card", "--case", "contrast-a",
             "--alpha", "true", "--output", str(target), "--browser", "/definitely/not/a/browser",
             "--runtime-root", str(RUNTIME)], cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("browser is unavailable", completed.stderr)
        self.assertFalse(target.exists())

    def test_time_domain_pure_functions_match_python_rounding_and_fail_closed(self) -> None:
        module = self.output / "time-domain.mjs"
        bundled = subprocess.run(
            [
                str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                str(RUNTIME / "src" / "time-domain.ts"),
                "--bundle", "--platform=node", "--format=esm", f"--outfile={module}",
            ],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const time = await import(process.argv[2]);
const scope = {
  fps: 24, chunkId: "chunk", spanId: "span", sceneId: "scene",
  chunk: {start: 48, end: 96}, span: {start: 24, end: 144}, scene: {start: 48, end: 120},
};
const rounded = [0.5, 1.5, 2.5].map((value) => time.secondsToFrame(value / 24));
const zeroes = [time.secondsToFrame(0), time.secondsToFrame(-0)];
const rejectedSeconds = [-0.1, -Number.MIN_VALUE, -1 / 48, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_VALUE];
const rejected = rejectedSeconds.map((value) => {
  try { time.secondsToFrame(value); return false; } catch { return true; }
});
const point = time.timeAtGlobalFrame(scope, 72);
const anchor = time.resolveAnchor(scope, [{id: "emphasis", sceneFrame: 24}], "emphasis");
const clock = {
  mediaId: "media", sourceTimebase: "cfr",
  timeline: {start: 48, end: 120}, source: {start: 30, end: 90},
  mediaFps: 20, playbackRate: 1,
};
const media = time.mediaTimeAtGlobalFrame(clock, 72);
let unknownAnchor = "";
let missingMedia = "";
try { time.resolveAnchor(scope, [{id: "emphasis", sceneFrame: 24}], "missing"); } catch (error) { unknownAnchor = error.message; }
try { time.mediaTimeAtGlobalFrame(null, 72); } catch (error) { missingMedia = error.message; }
process.stdout.write(JSON.stringify({rounded, zeroes, rejected, point, anchor, media, unknownAnchor, missingMedia}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()],
            input=script, capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["rounded"], [round(value) for value in (0.5, 1.5, 2.5)])
        self.assertEqual(result["zeroes"], [0, 0])
        self.assertEqual(result["rejected"], [True] * 6)
        self.assertEqual(result["point"]["outputFrame"], 24)
        self.assertEqual(result["point"]["spanLocalFrame"], 48)
        self.assertEqual(result["point"]["sceneLocalFrame"], 24)
        self.assertEqual(result["anchor"]["globalTimelineFrame"], 72)
        self.assertEqual(result["media"]["sourceFrame"], 50)
        self.assertEqual(result["media"]["sourceSeconds"], 2.5)
        self.assertEqual(result["unknownAnchor"], "unknown time anchor")
        self.assertIn("[MEDIA_TIMELINE_MAPPING_REQUIRED]", result["missingMedia"])

    def test_cfr_playback_seek_bridge_is_exact_and_rejects_unverified_cases(self) -> None:
        module = self.output / "media-playback.mjs"
        bundled = subprocess.run(
            [
                str(RUNTIME / "node_modules" / ".bin" / "esbuild"),
                str(RUNTIME / "src" / "media-playback.ts"),
                "--bundle", "--platform=node", "--format=esm", f"--outfile={module}",
            ],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(bundled.returncode, 0, bundled.stderr)
        script = r"""
const playback = await import(process.argv[2]);
const clock = {
  mediaId: "media-time-probe", sourceTimebase: "cfr",
  timeline: {start: 48, end: 120}, source: {start: 30, end: 90},
  mediaFps: 20, playbackRate: 1,
};
const media = {mediaId: "media-time-probe", src: "fixture.mp4", fps: 20, frameCount: 90};
const run = (nextClock, nextMedia, globalFrame = 95) => {
  try {
    return playback.resolveCfrPlaybackSeek({clock: nextClock, media: nextMedia, globalFrame, outputFrame: 2, compositionFps: 24});
  } catch (error) { return error.message; }
};
const good = run(clock, media);
const rate = run({...clock, playbackRate: 2, source: {start: 30, end: 150}}, {...media, frameCount: 150});
const alignment = run({...clock, source: {start: 1, end: 61}}, media);
const outside = run(clock, media, 120);
const identity = run(clock, {...media, mediaId: "other"});
const fractionalFps = run({...clock, mediaFps: 19.5, source: {start: 30, end: 88.5}}, {...media, fps: 19.5});
const range = run(clock, {...media, frameCount: 89});
process.stdout.write(JSON.stringify({good, rate, alignment, outside, identity, fractionalFps, range}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-", module.as_uri()],
            input=script, capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["good"]["sequenceFrom"], -45)
        self.assertEqual(result["good"]["trimBefore"], 36)
        self.assertAlmostEqual(result["good"]["sourceFrame"], 69 + 1 / 6)
        self.assertIn("[MEDIA_RATE_UNSUPPORTED]", result["rate"])
        self.assertIn("[SOURCE_START_NOT_COMPOSITION_FRAME_ALIGNED]", result["alignment"])
        self.assertIn("[GLOBAL_FRAME_OUTSIDE_MEDIA_TIMELINE]", result["outside"])
        self.assertIn("[MEDIA_FIXTURE_IDENTITY_MISMATCH]", result["identity"])
        self.assertIn("[MEDIA_FIXTURE_IDENTITY_MISMATCH]", result["fractionalFps"])
        self.assertIn("[MEDIA_SOURCE_RANGE_INVALID]", result["range"])



def _browser() -> Path | None:
    candidates = sorted(
        (Path.home() / "Library/Caches/ms-playwright").glob(
            "chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell"
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


class TalkCraftRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.browser = _browser()
        if cls.browser is None or shutil.which("node") is None or shutil.which("ffprobe") is None:
            raise unittest.SkipTest("local Remotion render dependencies are unavailable")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_production_composition_consumes_inherited_media_without_audio(self) -> None:
        runtime = self.output / "runtime"
        shutil.copytree(RUNTIME, runtime)
        runtime = runtime.resolve()
        registry_path = runtime / "card-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        card = next(item for item in registry["cards"] if item["card_id"] == "parallel-items-with-host")
        implementation = runtime / "src/cards/parallel-items-with-host.tsx"
        card["production"].update(
            status="qualified",
            derived_entrypoint="edit/hd/integrations/talkcraft/runtime/src/cards/parallel-items-with-host.tsx",
            implementation_sha256=hashlib.sha256(implementation.read_bytes()).hexdigest(),
            adapter_version="1.1.0",
            qualification_id="c" * 64,
        )
        registry["qualification_policy"].update(state="partially_qualified", production_enabled=True)
        contract_artifacts.write_json_artifact(registry_path, registry)

        fixtures = [
            runtime / "qualification-fixtures/alt-block-lines-host.webm",
            runtime / "qualification-fixtures/callout-laptop.jpg",
            runtime / "qualification-fixtures/callout-desk.jpg",
            runtime / "qualification-fixtures/callout-laptop.jpg",
        ]
        payload = brief()
        payload.update(card_id="parallel-items-with-host")
        payload["registry"] = {
            "version": registry["registry_version"],
            "sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        }
        payload["text"] = {"spoken": "并列展开", "display": "三个重点"}
        payload["events"] = [{"anchor_id": "word-001", "type": "text", "frame": 8, "payload": {"text": "并列展开"}}]
        payload["media"] = [
            {
                "job_path": f"inputs/media-{index}{fixture.suffix}",
                "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                "width": 540 if index == 0 else 1200,
                "height": 600 if index == 0 else 750,
                "fps": 24, "start_frame": 0, "end_frame": 530,
                "source_kind": "presenter" if index == 0 else "local_material",
                "authorization_ref": "user-provided/source.json",
            }
            for index, fixture in enumerate(fixtures)
        ]
        payload["frame_scope"].update(
            global_end_frame=530, span_end_frame=530, scene_duration_frames=530,
        )
        payload["render"].update(
            entrypoint=card["production"]["derived_entrypoint"],
            implementation_sha256=card["production"]["implementation_sha256"],
            adapter_version="1.1.0", qualification_id="c" * 64,
            alpha=False, duration_frames=530,
        )
        brief_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        brief_path = self.output / "production-brief.json"
        brief_path.write_bytes(brief_bytes)
        media_fds = [os.open(fixture, os.O_RDONLY) for fixture in fixtures]
        manifest = {
            "schema_version": "reference-process-media/v1",
            "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
            "media": [
                {
                    "media_ref": f"media-{index}", "fd": descriptor,
                    "sha256": payload["media"][index]["sha256"],
                    "byte_length": fixture.stat().st_size,
                }
                for index, (fixture, descriptor) in enumerate(zip(fixtures, media_fds))
            ],
        }
        manifest_path = self.output / "media-manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        manifest_fd = os.open(manifest_path, os.O_RDONLY)
        target = self.output / "production.mp4"
        try:
            completed = subprocess.run(
                [
                    "node", str(runtime / "render.mjs"),
                    "--brief", str(brief_path), "--media-manifest", f"/dev/fd/{manifest_fd}",
                    "--output", str(target), "--browser", str(self.browser),
                    "--runtime-root", str(runtime),
                ],
                    cwd="/", pass_fds=(manifest_fd, *media_fds), capture_output=True,
                text=True, timeout=180, check=False,
            )
        finally:
            os.close(manifest_fd)
            for descriptor in media_fds:
                os.close(descriptor)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema_version"], "talkcraft-production-result/v1")
        streams = self._probe(target)["streams"]
        self.assertEqual([item["codec_type"] for item in streams], ["video"])
        self.assertEqual(streams[0]["nb_frames"], "530")

    def _render(self, mode: str, *, alpha: bool, frames: int = 8, stdin: bool = False) -> Path:
        suffix = ".mov" if alpha else ".mp4"
        target = self.output / f"{mode}-{len(list(self.output.iterdir()))}{suffix}"
        arguments = [
                "--probe-mechanism", mode,
                "--frames", str(frames),
                "--alpha", str(alpha).lower(),
                "--output", str(target),
                "--browser", str(self.browser),
                "--runtime-root", str(RUNTIME),
        ]
        completed = subprocess.run(
            ["node", "--input-type=module", "-", *arguments]
            if stdin else ["node", str(RUNTIME / "render.mjs"), *arguments],
            input=(RUNTIME / "render.mjs").read_text(encoding="utf-8") if stdin else None,
            cwd="/" if stdin else RUNTIME,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        return target

    def _render_foundation(self, kind: str, order: str) -> tuple[Path, dict[str, object]]:
        target = self.output / f"{kind}-{order}.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-foundation", kind,
                "--sample-order", order,
                "--alpha", "false",
                "--output", str(target),
                "--browser", str(self.browser),
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest()
        )
        return target, result

    def _render_scene(self, order: str) -> tuple[Path, dict[str, object]]:
        target = self.output / f"scene-{order}.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-scene", "layout-camera",
                "--sample-order", order,
                "--alpha", "false",
                "--output", str(target),
                "--browser", str(self.browser),
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest()
        )
        return target, result

    def _render_time_domain(self, order: str) -> tuple[Path, dict[str, object]]:
        target = self.output / f"time-domain-{order}.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-time-domain", "timeline-anchor-media",
                "--sample-order", order,
                "--alpha", "false",
                "--output", str(target),
                "--browser", str(self.browser),
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest()
        )
        return target, result

    def _render_determinism(self, order: str) -> tuple[Path, dict[str, object]]:
        target = self.output / f"determinism-{order}.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-determinism", "bridge-isolation", "--sample-order", order,
                "--alpha", "false", "--output", str(target),
                "--browser", str(self.browser), "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        return target, result

    def _render_card_candidate(self, card_id: str, case_id: str) -> tuple[Path, dict[str, object]]:
        target = self.output / f"{card_id}-{case_id}.mp4"
        completed = subprocess.run(
            ["node", str(RUNTIME / "render.mjs"), "--probe-card", card_id, "--case", case_id,
             "--alpha", "false", "--output", str(target), "--browser", str(self.browser),
             "--runtime-root", str(RUNTIME)], cwd="/", capture_output=True, text=True, timeout=90, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        return target, result

    def _run_text_layout(self, mode: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        target = self.output / f"text-layout-{mode}.mp4"
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-text-layout", mode,
                "--alpha", "false",
                "--output", str(target),
                "--browser", str(self.browser),
                "--runtime-root", str(RUNTIME),
            ],
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
        )
        return completed, target

    @staticmethod
    def _scaled_rgb_frames(path: Path) -> list[bytes]:
        width, height = 135, 240
        raw = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(path),
                "-vf", f"scale={width}:{height}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = width * height * 3
        if len(raw) % frame_bytes:
            raise AssertionError("decoded foundation frames are truncated")
        return [raw[index:index + frame_bytes] for index in range(0, len(raw), frame_bytes)]

    @staticmethod
    def _media_roi_frames(path: Path) -> list[bytes]:
        width, height = 84, 152
        raw = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(path),
                "-vf", f"crop=420:760:108:1065,scale={width}:{height}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = width * height * 3
        if len(raw) % frame_bytes:
            raise AssertionError("decoded media ROI frames are truncated")
        return [raw[index:index + frame_bytes] for index in range(0, len(raw), frame_bytes)]

    @staticmethod
    def _determinism_roi_frames(path: Path, crop: str) -> list[bytes]:
        width, height = 108, 108
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"crop={crop},scale={width}:{height}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = width * height * 3
        if len(raw) % frame_bytes:
            raise AssertionError("decoded determinism ROI frames are truncated")
        return [raw[index:index + frame_bytes] for index in range(0, len(raw), frame_bytes)]

    def test_all_visual_foundations_render_and_random_seek_matches(self) -> None:
        contract = json.loads(
            (RUNTIME / "foundation-contract.json").read_text(encoding="utf-8")
        )
        for kind, key in (("backdrop", "backdrops"), ("frame", "frames")):
            with self.subTest(kind=kind):
                sequential_path, sequential = self._render_foundation(kind, "sequential")
                shuffled_path, shuffled = self._render_foundation(kind, "shuffled")
                variants = contract[key]
                expected_frames = len(variants) * 3
                self.assertEqual(sequential["variants"], variants)
                self.assertEqual(shuffled["variants"], variants)
                self.assertEqual(sequential["source_frames"], [0, 24, 48])
                self.assertEqual(shuffled["source_frames"], [48, 0, 24])
                self.assertEqual(sequential["frame_count"], expected_frames)
                for path in (sequential_path, shuffled_path):
                    streams = self._probe(path)["streams"]
                    video = next(item for item in streams if item["codec_type"] == "video")
                    self.assertEqual(
                        {key: video[key] for key in ("width", "height", "r_frame_rate", "nb_frames")},
                        {"width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": str(expected_frames)},
                    )
                    self.assertFalse(any(item["codec_type"] == "audio" for item in streams))

                ordered = self._scaled_rgb_frames(sequential_path)
                random_seek = self._scaled_rgb_frames(shuffled_path)
                self.assertEqual(len(ordered), expected_frames)
                self.assertEqual(len(random_seek), expected_frames)
                representatives = [ordered[index * 3 + 1] for index in range(len(variants))]
                self.assertEqual(len(set(representatives)), len(variants))
                self.assertTrue(all(max(frame) - min(frame) >= 20 for frame in representatives))
                shuffled_position = (1, 2, 0)
                for variant_index in range(len(variants)):
                    for source_index in range(3):
                        left = ordered[variant_index * 3 + source_index]
                        right = random_seek[variant_index * 3 + shuffled_position[source_index]]
                        mean_absolute_error = sum(
                            abs(a - b) for a, b in zip(left, right)
                        ) / len(left)
                        self.assertLess(mean_absolute_error, 1.0)

    def test_scene_planes_themes_and_camera_render_independently_of_seek_order(self) -> None:
        sequential_path, sequential = self._render_scene("sequential")
        shuffled_path, shuffled = self._render_scene("shuffled")
        self.assertEqual(sequential["variants"], ["light-push", "dark-pull"])
        self.assertEqual(sequential["source_frames"], [0, 36, 71])
        self.assertEqual(shuffled["source_frames"], [71, 0, 36])
        self.assertEqual(sequential["frame_count"], 6)
        ordered = self._scaled_rgb_frames(sequential_path)
        random_seek = self._scaled_rgb_frames(shuffled_path)
        self.assertEqual(len(ordered), 6)
        self.assertEqual(len(random_seek), 6)
        shuffled_position = (1, 2, 0)
        for variant_index in range(2):
            for source_index in range(3):
                left = ordered[variant_index * 3 + source_index]
                right = random_seek[variant_index * 3 + shuffled_position[source_index]]
                mean_absolute_error = sum(
                    abs(a - b) for a, b in zip(left, right)
                ) / len(left)
                self.assertLess(mean_absolute_error, 1.0)

        # The screen-space background remains dynamic while the world-space subject
        # visibly changes scale; this prevents a false pass from six static frames.
        for offset in (0, 3):
            first, middle, last = ordered[offset:offset + 3]
            self.assertNotEqual(first, middle)
            self.assertNotEqual(middle, last)

    def test_rendered_text_is_measured_and_invalid_layouts_fail_closed(self) -> None:
        completed, target = self._run_text_layout("valid")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema_version"], "talkcraft-runtime-text-layout-result/v1")
        self.assertEqual(result["text_layout"], "valid")
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["output_sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        video = next(item for item in self._probe(target)["streams"] if item["codec_type"] == "video")
        self.assertEqual(
            {key: video[key] for key in ("width", "height", "r_frame_rate", "nb_frames")},
            {"width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "1"},
        )

        failures = {
            "overflow": "measured text exceeds its approved bounds or capacity",
            "presenter": "measured text intersects the presenter safe zone",
            "world": "text must render in text.screen",
            "hidden": "text clipping is forbidden",
        }
        for mode, message in failures.items():
            with self.subTest(mode=mode):
                failed, rejected = self._run_text_layout(mode)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(message, failed.stderr)
                self.assertFalse(rejected.exists())

    def test_time_domain_render_is_independent_of_seek_order(self) -> None:
        sequential_path, sequential = self._render_time_domain("sequential")
        shuffled_path, shuffled = self._render_time_domain("shuffled")
        self.assertEqual(sequential["schema_version"], "talkcraft-runtime-time-domain-result/v1")
        self.assertEqual(sequential["time_domain"], "timeline-anchor-media")
        self.assertEqual(sequential["global_frames"], [48, 72, 95])
        self.assertEqual(shuffled["global_frames"], [95, 48, 72])
        self.assertEqual(sequential["frame_count"], 3)
        for path in (sequential_path, shuffled_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("width", "height", "r_frame_rate", "nb_frames")},
                {"width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "3"},
            )
            self.assertFalse(any(item["codec_type"] == "audio" for item in streams))
        ordered = self._media_roi_frames(sequential_path)
        random_seek = self._media_roi_frames(shuffled_path)
        self.assertEqual(len(set(ordered)), 3)
        for source_index, shuffled_index in enumerate((1, 2, 0)):
            mean_absolute_error = sum(
                abs(a - b) for a, b in zip(ordered[source_index], random_seek[shuffled_index])
            ) / len(ordered[source_index])
            self.assertLess(mean_absolute_error, 3.0)

    def test_anime_svg_and_three_render_independently_of_seek_order(self) -> None:
        sequential_path, sequential = self._render_determinism("sequential")
        shuffled_path, shuffled = self._render_determinism("shuffled")
        self.assertEqual(sequential["schema_version"], "talkcraft-runtime-determinism-result/v1")
        self.assertEqual(sequential["animation_local_frames"], [0, 24, 47])
        self.assertEqual(shuffled["animation_local_frames"], [47, 0, 24])
        self.assertEqual(sequential["scene_global_start"], 48)
        for path in (sequential_path, shuffled_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("width", "height", "r_frame_rate", "nb_frames")},
                {"width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "3"},
            )
            self.assertFalse(any(item["codec_type"] == "audio" for item in streams))
        for crop in ("900:430:90:130", "760:760:160:560"):
            ordered = self._determinism_roi_frames(sequential_path, crop)
            random_seek = self._determinism_roi_frames(shuffled_path, crop)
            self.assertEqual(len(set(ordered)), 3)
            for source_index, shuffled_index in enumerate((1, 2, 0)):
                mean_absolute_error = sum(
                    abs(a - b) for a, b in zip(ordered[source_index], random_seek[shuffled_index])
                ) / len(ordered[source_index])
                self.assertLess(mean_absolute_error, 3.0)

    def test_alt_block_candidate_renders_two_real_inputs_and_complete_action(self) -> None:
        first_path, first = self._render_card_candidate("alt-block-lines", "contrast-a")
        second_path, second = self._render_card_candidate("alt-block-lines", "contrast-b")
        self.assertEqual(first["schema_version"], "talkcraft-qualification-candidate-result/v1")
        self.assertFalse(first["qualification_granted"])
        self.assertEqual(first["generated_entry_sha256"], second["generated_entry_sha256"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "72"},
            )
            audio = next(item for item in streams if item["codec_type"] == "audio")
            self.assertEqual(audio["codec_name"], "aac")
        self.assertIsNone(first["presenter_fixture_sha256"])
        self.assertEqual(first["scene_input_fixture_sha256"], ["02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [16, 19])
        self.assertEqual([cue["anchor"] for cue in first["sfx_cues"]], ["block-0-complete", "block-1-complete"])
        presenter = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path), "-vf", "crop=760:960:160:900,scale=76:96",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 76 * 96 * 3
        presenter_frames = [presenter[index:index + frame_bytes] for index in range(0, len(presenter), frame_bytes)]
        self.assertEqual(len(presenter_frames), 72)
        self.assertGreater(sum(abs(a - b) for a, b in zip(presenter_frames[0], presenter_frames[48])) / frame_bytes, 1.0)
        settled = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", "1.2", "-i", str(first_path), "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=30, check=True,
        ).stdout
        def pixel(x: int, y: int) -> tuple[int, int, int]:
            offset = (y * 1080 + x) * 3
            return tuple(settled[offset:offset + 3])
        for point in ((100, 1000), (980, 1000), (100, 1600), (980, 1600)):
            self.assertTrue(all(channel > 245 for channel in pixel(*point)), point)
        self.assertTrue(any(channel < 220 for channel in pixel(540, 1100)))
        action = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path), "-vf", "crop=900:160:90:390,scale=180:32",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, timeout=30, check=True,
        ).stdout
        action_frame_bytes = 180 * 32
        action_frames = [action[index:index + action_frame_bytes] for index in range(0, len(action), action_frame_bytes)]
        counts = [sum(value < 245 for value in action_frames[index]) for index in (9, 11, 14, 17, 21, 49, 71)]
        self.assertEqual(counts[0], 0)
        self.assertTrue(all(left < right for left, right in zip(counts[1:4], counts[2:5])))
        self.assertEqual(counts[4], counts[5])
        self.assertEqual(counts[5], counts[6])
        pcm = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
             "-f", "f32le", "-"], capture_output=True, timeout=30, check=True,
        ).stdout
        samples = memoryview(pcm).cast("f")
        def rms(start: float, end: float) -> float:
            window = samples[int(start * 48000):int(end * 48000)]
            return (sum(value * value for value in window) / len(window)) ** 0.5
        self.assertEqual(rms(0.0, 0.62), 0.0)
        self.assertGreater(rms(0.72, 0.77), 0.02)
        self.assertLess(rms(0.79, 0.84), 0.02)
        self.assertGreater(rms(0.86, 0.94), 0.02)

    def test_count_badge_candidate_renders_two_inputs_and_all_five_actions(self) -> None:
        first_path, first = self._render_card_candidate("count-badge-title", "contrast-a")
        second_path, second = self._render_card_candidate("count-badge-title", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 80)
        self.assertEqual(first["sfx_cues"], [{
            "cueId": "number-color-lock", "frame": 15, "anchor": "number-color-lock",
            "name": "ui-pop", "assetKey": "talkcraft-ui-pop", "volume": 0.32, "playbackRate": 1,
        }])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "80"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")

        settled = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", "1.8", "-i", str(first_path), "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=30, check=True,
        ).stdout
        def pixel(x: int, y: int) -> tuple[int, int, int]:
            offset = (y * 1080 + x) * 3
            return tuple(settled[offset:offset + 3])
        for point in ((150, 1000), (930, 1000), (150, 1600), (930, 1600)):
            self.assertTrue(all(channel > 245 for channel in pixel(*point)), point)
        self.assertTrue(any(channel < 220 for channel in pixel(540, 1100)))

        def rendered_bbox(
            x_start: int, x_end: int, y_start: int, y_end: int,
            predicate: Callable[[int, int, int], bool],
        ) -> tuple[int, int, int, int]:
            matches = []
            for y in range(y_start, y_end):
                row = y * 1080 * 3
                for x in range(x_start, x_end):
                    offset = row + x * 3
                    red, green, blue = settled[offset:offset + 3]
                    if predicate(red, green, blue):
                        matches.append((x, y))
            self.assertTrue(matches)
            return (
                min(x for x, _ in matches), min(y for _, y in matches),
                max(x for x, _ in matches), max(y for _, y in matches),
            )

        number_box = rendered_bbox(250, 500, 200, 520, lambda red, green, blue: blue - red > 45 and blue - green > 45)
        quantifier_box = rendered_bbox(460, 800, 250, 500, lambda red, green, blue: max(red, green, blue) < 90)
        line2_box = rendered_bbox(250, 850, 480, 700, lambda red, green, blue: max(red, green, blue) < 90)
        self.assertLessEqual(abs(number_box[3] - quantifier_box[3]), 12)
        self.assertGreater(line2_box[1], max(number_box[3], quantifier_box[3]) + 24)

        def gray_roi(crop: str, width: int, height: int) -> list[bytes]:
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(first_path), "-vf", f"crop={crop},scale={width}:{height}",
                 "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, timeout=30, check=True,
            ).stdout
            size = width * height
            return [raw[index:index + size] for index in range(0, len(raw), size)]
        number = gray_roi("180:220:300:280", 60, 55)
        quantifier = gray_roi("300:110:470:370", 60, 22)
        line2 = gray_roi("500:120:290:480", 100, 24)
        dark = lambda frame: sum(value < 245 for value in frame)
        self.assertEqual(dark(number[9]), 0)
        self.assertGreater(dark(number[12]), 0)
        self.assertGreater(dark(number[36]), dark(number[34]))
        self.assertEqual(dark(quantifier[17]), 0)
        self.assertGreater(dark(quantifier[20]), 0)
        self.assertEqual(dark(line2[19]), 0)
        self.assertGreater(dark(line2[23]), 0)
        self.assertLessEqual(abs(dark(number[40]) - dark(number[79])), 2)
        self.assertLessEqual(abs(dark(quantifier[27]) - dark(quantifier[79])), 2)
        self.assertLessEqual(abs(dark(line2[27]) - dark(line2[79])), 2)

        pcm = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
             "-f", "f32le", "-"], capture_output=True, timeout=30, check=True,
        ).stdout
        samples = memoryview(pcm).cast("f")
        def rms(start: float, end: float) -> float:
            window = samples[int(start * 48000):int(end * 48000)]
            return (sum(value * value for value in window) / len(window)) ** 0.5
        self.assertEqual(rms(0.0, 0.55), 0.0)
        self.assertGreater(rms(0.64, 0.74), 0.02)

    def test_bar_chart_growth_candidate_renders_two_trends_with_five_aligned_bars_and_audio(self) -> None:
        first_path, first = self._render_card_candidate("bar-chart-growth", "contrast-a")
        second_path, second = self._render_card_candidate("bar-chart-growth", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 80)
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [10, 15, 16, 18, 19, 21, 28])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "80"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            settled = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,40)", "-frames:v", "1",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=30, check=True,
            ).stdout
            row = 650
            accent_columns = []
            for x in range(80, 1000):
                offset = (row * 1080 + x) * 3
                red, green, blue = settled[offset:offset + 3]
                if max(red, green, blue) - min(red, green, blue) > 70:
                    accent_columns.append(x)
            runs = []
            for x in accent_columns:
                if not runs or x > runs[-1][-1] + 1:
                    runs.append([x])
                else:
                    runs[-1].append(x)
            self.assertEqual(len(runs), 5)
            self.assertTrue(all(108 <= len(run) <= 114 for run in runs))
            for point in ((130, 1000), (950, 1000), (130, 1600), (950, 1600)):
                offset = (point[1] * 1080 + point[0]) * 3
                self.assertTrue(all(channel > 245 for channel in settled[offset:offset + 3]), point)
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
                 "-f", "f32le", "-"], capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.38), 0.0)
            self.assertGreater(rms(0.45, 0.62), 0.01)

    def test_callout_line_label_renders_two_measured_images_presenter_and_six_audio_actions(self) -> None:
        first_path, first = self._render_card_candidate("callout-line-label", "contrast-a")
        second_path, second = self._render_card_candidate("callout-line-label", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 118)
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [14, 19, 29, 34, 38, 48])
        self.assertEqual(first["scene_input_fixture_sha256"], ["d91b8db3ded913eac99572c2752aaec64b9aef1b37cdbb9be0ae58c0e0336af7", "02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertEqual(second["scene_input_fixture_sha256"], ["ddb49dc09886c023888ff53bcb2608fcb8f270645c0c09811016ad9ccec80e65", "02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertIsNone(first["presenter_fixture_sha256"])

        for path, fixture_name in ((first_path, "callout-laptop.jpg"), (second_path, "callout-desk.jpg")):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "118"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            settled_image = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,60),crop=300:180:180:180",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            fixture_image = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(RUNTIME / "qualification-fixtures" / fixture_name),
                 "-vf", "scale=720:450,crop=300:180:0:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            self.assertEqual(len(settled_image), len(fixture_image))
            self.assertLess(sum(abs(left - right) for left, right in zip(settled_image, fixture_image)) / len(settled_image), 12.0)
            presenter = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,60),crop=720:800:180:900,scale=144:160",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            self.assertGreater(sum(value < 220 for value in presenter), 1000)
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
                 "-f", "f32le", "-"], capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.55), 0.0)
            self.assertGreater(rms(0.60, 0.76), 0.01)
            self.assertGreater(rms(1.96, 2.20), 0.01)

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path),
             "-vf", "select='eq(n,13)+eq(n,16)+eq(n,18)+eq(n,24)+eq(n,28)+eq(n,32)+eq(n,33)+eq(n,36)+eq(n,37)+eq(n,43)+eq(n,47)+eq(n,52)+eq(n,94)+eq(n,109)+eq(n,117)',crop=1080:720:0:100,scale=270:180",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 270 * 180 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 15)
        mean_diff = lambda left, right: sum(abs(a - b) for a, b in zip(left, right)) / frame_bytes
        for left, right in ((0,1),(2,3),(4,5),(6,7),(8,9),(10,11)):
            self.assertGreater(mean_diff(frames[left], frames[right]), 0.01)
        self.assertLess(mean_diff(frames[11], frames[12]), 0.5)
        self.assertLess(mean_diff(frames[13], frames[14]), 0.2)
        self.assertLess(mean_diff(frames[0], frames[14]), 0.5)

    def test_behind_text_title_production_matches_approved_sample(self) -> None:
        evidence = RUNTIME.parent / "qualification-evidence/behind-text-title/production-batch-30-r1"
        payload = json.loads((evidence / "post-registration-proof.brief.json").read_text(encoding="utf-8"))
        registry_path = RUNTIME / "card-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        card = next(item for item in registry["cards"] if item["card_id"] == "behind-text-title")
        payload["registry"] = {
            "version": registry["registry_version"],
            "sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        }
        payload["render"]["qualification_id"] = card["production"]["qualification_id"]
        brief_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        brief_path = self.output / "production-brief.json"
        brief_path.write_bytes(brief_bytes)
        media_path = RUNTIME / "qualification-fixtures/alt-block-lines-host.webm"
        media_fd = os.open(media_path, os.O_RDONLY)
        manifest_fd = None
        try:
            manifest = {
                "schema_version": "reference-process-media/v1",
                "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
                "media": [{
                    "media_ref": "media-0", "fd": media_fd,
                    "sha256": hashlib.sha256(media_path.read_bytes()).hexdigest(),
                    "byte_length": media_path.stat().st_size,
                }],
            }
            manifest_path = self.output / "media-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_fd = os.open(manifest_path, os.O_RDONLY)
            target = self.output / "production.mp4"
            completed = subprocess.run(
                ["node", str(RUNTIME / "render.mjs"), "--brief", str(brief_path),
                 "--media-manifest", f"/dev/fd/{manifest_fd}", "--output", str(target),
                 "--browser", str(self.browser), "--runtime-root", str(RUNTIME)],
                cwd="/", pass_fds=(media_fd, manifest_fd), capture_output=True,
                text=True, timeout=120, check=False,
            )
        finally:
            os.close(media_fd)
            if manifest_fd is not None:
                os.close(manifest_fd)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        approved = json.loads((evidence / "qualification-record.json").read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads(completed.stdout)["output_sha256"],
            approved["identity"]["cases"][0]["output_sha256"],
        )

    def test_behind_text_title_renders_alpha_presenter_over_title_on_white_with_audio(self) -> None:
        first_path, first = self._render_card_candidate("behind-text-title", "contrast-a")
        second_path, second = self._render_card_candidate("behind-text-title", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 76)
        self.assertIsNone(first["presenter_fixture_sha256"])
        self.assertEqual(first["presenter_decode"], "vp9-alpha-transparent")
        self.assertEqual(first["scene_input_fixture_sha256"], ["02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertEqual(first["sfx_cues"], [{
            "cueId": "title-rise", "frame": 10, "anchor": "title-rise",
            "name": "impact-deep-whoosh", "assetKey": "talkcraft-impact-deep-whoosh",
            "volume": 0.3, "playbackRate": 1,
        }])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "76"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            settled = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,40)",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            def pixel(x: int, y: int) -> tuple[int, int, int]:
                offset = (y * 1080 + x) * 3
                return tuple(settled[offset:offset + 3])
            for point in ((20, 1000), (1060, 1000), (20, 1500), (1060, 1500), (540, 1800)):
                self.assertTrue(all(channel > 245 for channel in pixel(*point)), point)
            bottom_band = settled[1700 * 1080 * 3:]
            self.assertGreater(sum(value > 245 for value in bottom_band) / len(bottom_band), 0.999)
            title_roi = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,40),crop=1000:830:40:300",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            pixels = list(zip(title_roi[0::3], title_roi[1::3], title_roi[2::3]))
            self.assertGreater(sum(max(rgb) < 235 for rgb in pixels), 30000)
            self.assertGreater(sum(80 <= max(rgb) < 220 for rgb in pixels), 30000)
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
                 "-f", "f32le", "-"], capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.39), 0.0)
            self.assertGreater(rms(0.70, 0.95), 0.02)

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path),
             "-vf", "select='eq(n,9)+eq(n,14)+eq(n,18)+eq(n,24)+eq(n,40)+eq(n,75)',crop=1080:1280:0:360,scale=135:160",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 135 * 160 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 6)
        mean_diff = lambda left, right: sum(abs(a - b) for a, b in zip(left, right)) / frame_bytes
        self.assertGreater(mean_diff(frames[0], frames[1]), 0.5)
        self.assertGreater(mean_diff(frames[1], frames[2]), 0.1)
        self.assertGreater(mean_diff(frames[2], frames[3]), 0.1)
        self.assertGreater(mean_diff(frames[4], frames[5]), 0.05)

    def test_impact_open_title_renders_single_slam_two_corners_and_two_sfx_cues(self) -> None:
        first_path, first = self._render_card_candidate("impact-open-title", "contrast-a")
        second_path, second = self._render_card_candidate("impact-open-title", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 76)
        self.assertIsNone(first["presenter_fixture_sha256"])
        self.assertEqual(first["presenter_decode"], "vp9-alpha-transparent")
        self.assertEqual(first["scene_input_fixture_sha256"], ["02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [10, 17])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "76"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            settled = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,40)",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            def pixel(x: int, y: int) -> tuple[int, int, int]:
                offset = (y * 1080 + x) * 3
                return tuple(settled[offset:offset + 3])
            self.assertGreater(pixel(68, 68)[0] - pixel(68, 68)[1], 20)
            self.assertGreater(pixel(1012, 1852)[0] - pixel(1012, 1852)[1], 20)
            self.assertGreater(sum(value < 220 for value in settled[(850 * 1080 + 180) * 3:(1650 * 1080 + 900) * 3]), 1000)
            bottom_band = settled[1700 * 1080 * 3:]
            self.assertGreater(sum(value > 245 for value in bottom_band) / len(bottom_band), 0.99)
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.38), 0.0)
            self.assertGreater(rms(0.70, 0.95), 0.01)
            self.assertGreater(rms(0.95, 1.20), 0.01)

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path),
             "-vf", "select='eq(n,9)+eq(n,14)+eq(n,16)+eq(n,21)+eq(n,22)+eq(n,30)',crop=1080:920:0:120,scale=135:115",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 135 * 115 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 6)
        mean_diff = lambda left, right: sum(abs(a - b) for a, b in zip(left, right)) / frame_bytes
        self.assertGreater(mean_diff(frames[0], frames[1]), 1.0)
        self.assertGreater(mean_diff(frames[2], frames[3]), 0.3)
        self.assertGreater(mean_diff(frames[4], frames[5]), 0.2)

    def test_keyword_pop_highlight_renders_delayed_single_pop_and_resets_shake(self) -> None:
        first_path, first = self._render_card_candidate("keyword-pop-highlight", "contrast-a")
        second_path, second = self._render_card_candidate("keyword-pop-highlight", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 48)
        self.assertIsNone(first["presenter_fixture_sha256"])
        self.assertEqual(first["presenter_decode"], "vp9-alpha-transparent")
        self.assertEqual(first["scene_input_fixture_sha256"], ["02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertEqual(first["sfx_cues"], [{
            "cueId": "keyword-impact", "frame": 13, "anchor": "keyword-impact",
            "name": "wind-swoosh-short", "assetKey": "talkcraft-wind-swoosh-short",
            "volume": 0.5, "playbackRate": 1,
        }])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "48"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            settled = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,30)",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            bottom_band = settled[1650 * 1080 * 3:]
            self.assertGreater(sum(value > 245 for value in bottom_band) / len(bottom_band), 0.995)
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.50), 0.0)
            self.assertGreater(rms(0.75, 1.20), 0.01)

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path),
             "-vf", "select='eq(n,12)+eq(n,14)+eq(n,18)+eq(n,19)+eq(n,24)+eq(n,30)',crop=1080:220:0:1350",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 1080 * 220 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 6)
        mean_diff = lambda left, right: sum(abs(a - b) for a, b in zip(left, right)) / frame_bytes
        self.assertGreater(mean_diff(frames[0], frames[1]), 2.0)
        self.assertGreater(mean_diff(frames[1], frames[2]), 1.0)
        self.assertGreater(mean_diff(frames[2], frames[3]), 1.0)
        self.assertGreater(mean_diff(frames[3], frames[4]), 0.5)
        self.assertLess(mean_diff(frames[4], frames[5]), 0.2)
        def leftmost_dark(frame: bytes) -> int:
            dark = []
            for y in range(20, 210):
                for x in range(1080):
                    offset = (y * 1080 + x) * 3
                    if max(frame[offset:offset + 3]) < 100:
                        dark.append(x)
            return min(dark)
        self.assertGreaterEqual(leftmost_dark(frames[1]) - leftmost_dark(frames[0]), 4)
        self.assertLessEqual(leftmost_dark(frames[1]) - leftmost_dark(frames[0]), 10)

    def test_slab_punch_title_renders_center_expansion_hard_cut_and_two_sfx_cues(self) -> None:
        first_path, first = self._render_card_candidate("slab-punch-title", "contrast-a")
        second_path, second = self._render_card_candidate("slab-punch-title", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 64)
        self.assertIsNone(first["presenter_fixture_sha256"])
        self.assertEqual(first["presenter_decode"], "vp9-alpha-transparent")
        self.assertEqual(first["scene_input_fixture_sha256"], ["02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af"])
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [16, 21])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "64"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            settled = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,40)",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            bottom_band = settled[1650 * 1080 * 3:]
            self.assertGreater(sum(value > 245 for value in bottom_band) / len(bottom_band), 0.995)
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.60), 0.0)
            self.assertGreater(rms(0.66, 0.87), 0.005)
            self.assertGreater(rms(0.87, 1.30), 0.005)

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path),
             "-vf", "select='eq(n,9)+eq(n,14)+eq(n,16)+eq(n,20)+eq(n,21)+eq(n,25)+eq(n,40)',crop=1080:650:0:180,scale=216:130",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 216 * 130 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 7)
        mean_diff = lambda left, right: sum(abs(a - b) for a, b in zip(left, right)) / frame_bytes
        self.assertGreater(mean_diff(frames[0], frames[1]), 0.5)
        self.assertGreater(mean_diff(frames[2], frames[3]), 0.3)
        self.assertGreater(mean_diff(frames[3], frames[4]), 1.0)
        self.assertGreater(mean_diff(frames[4], frames[5]), 0.1)
        self.assertLess(mean_diff(frames[5], frames[6]), 0.05)

    def test_type_contrast_emphasis_renders_uneven_append_beats_and_two_stable_emphases(self) -> None:
        first_path, first = self._render_card_candidate("type-contrast-emphasis", "contrast-a")
        second_path, second = self._render_card_candidate("type-contrast-emphasis", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["frame_count"], 54)
        self.assertEqual(first["presenter_decode"], "vp9-alpha-transparent")
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [28, 40])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual({key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")}, {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "54"})
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")
            pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True, timeout=30, check=True).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 1.10), 0.0)
            self.assertGreater(rms(1.16, 1.55), 0.005)
            self.assertGreater(rms(1.66, 2.10), 0.005)

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path), "-vf", "select='eq(n,3)+eq(n,6)+eq(n,20)+eq(n,23)+eq(n,27)+eq(n,31)+eq(n,35)+eq(n,39)+eq(n,44)+eq(n,48)',crop=1080:580:0:240,scale=216:116", "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 216 * 116 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 10)
        mean_diff = lambda left, right: sum(abs(a - b) for a, b in zip(left, right)) / frame_bytes
        for left, right in ((0, 1), (2, 3), (4, 5), (6, 7), (7, 8)):
            self.assertGreater(mean_diff(frames[left], frames[right]), 0.08)
        self.assertLess(mean_diff(frames[8], frames[9]), 0.05)

    def test_line_by_line_slide_renders_staggered_stack_hold_and_delayed_right_exit(self) -> None:
        first_path, first = self._render_card_candidate("line-by-line-slide", "contrast-a")
        second_path, second = self._render_card_candidate("line-by-line-slide", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["frame_count"], 87)
        self.assertEqual([cue["frame"] for cue in first["sfx_cues"]], [7, 10, 14])
        for path in (first_path, second_path):
            streams=self._probe(path)["streams"]; video=next(item for item in streams if item["codec_type"]=="video")
            self.assertEqual({key:video[key] for key in ("codec_name","width","height","r_frame_rate","nb_frames")},{"codec_name":"h264","width":1080,"height":1920,"r_frame_rate":"24/1","nb_frames":"87"})
            self.assertEqual(next(item for item in streams if item["codec_type"]=="audio")["codec_name"],"aac")
            pcm=subprocess.run(["ffmpeg","-v","error","-i",str(path),"-map","0:a:0","-ac","1","-ar","48000","-f","f32le","-"],capture_output=True,timeout=30,check=True).stdout
            samples=memoryview(pcm).cast("f")
            def rms(start:float,end:float)->float:
                window=samples[int(start*48000):int(end*48000)];return(sum(value*value for value in window)/len(window))**0.5
            self.assertEqual(rms(0.0,0.28),0.0)
            self.assertGreater(rms(0.29,1.05),0.005)
        selected=subprocess.run(["ffmpeg","-v","error","-i",str(first_path),"-vf","select='eq(n,6)+eq(n,10)+eq(n,14)+eq(n,18)+eq(n,25)+eq(n,35)+eq(n,68)+eq(n,75)+eq(n,82)+eq(n,86)',crop=1080:650:0:210,scale=216:130","-vsync","0","-f","rawvideo","-pix_fmt","rgb24","-"],capture_output=True,timeout=30,check=True).stdout
        frame_bytes=216*130*3; frames=[selected[i:i+frame_bytes] for i in range(0,len(selected),frame_bytes)]
        self.assertEqual(len(frames),10)
        mean_diff=lambda left,right:sum(abs(a-b) for a,b in zip(left,right))/frame_bytes
        self.assertGreater(mean_diff(frames[0],frames[1]),0.1)
        self.assertGreater(mean_diff(frames[1],frames[2]),0.1)
        self.assertLess(mean_diff(frames[5],frames[6]),0.05)
        self.assertGreater(mean_diff(frames[6],frames[7]),0.1)
        self.assertGreater(mean_diff(frames[7],frames[8]),0.1)

    def test_shape_wipe_candidate_renders_real_ab_swap_without_exposed_seam(self) -> None:
        first_path, first = self._render_card_candidate("shape-wipe-transition", "contrast-a")
        second_path, second = self._render_card_candidate("shape-wipe-transition", "contrast-b")
        self.assertFalse(first["qualification_granted"])
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        self.assertEqual(first["layout"], "full-frame")
        self.assertEqual(first["frame_count"], 59)
        self.assertEqual(first["scene_input_fixture_sha256"], [
            "02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af",
            "27a5027a92f74e8de594e3fe9653857fd705e9fc05cea38fd8e96341c2d5cd45",
        ])
        self.assertEqual(second["scene_input_fixture_sha256"], [
            "02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af",
            "b314d507fbe21e9f9588ea216722861cc9423e66722a46396f6529f0d6816c5f",
        ])
        self.assertEqual(first["sfx_cues"], [{
            "cueId": "wipe-start", "frame": 22, "anchor": "wipe-start",
            "name": "wind-swoosh-short", "assetKey": "talkcraft-wind-swoosh-short",
            "volume": 0.35, "playbackRate": 1,
        }])
        for path in (first_path, second_path):
            streams = self._probe(path)["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            self.assertEqual(
                {key: video[key] for key in ("codec_name", "width", "height", "r_frame_rate", "nb_frames")},
                {"codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "59"},
            )
            self.assertEqual(next(item for item in streams if item["codec_type"] == "audio")["codec_name"], "aac")

        selected = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path),
             "-vf", "select='eq(n,0)+eq(n,29)+eq(n,58)',scale=135:240",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        frame_bytes = 135 * 240 * 3
        frames = [selected[index:index + frame_bytes] for index in range(0, len(selected), frame_bytes)]
        self.assertEqual(len(frames), 3)
        self.assertNotEqual(frames[0], frames[2])
        swap_frame = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(first_path), "-vf", "select=eq(n\\,29)",
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, timeout=30, check=True,
        ).stdout
        swap_pixels = list(zip(swap_frame[0::3], swap_frame[1::3], swap_frame[2::3]))
        palette = ((216, 216, 220), (138, 138, 142), (29, 29, 31))
        self.assertGreater(
            sum(min(sum(abs(channel - target) for channel, target in zip(pixel, color)) for color in palette) <= 24 for pixel in swap_pixels) / len(swap_pixels),
            0.998,
        )
        first_frame = frames[0]
        def pixel(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
            offset = (y * 135 + x) * 3
            return tuple(frame[offset:offset + 3])
        for point in ((0, 0), (134, 0), (0, 239), (134, 239)):
            self.assertTrue(all(channel > 245 for channel in pixel(first_frame, *point)), point)
        self.assertTrue(any(value < 80 for value in first_frame[(150 * 135 + 35) * 3:(235 * 135 + 100) * 3]))

        for output_path, fixture_name in (
            (first_path, "shape-wipe-ocean.webm"),
            (second_path, "shape-wipe-typing.webm"),
        ):
            final_frame = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(output_path), "-vf", "select=eq(n\\,58)",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            fixture_frames = []
            for source_frame in range(27, 31):
                fixture_frames.append(subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", str(RUNTIME / "qualification-fixtures" / fixture_name),
                     "-vf", f"select=eq(n\\,{source_frame}),scale=-1:1920,crop=1080:1920", "-frames:v", "1",
                     "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=30, check=True,
                ).stdout)
            baseline = min(
                fixture_frames,
                key=lambda frame: sum(abs(left - right) for left, right in zip(final_frame, frame)),
            )
            close_pixels = sum(
                sum(abs(final_frame[index + channel] - baseline[index + channel]) for channel in range(3)) <= 30
                for index in range(0, len(final_frame), 3)
            ) / (len(final_frame) / 3)
            self.assertGreater(close_pixels, 0.99)
            for x_start, y_start in ((0, 0), (1040, 0), (0, 1880), (1040, 1880)):
                differences = []
                for y in range(y_start, y_start + 40):
                    for x in range(x_start, x_start + 40):
                        offset = (y * 1080 + x) * 3
                        differences.extend(abs(final_frame[offset + channel] - baseline[offset + channel]) for channel in range(3))
                self.assertLess(sum(differences) / len(differences), 8.0)

            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(output_path), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
                 "-f", "f32le", "-"], capture_output=True, timeout=30, check=True,
            ).stdout
            samples = memoryview(pcm).cast("f")
            def rms(start: float, end: float) -> float:
                window = samples[int(start * 48000):int(end * 48000)]
                return (sum(value * value for value in window) / len(window)) ** 0.5
            self.assertEqual(rms(0.0, 0.9), 0.0)
            self.assertGreater(rms(1.0, 1.2), 0.03)

    def test_stdin_entrypoint_uses_verified_snapshot_outside_runtime_cwd(self) -> None:
        path = self._render("text", alpha=False, frames=3, stdin=True)
        video = next(item for item in self._probe(path)["streams"] if item["codec_type"] == "video")
        self.assertEqual(video["nb_frames"], "3")

    def test_stdin_entrypoint_writes_to_inherited_descriptor(self) -> None:
        target = self.output / "descriptor.mp4"
        arguments = [
            "--probe-mechanism", "data", "--frames", "3", "--alpha", "false",
            "--output", "", "--browser", str(self.browser),
            "--runtime-root", str(RUNTIME),
        ]
        with target.open("w+b") as output:
            arguments[arguments.index("--output") + 1] = f"/dev/fd/{output.fileno()}"
            completed = subprocess.run(
                ["node", "--input-type=module", "-", *arguments],
                input=(RUNTIME / "render.mjs").read_text(encoding="utf-8"),
                cwd="/", pass_fds=(output.fileno(),), capture_output=True,
                text=True, timeout=60, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        video = next(item for item in self._probe(target)["streams"] if item["codec_type"] == "video")
        self.assertEqual(video["nb_frames"], "3")

    def test_bootstrap_pins_manifest_and_rejects_changed_bytes(self) -> None:
        entrypoint = (RUNTIME / "render.mjs").read_text(encoding="utf-8")
        expected = re.search(r'EXPECTED_MANIFEST_SHA256 = "([0-9a-f]{64})"', entrypoint)
        self.assertIsNotNone(expected)
        manifest = (RUNTIME / "closure-manifest.json").read_bytes()
        self.assertEqual(expected.group(1), hashlib.sha256(manifest).hexdigest())
        changed_root = self.output / "changed-runtime"
        changed_root.mkdir()
        changed_root = changed_root.resolve()
        (changed_root / "closure-manifest.json").write_bytes(manifest + b" ")
        completed = subprocess.run(
            [
                "node", str(RUNTIME / "render.mjs"),
                "--probe-mechanism", "text", "--frames", "1", "--alpha", "false",
                "--output", str(self.output / "rejected.mp4"),
                "--browser", str(self.browser), "--runtime-root", str(changed_root),
            ],
            cwd="/", capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("manifest identity mismatch", completed.stderr)
        self.assertFalse((self.output / "rejected.mp4").exists())

    @staticmethod
    def _probe(path: Path) -> dict[str, object]:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_streams", "-show_format",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_four_mechanisms_render_through_one_locked_runtime(self) -> None:
        for mode in ("text", "data", "transition"):
            with self.subTest(mode=mode):
                path = self._render(mode, alpha=False)
                probe = self._probe(path)
                video = [item for item in probe["streams"] if item["codec_type"] == "video"]
                self.assertEqual(len(video), 1)
                self.assertEqual(
                    {key: video[0][key] for key in ("codec_name", "pix_fmt", "width", "height", "r_frame_rate", "nb_frames")},
                    {"codec_name": "h264", "pix_fmt": "yuv420p", "width": 1080, "height": 1920, "r_frame_rate": "24/1", "nb_frames": "8"},
                )
                self.assertFalse(any(item["codec_type"] == "audio" for item in probe["streams"]))

        alpha_path = self._render("annotation", alpha=True)
        alpha_probe = self._probe(alpha_path)
        video = next(item for item in alpha_probe["streams"] if item["codec_type"] == "video")
        self.assertEqual(video["codec_name"], "prores")
        self.assertTrue(video["pix_fmt"].startswith("yuva444p"))
        decoded = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(alpha_path),
                "-vf", "alphaextract", "-frames:v", "1", "-f", "rawvideo",
                "-pix_fmt", "gray", "-",
            ],
            capture_output=True,
            timeout=20,
            check=True,
        ).stdout
        self.assertEqual(len(decoded), 1080 * 1920)
        self.assertEqual(min(decoded), 0)
        self.assertEqual(max(decoded), 255)
        self.assertTrue(any(0 < value < 255 for value in decoded))

    def test_same_input_has_identical_decoded_frames(self) -> None:
        first = self._render("data", alpha=False, frames=5)
        second = self._render("data", alpha=False, frames=5)

        def frame_hash(path: Path) -> str:
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-f", "framemd5", "-"],
                capture_output=True,
                timeout=20,
                check=True,
            ).stdout
            return hashlib.sha256(raw).hexdigest()

        self.assertEqual(frame_hash(first), frame_hash(second))

    def test_only_qualified_cards_are_enabled_in_runtime_contract(self) -> None:
        contract = json.loads((RUNTIME / "runtime-contract.json").read_text(encoding="utf-8"))
        self.assertTrue(contract["production_cards_enabled"])
        self.assertTrue(contract["card_dispatch"]["production_composition_connected"])
        self.assertTrue(contract["qualification_candidate"]["production_media_binding_connected"])
        self.assertFalse(contract["span_chunk_enabled"])
        registry = json.loads((RUNTIME / "card-registry.json").read_text(encoding="utf-8"))
        self.assertTrue(registry["qualification_policy"]["production_enabled"])
        self.assertEqual(
            sum(card["production"]["status"] == "qualified" for card in registry["cards"]),
            108,
        )
        self.assertEqual(
            [card["card_id"] for card in registry["cards"] if card["production"]["status"] != "qualified"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
