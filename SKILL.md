---
name: hd-talking-head
description: Use when 用户提供原始口播视频和文案，希望完成封面、内容提炼、剪辑、A-roll、B-roll、字幕、样片、预览与交付，并在关键决策点人工确认。
---

# HD 口播全流程

本 Skill 是现有口播后期工作流的执行合同。每条视频建立一个独立 Job，以批准状态、文件哈希和人工审核推进。它只支持 `full-v2` 十二阶段流程和 VisualPlan schema v3 / ShotRecipe v2，不兼容旧 visual Job。旧 visual Job 重新执行 `visual_direction`，不读取或转换旧视觉计划。

本包不限定 Agent 品牌；需要能读取文件、运行脚本及尊重人工门的宿主。它包含流程与辅助脚本，不包含完整剪辑引擎；`<project>` 必须提供兼容的 `edit/hd` 运行时，不能把“复制 Skill 成功”当成全流程已可执行。完整包发布与跨 Agent 调用见 [发布与调用合同](references/release-contract.md)。

启动 Job 时只完整阅读：

- [依赖预检、确认与安装合同](references/dependency-preflight.md)
- [十二阶段执行合同](references/stage-contracts.md)
- [每任务工作区与用户资料合同](references/job-workspace-contract.md)

其他参考只在对应阶段加载：

- [9:16 视觉质量合同](references/visual-quality-contract.md)
- [统一头肩头像参数与校验](references/avatar-profile.md)（从 `visual_direction` 起，任何 B-roll 使用小头像时）
- [B-roll 语义能力路由](references/broll-capability-router.md)
- [语义动效规划接口与执行边界](references/semantic-motion.md)（关系图或五类状态动效进入候选时）
- [B-roll 开源能力适配矩阵](references/open-source-adapter-matrix.md)
- [第三方模板双输入实测资格](references/template-qualification.md)（新增、更新或审查模板登记时）
- [正式生产绑定](references/production-bindings.md)
- [视觉资产前置检查](references/visual-assets-preflight.md)
- [视觉修订与未变镜头复用](references/visual-revision-reuse.md)（修改已生成视觉计划或重试正式镜头时）
- [封面输出与质量合同](references/cover-contract.md)
- [封面入场、A-roll 开场与可选配乐](references/cover-opening-bgm.md)（设计开场、修改开头或用户要求 BGM 时）
- [权威素材使用回执与变更事务](references/material-usage-contract.md)（新增、替换或撤回用户资料时）

封面与可选 BGM 使用正式 `preview_v2.prepare_preview_v2(job, opening=..., music=...)`，参数、统一时间偏移、许可和审计附件以封面入场合同为准。默认无 BGM；启用时仍需本次选择和真实试听批准。其他机器缺少运行时时读取 [运行时部署](references/runtime-deployment.md)，先导出、校验、安装兼容代码，再执行依赖预检；不复制多个活动 Skill，不迁移旧 Job。

## 1. 新 Job 的连接检查与唯一目录

每个新视频都必须重新执行一次：

1. 取得视频绝对路径、文案文件绝对路径或聊天中的完整文案，以及用户提供的图片、视频、音频和文档。
2. 确认 `python3`、预检脚本和 `edit/hd/tools/state.py` 可用；运行 `python3 <skill>/scripts/verify_skill_release.py` 校验完整包。项目包含 TalkCraft 集成时，再运行 `python3 <project>/edit/hd/integrations/talkcraft/check_runtime.py`：它必须确认生产运行时依赖精确就位、上游基线可读、工作台调参和可选 Fish Audio 入口存在。生产运行时属于 108 张资格身份，不得用上游共享 runtime 自动覆盖或自动升级。缺文件、哈希变化或版本不一致时停止，列出准确的安装或路径修正动作，等待一次用户确认；不得现场重写发布清单掩盖缺失。
3. 运行 `scripts/initialize_video_job.py`，创建 Job isolation 所需的独立 workspace、去重后用户资料、`full-v2` workflow 和唯一输出树：

```bash
python3 <skill>/scripts/initialize_video_job.py \
  --project-root <project> \
  --jobs-root <project>/video-jobs \
  --title "<本期标题>" \
  --video <absolute-video> \
  --script <absolute-script> \
  --user-file <optional-material>
```

4. 将上次配置作为待确认草稿写入本 Job 的 `manifests/provider-config.json`，格式见依赖预检合同。不复制上次批准记录，不保存密钥。没有历史配置时根据本次实际能力填写，不虚构内置视频模型。
5. 用同一个已选 Python 运行 `scripts/dependency_preflight.py --job-context <workspace>/job-context.json`，报告写入 `<job>/manifests/dependency-preflight.json`。区分发现/安装、`configured`、`connected`、`callable`、`bound`；必需项未通过时停止。预检只做本地检查，不执行媒体生成。
6. 一次展示本 Job 的 provider、精确模型、endpoint 标识、参考图能力、原生 9:16、无声输出、连接证据、额度、并发，以及实际 Python、项目路径和合成器版本，询问是否修改。用户确认后调用 `scripts/confirm_job_setup.py --job-context <workspace>/job-context.json --user-confirmation "<本次确认原文>"`，记录 `manifests/setup-approval.json`；成功才进入 `inspect`。不得用测试文本或过去的“确认”代替本次批准。
7. 用户选择 `grok-imagine-video` 时，模型 ID 必须精确一致；不自动切换模型。后续 provider 请求前仍复核真实连接与额度，预检成功不等于付费生成授权。

`job-context.json` 还记录 `skill_release` 及真实 `runtime` 身份。初始化在创建目录前验证发布包及模块来源；`state.require_runnable` 对 Skill 管理的 Job 强制检查当前包、运行时、Job 绑定预检和配置批准。恢复同 Job 时复用未变化的批准；报告超过 24 小时需刷新，配置不变不重复询问。项目/解释器/源码/Skill 身份变化必须先做明确迁移，不能静默重写上下文或重做已批准素材。裸状态引擎测试不走此门，不能作为 Skill 的启动捷径。

输入缺视频或文案时，只询问缺失项，不猜路径。内联文案通过初始化器的 `--script-stdin` 或 `--script-text` 代替 `--script`：初始化器直接在新 workspace 内保存 UTF-8 原文并建立索引，不要求先存在 Job，不把输入写入 Skill 目录。长文案优先通过 stdin 传入，使用宿主参数数组/输入流，不将原文拼接进 shell。

初始化发布 workspace 时已写入 `initialization.json`。若后续初始化中断，使用同一 Python 执行 `scripts/initialize_video_job.py --resume-workspace <workspace>`，不再次使用新建参数。它只复用导入字节和同一 workflow，原件移走也不重新复制；运行时/发布身份变化、损坏文件或非空事务残留会停止并保留现场。已完成 Job 不自动补造丢失 workflow；没有恢复记录的历史 Job 不适用这个入口。具体边界见工作区合同。`workflow.json` 是唯一状态事实，不得手工修改。

## 2. 十二阶段与人工门

产品顺序固定为：

`inspect` → `content_analysis` → `cover_direction` → `cover` → `speech_cleanup` → `edit_structure` → `visual_direction` → `visual_canary` → `visual_assets` → `subtitles` → `preview` → `delivery`

一次只运行一个 runner。每次动作前重新 `load_job`，按产品顺序找到最早未完成阶段；它必须是唯一候选，且依赖全部 `approved`。候选缺失、不唯一或状态不一致时记录当前状态并明确停止。运行后再次加载，验证它是唯一 `ready_for_review`，报审后停止。机器 QA PASS、“整体继续”或进度要求都不能代替当前人工门。

封面有两个不可合并的人工门：`cover_direction` 批准内容与设计方向，`cover` 批准实际图片。文案理解、重点和关键词只在 `content_analysis` 决策一次；下游不得重新提炼或询问同一问题。

到达 `cover_direction` 和 `cover` 时完整阅读封面输出与质量合同，并显式加载 `gbro-cover-design`。子 Skill 内完成构图、参考图和提示词的三轮内部决策，不在这三轮中额外打断用户；只在最终封面成图报审。子 Skill 的 3:4 默认值不改写当前 Job 已批准比例。

## 3. 批准、修改和 blocked

每个 runner 只能推进到 `ready_for_review`。报审只展示当前阶段，并使用以下稳定格式：

```text
阶段：<stage>
状态：<ready_for_review | blocked>
结果：<可审核产物与忠实简洁摘要>
注意：<无已知问题 | 具体问题>
下一步：<等待确认 | 修改意见 | blocked 选择>
```

只有用户对当前产物无歧义地单独回复“确认”，才执行：重新加载 → 验证唯一 `ready_for_review` → 只 `approve` 该阶段 → 再加载并验证提交 → 有下游时只运行一个下一阶段。

最终 `delivery` 使用 `edit.hd.tools.delivery_approval.approve_delivery` 或正式 CLI 的 `approve --stage delivery` 分支：传入报审时保存的 revision、最终 MP4 SHA-256 和本次用户确认原文，具体参数及中断恢复见十二阶段合同的“最终确认入口”。不能用裸 `state.approve` 代替这条最终确认链路，也不能自行编写 `approval-receipt.json`。

修改意见只作用于当前待审或已批准阶段，将用户原意的忠实简洁摘要传入 `revise`。单个正式视觉段使用 `artifact_scope=("seg-xxx",)`；不手工改 `workflow.json`。

修订已有视觉计划时读取视觉修订合同。支持 `segment-inputs` 的运行时会在新计划及 canary 获批后，按完整输入指纹与原批准证据复用未变正式片段，不因其他镜头变化重复生成。此能力不改变下游状态 DAG，也不自动迁移历史成片。

用户资料变化必须先读工作区与素材回执合同，使用 `scripts/manage_user_materials.py` 的 `plan` → 人工确认 `plan_hash` → `apply --confirmed-plan-hash` 唯一入口。新 Job 的每个已发布阶段都必须包含完整 `material-usage.json`；无引用也发布空声明。已使用资料的替换/撤回依据当前回执计算 `earliest_stage` 和 `artifact_scope`，经 `prepared` → `material_committed` → `workflow_revised` 三阶段事务后恰好调用一次 `state.revise`。原字节和旧 material ID 保留，未变片段按输入指纹复用，受影响及下游阶段仍须逐门重审。回执缺失或身份不一致时 fail closed；旧 Job 不补造回执。资料变更期间暂停当前 Job runner，同一 `operation_id` 仅用于原事务恢复。

视觉来源执行阶段进入 `blocked` 后不自动重试，只展示两个互斥选项并明确停止：

- `retry_same_strategy`：保持已批准语义、来源类型和配方，在连接或运行条件恢复后重试。
- `replan_visual_direction`：返回 `visual_direction`，由用户重新批准语义选择与来源绑定。

其他阶段保持当前阶段的修订边界：报告准确状态后停止，不跳到尚未解锁的 `visual_direction`。`cover` 返回当前封面 revision，仍可由用户明确选择 code-generated alternative `aroll-code-cover`；它只适用于 `cover`，必须形成 revision 并重新报审，不能改写 B-roll 的来源选择。

## 4. B-roll 语义合同

B-roll 有且仅有五类同级来源：

```broll-source-policy
- `local_material`
- `official_material`
- `code_generated`
- `external_stock`
- `ai_generated`
kind_priority: none
selection_mode: none | single | hybrid
semantic_role_source_separation: required
quota: none
cross_kind_replacement: forbidden
```

每段根据语义选择 `none` / `single` / `hybrid`；语义角色与素材来源分离。不设来源优先级，不设来源配额，不做跨类替换，五类之间不是降级关系。`external_stock` 和 `ai_generated` 都是主动语义选择，不是其他来源无法执行后的替代项。

检索前先读当前 Job 已索引的用户资料，避免重复下载或生成相同内容；这是检索去重，不改变五类来源的语义平等地位。

- `local_material` 从当前 Job 的 `00-user-provided/material-index.json` 绑定少量用户图片、视频或文档。
- `official_material` 绑定第一方图片、视频或页面记录，保留来源、人物职务和内容真实性检查。
- `code_generated` 调用现有依赖 Skill，按 ShotRecipe 执行，并保留 Skill 调用证据、`dependency_id`、`entrypoint` 和 `producer_version`。
- `external_stock` 根据语义检索经批准 provider，保留许可记录、作者、来源 URL 和下载身份。
- `ai_generated` 是主动语义选择；它绑定 provider、精确模型、参考图和 generation identity。

`code_generated` 内部先运行 `scripts/verify_broll_template.py` 读取 `references/verified-template-registry.json`，再按当前语义与容量执行 `verified_third_party` → `verified_local_canonical` → `custom_fallback`。`structural` 改造不得沿用第三方验证身份；本地 canonical 仅能使用已登记的自有结构合同。实际文案填充后仍做当前文案三态 QA，并把 `template_origin` 与 `verification_id` 冻结进 ShotRecipe。编译和正式执行还会复核第三方真实登记与 `invocation_record.template_request` 的当前语义、容量、数字；未知来源或缺少当前请求时直接停止，不补默认值。登记检查强制核验两组历史真实执行附件及对应像素，不等于当前 Job 已渲染或已验收；维护登记时完整阅读双输入实测资格合同。

TalkCraft 108 张卡使用独立生产注册表，不冒充旧 `verified-template-registry`。当段落已选 `code_generated` 且适合 TalkCraft 时，必须先调用 `edit.hd.tools.talkcraft_matcher.match_cards`，把当前口播原文、语义目标、关键词、信息单元、组件角色、已有媒体和人物需求作为输入；再用 `build_binding` 冻结首选卡片。匹配器只读锁定的 `runtime/card-semantic-index.json`，运行时仍以 `runtime/card-registry.json` 的 qualified 身份为唯一准入依据；缺必需图像/视频/人物、角色不符或索引身份变化时显式停止，不在 adapter 或执行阶段重新选卡。这个自动选卡结果仍需要当前 Job 的 brief 参数化、三态 QA 和 canary 人工审批。

需要工作台微调时，先用 `edit.hd.tools.talkcraft_workbench.build_v4_edit_contract` 从当前 VisualPlan v4 和 draft brief bundles 生成稳定目标及可编辑字段，再用 `apply_v4_overrides` 生成新的 draft bundles。工作台只允许改合同公开的语境参数，当前只开放显示文案与深浅主题；未知目标、未知字段、非法值或计划身份变化都停止。回写结果保持 `editable_draft_only`，不得覆盖已批准 bundle，也不得跳过 canary 与人工审批。上游 Workbench 的 `overrides.json`、共享 React 19 / Remotion 4.0.519 只服务上游编辑与冒烟；正式渲染继续使用项目已资格的 React 18 / Remotion 4.0.520 运行时。

Fish Audio 仅是无成品配音时的可选输入方式，不改变默认“使用用户成品口播”的原则。只有用户明确选择合成配音、当前 Job 已确认精确模型/声音/费用且存在 `FISH_AUDIO_API_KEY` 时，才调用 `edit/hd/integrations/talkcraft/upstream/scripts/tts_fishaudio.py`；不得把密钥写入 Job 或 Skill，不得自动发起试音或付费请求。其输出音频和时间戳仍按用户提供音频同样进入 Job、校验并报审。

当前注册表有十四套可验证整屏模板：三套 `verified_third_party`、五套本地 canonical（`process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword`）、`hd-talking-head/relation-motion`，以及五套已登记 SemanticState（`replacement`、`threshold`、`delay`、`hierarchy`、`feedback`）。五套通用本地 canonical 共用 `scripts/local_canonical_renderer.cjs` 和 `scripts/local_canonical_adapter.py`；`evidence-source` 的主媒体可为图片或视频。RelationMotion 与 SemanticState 直接消费各自已冻结的语义动效计划。五套 SemanticState 的登记绑定双输入真实执行、逐态像素、动作顺序和用户批准的 25 秒头像合成样片；这些历史资格仍不取代当前 Job 的语义选择、实际填充三态 QA 与 canary 人工审批门。

`visual_direction` 冻结 `source_bindings`，并编译 `ShotRecipe v2`。`visual_canary` 只执行已批准配方，不做语义重选。`visual_assets` 严格复用 canary 字节和剩余已冻结配方，不重新做来源判断。

扩展第三方模板时，先按资格合同筛查完整文案可编辑范围、长度与中文字体、分词及语义动效；原生竖屏或换标题成功不等于可以直接用于本期内容。保留版本化的排除记录，不重复测试未变化的同一缺陷。

选中 `html-video/frame-data-rollup` 时，加载 [原生 DataRollup 执行接口](references/data-rollup-execution.md)；选中 `hyperframes/notification-cascade` 时，加载 [原生 Notification Cascade 执行接口](references/hyperframes-notification-execution.md)；选中 `hyperframes/chatgpt-exchange` 时，加载 [原生 ChatGPT Exchange 执行接口](references/hyperframes-chatgpt-exchange-execution.md)。第三套只用于“提问→回答→四项对照表→回读结论”的已验证语义，不代替普通对比海报。三者都通过包内 adapter 工厂接入正式执行器，不手工重画或停留在文字登记。新调用计划使用 `status=planned / exit_code=null`；实际成功以执行器输出证据为准，不能为了通过校验提前填写成功。其他模板没有这一执行验证时不得套用其结论。

所有视频和 B-roll 原生 1080×1920/24fps，不做横屏后裁切。B-roll 无常规口播字幕；小头像使用 head-shoulders 裁切。实际媒体由已冻结记录和 SHA-256 解析；不用空海报代替。切入切出用 8–12 帧 alpha 回到同时间轴 A-roll。渲染与外部生成串行，重型并发为 1。

到达 `visual_direction` 时必须完整阅读 9:16 视觉质量合同、B-roll 语义能力路由和开源能力适配矩阵。到达 `visual_assets` 时必须完整阅读正式生产绑定与视觉资产前置检查。本地绑定、字体、哈希、路由或 `safe_zone` 不合格时，先停止当前执行，不发出供应商请求。

## 5. 完成边界

Preview 使用剪辑后 A-roll 的口播音频主时钟，默认不加背景音乐。机器 QA PASS 只是 `ready_for_review`；`delivery` 仍需最终确认、正式回执及完成审计。仅有 `delivery approved` 状态不足以宣称正式完成。

交付后用 `scripts/audit_job_completion.py --workspace <workspace> --json` 做只读审计。它只能返回 `formal_complete`、`legacy_external_approval`、`incomplete` 或 `inconsistent` 四态，并展示已验证/未证明边界；不修改 workflow、回执或文件。新 Job 只有当前 revision 十二阶段全批准、交付媒体与 manifest 一致，且最终人工 approval receipt 精确绑定实际文件 SHA-256 时，才能返回 `formal_complete`。

正文默认从实拍 A-roll 引入话题，再切入语义对应的 B-roll；如启用封面，顺序为“封面 → A-roll 引入 → B-roll”，不能封面后立即被官方片头或海报接管。具体时长依据已批准口播动态决定，用户明确批准其他开场结构时记录例外。设计或修订开场时读取对应合同，只审核新增合成方式并复用现有资产；正式首帧、时间偏移与音乐实际可听性必须验证。

未明确要求时不上传 ChatCut 或其他外部编辑器，不自动发布或发消息。默认只允许 1 个主 Agent 内联执行；渲染与外部生成始终保持串行。
