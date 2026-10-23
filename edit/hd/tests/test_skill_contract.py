from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = ROOT / "skill-development/hd-talking-head"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
REFERENCE_ROOT = SKILL_ROOT / "references"
REFERENCE_PATHS = (
    SKILL_PATH,
    REFERENCE_ROOT / "broll-capability-router.md",
    REFERENCE_ROOT / "stage-contracts.md",
    REFERENCE_ROOT / "visual-quality-contract.md",
    REFERENCE_ROOT / "visual-assets-preflight.md",
    REFERENCE_ROOT / "job-workspace-contract.md",
    REFERENCE_ROOT / "open-source-adapter-matrix.md",
    REFERENCE_ROOT / "cover-contract.md",
    REFERENCE_ROOT / "production-bindings.md",
    REFERENCE_ROOT / "dependency-preflight.md",
)
OPENAI_PATH = SKILL_ROOT / "agents" / "openai.yaml"
STAGES = (
    "inspect",
    "content_analysis",
    "cover_direction",
    "cover",
    "speech_cleanup",
    "edit_structure",
    "visual_direction",
    "visual_canary",
    "visual_assets",
    "subtitles",
    "preview",
    "delivery",
)
SOURCE_KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)


def _frontmatter(source: str) -> tuple[dict[str, object], str]:
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", source, re.DOTALL)
    if match is None:
        raise AssertionError("SKILL.md must have one YAML frontmatter block")
    payload = yaml.safe_load(match.group(1))
    if type(payload) is not dict:
        raise AssertionError("frontmatter must be a mapping")
    return payload, match.group(2)


def _stage_rows(source: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in source.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0].strip("`") in STAGES:
            rows[cells[0].strip("`")] = cells
    return rows


class SkillEntrypointContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SKILL_PATH.read_text(encoding="utf-8")
        cls.frontmatter, cls.body = _frontmatter(cls.source)

    def test_metadata_identifies_the_existing_skill_and_trigger(self) -> None:
        self.assertEqual(self.frontmatter.get("name"), "hd-talking-head")
        description = self.frontmatter.get("description")
        self.assertIs(type(description), str)
        assert isinstance(description, str)
        self.assertTrue(description.startswith("Use when "))
        for phrase in ("原始口播视频", "文案", "人工确认"):
            self.assertIn(phrase, description)

    def test_progressive_reference_loading_is_explicit(self) -> None:
        for label, relative in (
            ("依赖预检、确认与安装合同", "references/dependency-preflight.md"),
            ("十二阶段执行合同", "references/stage-contracts.md"),
            ("每任务工作区与用户资料合同", "references/job-workspace-contract.md"),
            ("9:16 视觉质量合同", "references/visual-quality-contract.md"),
            ("B-roll 语义能力路由", "references/broll-capability-router.md"),
            ("正式生产绑定", "references/production-bindings.md"),
            ("视觉资产前置检查", "references/visual-assets-preflight.md"),
            ("封面输出与质量合同", "references/cover-contract.md"),
        ):
            self.assertIn(f"[{label}]({relative})", self.body)
        self.assertIn("启动 Job 时只完整阅读", self.body)
        self.assertIn("到达 `visual_direction` 时", self.body)
        self.assertIn("到达 `visual_assets` 时", self.body)

    def test_openai_interface_and_implicit_invocation_are_preserved(self) -> None:
        payload = yaml.safe_load(OPENAI_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["interface"]["display_name"], "HD 口播工作流")
        self.assertIn("原始口播视频和文案", payload["interface"]["short_description"])
        self.assertEqual(payload["interface"]["icon_small"], "./assets/icon-small.svg")
        self.assertEqual(payload["interface"]["icon_large"], "./assets/icon-large.png")
        self.assertEqual(payload.get("policy"), {"allow_implicit_invocation": True})

    def test_job_creation_and_resume_use_the_state_layer(self) -> None:
        for phrase in (
            "scripts/initialize_video_job.py",
            "edit/hd/tools/state.py",
            "`full-v2` workflow",
            "`load_job`",
            "`workflow.json` 是唯一状态事实",
        ):
            self.assertIn(phrase, self.body)

    def test_controller_preserves_twelve_stages_and_human_gates(self) -> None:
        order = " → ".join(f"`{stage}`" for stage in STAGES)
        self.assertIn(order, self.body)
        self.assertIn("封面有两个不可合并的人工门", self.body)
        self.assertIn("一次只运行一个 runner", self.body)
        self.assertIn("唯一 `ready_for_review`", self.body)
        self.assertIn("机器 QA PASS", self.body)
        self.assertIn("`delivery` 仍需最终确认", self.body)
        self.assertIn("仅有 `delivery approved` 状态不足以宣称正式完成", self.body)
        self.assertIn("audit_job_completion.py", self.body)

    def test_review_summary_has_one_stable_readable_shape(self) -> None:
        for line in (
            "阶段：<stage>",
            "状态：<ready_for_review | blocked>",
            "结果：<可审核产物与忠实简洁摘要>",
            "注意：<无已知问题 | 具体问题>",
            "下一步：<等待确认 | 修改意见 | blocked 选择>",
        ):
            self.assertIn(line, self.body)

    def test_confirmation_revision_and_stop_language_is_precise(self) -> None:
        for phrase in (
            "暂停阶段需要用户确认时",
            "只 `approve` 该阶段",
            "忠实简洁摘要",
            'artifact_scope=("seg-xxx",)',
            "不手工改 `workflow.json`",
            "明确停止",
        ):
            self.assertIn(phrase, self.body)
        section = self.body[self.body.index("## 3. ") : self.body.index("## 4. ")]
        self.assertEqual(section.count("`retry_same_strategy`"), 1)
        self.assertEqual(section.count("`replan_visual_direction`"), 1)
        option_lines = [
            line for line in section.splitlines() if line.startswith("- `")
        ]
        self.assertEqual(
            option_lines,
            [
                "- `retry_same_strategy`：保持已批准语义、来源类型和配方，在连接或运行条件恢复后重试。",
                "- `replan_visual_direction`：返回 `visual_direction`，由用户重新批准语义选择与来源绑定。",
            ],
        )
        self.assertIn("视觉来源执行阶段进入 `blocked`", section)
        self.assertIn("其他阶段保持当前阶段的修订边界", section)
        self.assertIn("`cover` 返回当前封面 revision", section)

    def test_visual_lifecycle_freezes_then_executes_then_reuses(self) -> None:
        for phrase in (
            "`visual_direction` 冻结 `source_bindings`",
            "编译 `ShotRecipe v2`",
            "`visual_canary` 只执行已批准配方",
            "`visual_assets` 严格复用",
            "不重新做来源判断",
            "VisualPlan schema v3",
            "不兼容旧 visual Job",
        ):
            self.assertIn(phrase, self.body)

    def test_visual_direction_orders_provider_check_acquisition_and_freeze(self) -> None:
        source = (REFERENCE_ROOT / "visual-assets-preflight.md").read_text(
            encoding="utf-8"
        )
        ordered = (
            "先根据语义确定 kind 和 provider",
            "在首次请求前完成所选 provider 的连接检查",
            "搜索、下载或生成并写入当前 Job",
            "冻结实际 `source_bindings` 并编译 ShotRecipe v2",
            "进入 `ready_for_review`",
        )
        positions = [source.index(phrase) for phrase in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_cover_keeps_its_code_generated_alternative(self) -> None:
        self.assertIn('alternative `aroll-code-cover`', self.body)
        self.assertIn("只适用于 `cover`", self.body)

    def test_cover_skill_and_chatcut_boundaries_are_preserved(self) -> None:
        for phrase in (
            "Punk-Skill/skills/punk-cover/SKILL.md",
            "封面有两个不可合并的人工门",
            "封面不制作或展示缩略图",
            "未明确要求时不上传 ChatCut",
            "不自动发布或发消息",
        ):
            self.assertIn(phrase, self.body)


class BrollSemanticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.router = (REFERENCE_ROOT / "broll-capability-router.md").read_text(
            encoding="utf-8"
        )
        cls.stages = (REFERENCE_ROOT / "stage-contracts.md").read_text(
            encoding="utf-8"
        )

    def test_five_sources_are_equal_semantic_choices(self) -> None:
        combined = "\n".join((self.skill, self.router, self.stages))
        for kind in SOURCE_KINDS:
            self.assertIn(f"`{kind}`", combined)
        for phrase in (
            "五类同级",
            "`none` / `single` / `hybrid`",
            "语义角色与素材来源分离",
            "不设来源优先级",
            "不设来源配额",
            "不做跨类替换",
            "不是降级关系",
        ):
            self.assertIn(phrase, combined)

    def test_each_source_keeps_its_distinct_execution_evidence(self) -> None:
        combined = "\n".join((self.skill, self.router, self.stages))
        for phrase in (
            "`code_generated` 调用现有依赖 Skill",
            "Skill 调用证据",
            "`external_stock`",
            "许可记录",
            "`ai_generated` 是主动语义选择",
            "不是其他来源无法执行后的替代项",
        ):
            self.assertIn(phrase, combined)

    def test_semantic_state_canary_approval_rejects_incomplete_machine_receipts(self) -> None:
        source = (REFERENCE_ROOT / "template-qualification.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "validate_human_approval",
            "qualification_evidence",
            "reviewed_input",
            "consumed_snapshot",
            "pixel_qa",
            "极简回执",
            "重新 FFprobe",
            "stable=4 / presence=8 / exit=4",
            "consumed sample 与 source A-roll",
            "现场抽取对照帧重新计算",
            "固定顺序",
        ):
            self.assertIn(phrase, source)

    def test_plan_modes_and_component_binding_are_explicit(self) -> None:
        for phrase in (
            "mode: none | single | hybrid",
            "kind",
            "semantic_role",
            "dependency_id",
            "entrypoint",
            "producer_version",
            "invocation_record",
            "license_snapshot",
        ):
            self.assertIn(phrase, self.router)

    def test_source_policy_has_no_fixed_order_or_window_quota(self) -> None:
        combined = "\n".join((self.skill, self.router, self.stages))
        for phrase in (
            "用户资料优先",
            "官方资料优先",
            "外部素材最后",
            "AI 生成最后",
            "任意五镜头窗口至少",
            "至少使用两种经批准来源组合",
            "来源类型占比",
        ):
            self.assertNotIn(phrase, combined)
        kind_pattern = "|".join(SOURCE_KINDS)
        self.assertIsNone(
            re.search(
                rf"`?(?:{kind_pattern})`?\s*(?:→|>)\s*`?(?:{kind_pattern})`?",
                combined,
            )
        )
        chinese_kind = (
            r"(?:用户(?:资料)?|本地(?:素材|资料)|官方(?:素材|资料)?|"
            r"代码(?:\s*B-roll)?|外部(?:素材库|素材)|AI(?:\s*生成)?)"
        )
        self.assertIsNone(
            re.search(rf"{chinese_kind}\s*(?:→|>)\s*{chinese_kind}", combined)
        )
        self.assertIn("来源组合始终由当前语义决定", self.router)
        self.assertIn("不设窗口数量或类型占比要求", self.router)


class StageReferenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (REFERENCE_ROOT / "stage-contracts.md").read_text(
            encoding="utf-8"
        )
        cls.rows = _stage_rows(cls.source)

    def test_stage_table_has_exact_twelve_rows(self) -> None:
        self.assertEqual(tuple(self.rows), STAGES)
        self.assertTrue(all(len(row) == 4 for row in self.rows.values()))

    def test_formal_v2_entrypoints_are_declared(self) -> None:
        for symbol in (
            "transcribe.transcribe_job",
            "speech_edit_v2.prepare_cleanup_proposal",
            "speech_edit_v2.render_edit",
            "visual_assets_v2.prepare_visual_assets_v2",
            "subtitles_v2.prepare_subtitles_v2",
            "preview_v2.prepare_preview_v2",
            "qa_delivery_v2.prepare_delivery_v2",
        ):
            self.assertIn(symbol, self.source)

    def test_visual_stage_responsibilities_do_not_overlap(self) -> None:
        direction = self.source[self.source.index("### 7. ") : self.source.index("### 8. ")]
        canary = self.source[self.source.index("### 8. ") : self.source.index("### 9. ")]
        assets = self.source[self.source.index("### 9. ") : self.source.index("### 10. ")]
        self.assertIn("冻结", direction)
        self.assertIn("编译", direction)
        self.assertIn("只执行", canary)
        self.assertIn("不做语义重选", canary)
        self.assertIn("相同 SHA-256 字节复用", assets)
        self.assertIn("不做语义重选", assets)

    def test_content_is_decided_once_and_cover_has_two_gates(self) -> None:
        for phrase in (
            "唯一语义事实源",
            "下游不重新调用 LLM 提炼",
            "`cover_direction` 是设计方向批准",
            "`cover` 是实际图片批准",
            "二者不可合并",
        ):
            self.assertIn(phrase, self.source)

    def test_speech_cleanup_keeps_independent_asr_cross_check(self) -> None:
        for phrase in (
            "第二次独立转写",
            "Whisper DTW",
            "词内口吃",
            "reviewed_cut_ranges",
            "二次 ASR 的时间戳不得直接当作原片绝对时间",
            "同词多次出现",
            "左右文",
            "命中有效语音",
            "人工审核确认后才能渲染",
        ):
            self.assertIn(phrase, self.source)

    def test_edit_and_delivery_media_invariants_are_preserved(self) -> None:
        for phrase in (
            "0.40 秒",
            "0.08 秒",
            "30ms",
            "1080×1080、SAR=9:16、DAR=9:16",
            "最终输出必须是 SAR=1:1、DAR=9:16",
            "默认无背景音乐",
            "用户对当前 `delivery` 回复确认",
        ):
            self.assertIn(phrase, self.source)

    def test_stage_outputs_cover_the_complete_review_chain(self) -> None:
        for path in (
            "01-inspect/report.json",
            "02-content-analysis/content-analysis.json",
            "03-cover-direction/person-reference.png",
            "04-cover/cover-<approved-ratio>.png",
            "05-speech-cleanup/",
            "06-edit-structure/edit-plan.json",
            "07-visual-direction/visual-plan.json",
            "08-visual-canary/visual-canary.mp4",
            "09-visual-assets/asset-manifest.json",
            "10-subtitles/subtitle-plan.json",
            "11-preview/review.mp4",
            "12-delivery/final.mp4",
        ):
            self.assertIn(path, self.source)


class VisualQualityReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (REFERENCE_ROOT / "visual-quality-contract.md").read_text(
            encoding="utf-8"
        )

    def test_canvas_memory_and_aroll_rules_are_preserved(self) -> None:
        for phrase in (
            "只输出 9:16",
            "固定为 24fps",
            "低内存",
            "重型渲染并发为 1",
            "A-roll 保留实拍背景",
            "不抠像",
            "一次最多两行",
            "整体旋转",
            "基线错位",
        ):
            self.assertIn(phrase, self.source)

    def test_broll_avatar_and_poster_density_rules_are_preserved(self) -> None:
        for phrase in (
            "有口播的 B-roll 必须有对应字幕",
            "头肩裁切",
            "不能只剩头部",
            "当前注册表和验证器结果",
            "默认 5–7 个有效信息单元",
            "不得为了密度编造信息",
        ):
            self.assertIn(phrase, self.source)

    def test_motion_and_delivery_checks_are_observable(self) -> None:
        for phrase in (
            "元素分层出现",
            "分层淡出",
            "最后 8–12 帧",
            "ffprobe",
            "qa-report.json",
            "delivery-manifest.json",
            "不得将“字幕与 B-roll 重叠为零”当作质量通过",
            "默认不加背景音乐",
        ):
            self.assertIn(phrase, self.source)

    def test_decorative_geometry_requires_visible_content_anchors(self) -> None:
        for phrase in (
            "装饰线、分割线、连接线",
            "必须明确依附",
            "禁止在空白区独立悬空",
            "没有可验证依附对象时必须不渲染",
            "不得穿过圆形、头像或文字",
        ):
            self.assertIn(phrase, self.source)


class WorkspaceAndCoverReferenceTests(unittest.TestCase):
    def test_workspace_index_and_precise_invalidation_are_preserved(self) -> None:
        source = (REFERENCE_ROOT / "job-workspace-contract.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "video/",
            "images/",
            "audio/",
            "documents/",
            "material-index.json",
            "不得重新扫描全部用户资料",
            "`material_id` 和 SHA-256",
            "只失效引用该资产",
        ):
            self.assertIn(phrase, source)

    def test_cover_revision_scope_does_not_repeat_content_analysis(self) -> None:
        source = (REFERENCE_ROOT / "cover-contract.md").read_text(encoding="utf-8")
        for phrase in (
            "仅修订 `cover`",
            "复用同一底图",
            "不重复生图",
            "不重新执行 `content_analysis`",
        ):
            self.assertIn(phrase, source)

    def test_cover_ratio_typography_and_person_constraints_are_preserved(self) -> None:
        source = (REFERENCE_ROOT / "cover-contract.md").read_text(encoding="utf-8")
        for phrase in (
            "只交付本 Job 已批准的比例",
            "构图样板，非最终生成图",
            "人物头脸保护区",
            "一至两行",
            "cover-base.png",
            "底图不承担最终中文",
            "`aroll-code-cover`",
        ):
            self.assertIn(phrase, source)


class CompletionClosureContractTests(unittest.TestCase):
    def test_material_receipts_and_confirmed_transaction_are_documented(self) -> None:
        skill = SKILL_PATH.read_text(encoding="utf-8")
        stages = (REFERENCE_ROOT / "stage-contracts.md").read_text(encoding="utf-8")
        workspace = (REFERENCE_ROOT / "job-workspace-contract.md").read_text(
            encoding="utf-8"
        )
        usage = (REFERENCE_ROOT / "material-usage-contract.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((skill, stages, workspace, usage))
        for phrase in (
            "material-usage.json",
            "complete_reference_declaration",
            "confirmed_plan_hash",
            "prepared",
            "material_committed",
            "workflow_revised",
            "state.revise",
            "旧 Job 不补造回执",
        ):
            self.assertIn(phrase, combined)
        self.assertNotIn("已使用资料的受控重新绑定与局部复用仍是待实现项", combined)

    def test_completion_audit_is_read_only_and_has_four_states(self) -> None:
        combined = "\n".join(
            (
                SKILL_PATH.read_text(encoding="utf-8"),
                (REFERENCE_ROOT / "stage-contracts.md").read_text(encoding="utf-8"),
            )
        )
        for phrase in (
            "scripts/audit_job_completion.py",
            "formal_complete",
            "legacy_external_approval",
            "incomplete",
            "inconsistent",
            "只读审计",
        ):
            self.assertIn(phrase, combined)

    def test_registered_templates_do_not_replace_current_job_canary(self) -> None:
        skill = SKILL_PATH.read_text(encoding="utf-8")
        qualification = (REFERENCE_ROOT / "template-qualification.md").read_text(
            encoding="utf-8"
        )
        registry = yaml.safe_load(
            (REFERENCE_ROOT / "verified-template-registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(registry["templates"]), 14)
        self.assertIn(
            "verified_third_party` → `verified_local_canonical` → `custom_fallback",
            skill,
        )
        self.assertIn("五套本地 canonical", skill + qualification)
        self.assertIn("当前 Job 的语义选择", skill + qualification)
        self.assertIn("canary 人工审批门", skill + qualification)


class ProductionAndPreflightReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.production = (REFERENCE_ROOT / "production-bindings.md").read_text(
            encoding="utf-8"
        )
        cls.preflight = (REFERENCE_ROOT / "visual-assets-preflight.md").read_text(
            encoding="utf-8"
        )

    def test_current_registry_and_job_are_the_production_authorities(self) -> None:
        for phrase in (
            "确认样片就是正式模板",
            "verified-template-registry.json",
            "当前 Job 已批准的 ShotRecipe 和 canary",
            "不把历史样片文案复制到新任务",
        ):
            self.assertIn(phrase, self.production)

    def test_font_avatar_sync_and_runtime_thresholds_remain_numeric(self) -> None:
        for phrase in (
            "字体文件或系统字体身份",
            "内部语义字段不得上屏",
            "0.38–0.52",
            "至少 0.68",
            "0.06–0.11",
            "最大音画误差为 2 帧",
            "soft-safe 边界为 y=1700",
            "hard-safe 边界为 y=1800",
            "只允许 1 个主 Agent",
        ):
            self.assertIn(phrase, self.production)

    def test_five_component_records_and_generation_accounting_are_explicit(self) -> None:
        for phrase in (
            "validate_shot_recipe_v2",
            "local_material",
            "official_material",
            "code_generated",
            "external_stock",
            "ai_generated",
            "license_snapshot",
            "model_is_available",
            "当前 generation",
            "外部请求数为 0",
            "资产类型字段是 `type`",
        ):
            self.assertIn(phrase, self.preflight)

    def test_named_people_keep_first_party_source_records(self) -> None:
        for phrase in (
            "命名人物",
            "第一方官方视频",
            "官方人物页图片",
            "姓名、职务、publisher、URL、访问时间",
        ):
            self.assertIn(phrase, self.production)

    def test_reference_projects_remain_registered_as_design_sources(self) -> None:
        for project in (
            "html-video",
            "erduo-broll-loop-engineering",
            "video-use",
            "video-autopilot-kit",
            "HyperFrames",
            "Remotion",
            "OpenMontage",
            "Generative-Media-Skills",
            "Open-Generative-AI",
            "OpenChatCut",
        ):
            self.assertIn(project, self.production)


class NeutralWorkflowLanguageTests(unittest.TestCase):
    def test_skill_documents_use_neutral_workflow_vocabulary(self) -> None:
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in REFERENCE_PATHS)
        for retained in (
            "safe_zone",
            "Job isolation",
            "内容真实性",
            "供应商连接状态",
            "账号连接",
            "字段边界",
            "路径约束",
            "记录一致性",
            "失败恢复",
            "产物一致性",
        ):
            self.assertIn(retained, corpus)


if __name__ == "__main__":
    unittest.main()
