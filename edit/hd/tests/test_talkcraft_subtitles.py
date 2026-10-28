from __future__ import annotations

import unittest
import copy
import json
import os
import subprocess
import tempfile
from unittest.mock import patch

from edit.hd.tools import subtitles_v2, talkcraft_subtitles


class TalkCraftSubtitleAdapterTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("HD_SUBTITLE_METADATA_TEST") == "1", "explicit metadata browser check")
    def test_metadata_checks_real_unbroken_word_width_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = f"""
              import {{createRequire}} from 'node:module';
              const require = createRequire({json.dumps(str(talkcraft_subtitles.ROOT / 'runtime/package.json'))});
              const {{bundle}} = require('@remotion/bundler');
              const {{selectComposition}} = require('@remotion/renderer');
              const serveUrl = await bundle({{
                entryPoint: {json.dumps(str(talkcraft_subtitles.ADAPTER / 'entry.tsx'))},
                rootDir: {json.dumps(str(talkcraft_subtitles.ADAPTER))},
                outDir: {json.dumps(directory)}, onProgress: () => {{}},
                webpackOverride: (config) => ({{...config, resolve: {{...config.resolve,
                  modules: [{json.dumps(str(talkcraft_subtitles.ROOT / 'runtime/node_modules'))}, ...(config.resolve?.modules ?? [])]}}}}),
              }});
              const results = [];
              for (const text of ['项目材料', 'iiiiiiiiiiii', '中华人民共和国国家安全法', 'WWWWWWWWWWWW']) {{
                const inputProps = {{schema_version: 2,
                  canvas: {{width:1080,height:1920,fps:24,frames:48}}, cues: [{{
                    cue_id:'cue-capacity',start:0.1,end:1.9,text,
                    words:[{{start:0.1,end:1.9,text_start:0,text_end:text.length}}],
                    emphasis:{{text_start:0,text_end:text.length,start:0.1,end:1.9}},
                    placement:'above_avatar',bottom:228,width:584,
                  }}]}};
                try {{
                  const composition = await selectComposition({{serveUrl,id:'TalkCraftSubtitles',inputProps}});
                  results.push({{accepted:true,frames:composition.durationInFrames}});
                }} catch (error) {{
                  results.push({{accepted:false,error:String(error)}});
                }}
              }}
              console.log(JSON.stringify(results));
            """
            result = json.loads(subprocess.check_output(
                ["node", "--input-type=module", "-e", script], text=True,
                cwd=talkcraft_subtitles.ROOT / "runtime", timeout=120))
        self.assertEqual([item["accepted"] for item in result], [True, True, False, False])
        self.assertEqual([item["frames"] for item in result[:2]], [48, 48])
        for item in result[2:]:
            self.assertIn("cue-capacity", item["error"])
            self.assertIn("complete word", item["error"])
            self.assertIn("does not fit", item["error"])

    def test_narrow_lines_keep_words_keywords_and_punctuation_together(self) -> None:
        module = (talkcraft_subtitles.ADAPTER / "line-units.mjs").as_uri()
        script = f"""
          import {{lineUnits}} from {json.dumps(module)};
          const text = '整份合同、年报、项目材料';
          const units = lineUnits(text);
          const protectedUnits = lineUnits(text, {{text_start: 8, text_end: 12}});
          const quoted = '“年报”，还有😀';
          console.log(JSON.stringify({{
            words: units.map((u) => text.slice(u.start, u.end)),
            protectedWords: protectedUnits.map((u) => text.slice(u.start, u.end)),
            quotedWords: lineUnits(quoted).map((u) => quoted.slice(u.start, u.end))
          }}));
        """
        result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], text=True))
        self.assertEqual("".join(result["words"]), "整份合同、年报、项目材料")
        self.assertIn("年报、", result["words"])
        self.assertIn("项目材料", result["protectedWords"])
        self.assertIn("“年报”，", result["quotedWords"])
        self.assertIn("😀", result["quotedWords"])

    def test_cue_input_preserves_multi_character_word_timing_and_utf16_offsets(self) -> None:
        cue = {"id": "cue-001", "start": 1.0, "end": 2.0, "text": "A😀你", "emphasis_words": ["😀你"]}
        words = [
            {"text": "A😀", "start": 0.8, "end": 1.4},
            {"text": "你", "start": 1.35, "end": 1.8},
        ]
        result = talkcraft_subtitles.cue_input(cue, words)
        self.assertEqual([(item["start"], item["end"]) for item in result["words"]], [(1.0, 1.4), (1.35, 1.8)])
        self.assertEqual([(item["text_start"], item["text_end"]) for item in result["words"]], [(0, 3), (3, 4)])
        self.assertEqual(result["emphasis"], {"text_start": 1, "text_end": 4, "start": 1.0, "end": 1.8})

    def test_renderer_binding_rejects_missing_or_tampered_renderer(self) -> None:
        plan = {"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 24}, "cues": []}
        renderer_input = talkcraft_subtitles.renderer_input(plan, [])
        identity = {"id": "renderer"}
        payload = {"schema_version": 4, "render_plan": plan, "renderer_input": renderer_input, "renderer": identity}
        with patch.object(talkcraft_subtitles, "identity", return_value=identity):
            talkcraft_subtitles.validate_binding(payload)
            for changed in (dict(payload, schema_version=3), dict(payload, renderer={"id": "tampered"})):
                with self.assertRaises(talkcraft_subtitles.TalkCraftSubtitleError):
                    talkcraft_subtitles.validate_binding(changed)

    def test_renderer_binding_rejects_tampered_bottom(self) -> None:
        plan = {"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 24},
                "cues": [{"id": "cue-1", "start": 0.0, "end": 0.5,
                          "text": "测试", "emphasis_words": [],
                          "safe_zones": {"face": None}}]}
        renderer_input = talkcraft_subtitles.renderer_input(plan, [{
            "cue_id": "cue-1", "start": 0.0, "end": 0.5, "text": "测试",
            "words": [], "emphasis": None, "placement": "standard", "bottom": 350,
        }])
        identity = {"id": "renderer"}
        payload = {"schema_version": 4, "render_plan": plan,
                   "renderer_input": renderer_input, "renderer": identity}
        with patch.object(talkcraft_subtitles, "identity", return_value=identity):
            talkcraft_subtitles.validate_binding(payload)
            tampered = copy.deepcopy(payload)
            tampered["renderer_input"]["cues"][0]["bottom"] = 349
            with self.assertRaises(talkcraft_subtitles.TalkCraftSubtitleError):
                talkcraft_subtitles.validate_binding(tampered)

    def test_renderer_binding_requires_the_actual_broll_card_width(self) -> None:
        cue = {"id":"cue-1", "start":0.0, "end":0.5, "text":"测试",
               "emphasis_words":[], "safe_zones":{"face":{"x":672,"y":1372,"width":328,"height":328}},
               "box":{"x":80,"y":1462,"width":584,"height":230}, "bottom":228}
        rendered = talkcraft_subtitles.cue_input(cue, [{"text":"测试","start":0.0,"end":0.5}],
                                                placement="above_avatar")
        self.assertEqual(rendered["width"], 584)
        plan = {"canvas":{"width":1080,"height":1920,"fps":24,"frames":24}, "cues":[cue]}
        identity = {"id":"renderer"}
        payload = {"schema_version":4, "render_plan":plan,
                   "renderer_input":talkcraft_subtitles.renderer_input(plan,[rendered]), "renderer":identity}
        with patch.object(talkcraft_subtitles, "identity", return_value=identity):
            talkcraft_subtitles.validate_binding(payload)
            for width in (640, 583, True, None):
                changed = copy.deepcopy(payload)
                if width is None:
                    changed["renderer_input"]["cues"][0].pop("width")
                else:
                    changed["renderer_input"]["cues"][0]["width"] = width
                with self.subTest(width=width), self.assertRaisesRegex(
                        talkcraft_subtitles.TalkCraftSubtitleError, "width changed"):
                    talkcraft_subtitles.validate_binding(changed)

    def test_four_approved_emphasis_cues_are_allowed(self) -> None:
        terms = ("认知", "流程", "效率", "价值")
        plan = {"cues": [
            {"id": f"cue-{index}", "segment_id": "s", "start": index * 20.0,
             "end": index * 20.0 + 1, "text": term, "emphasis_words": [term]}
            for index, term in enumerate(terms)
        ]}
        segments = [{"segment_id": "s", "shot_recipe": {"mode": "none"}, "content_item_ids": ["i"]}]
        subtitles_v2.validate_emphasis(plan, {"i": terms}, segments,
                                      emphasis_times={cue["id"]: cue["start"] for cue in plan["cues"]})


if __name__ == "__main__":
    unittest.main()
