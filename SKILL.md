---
name: hd-talking-head
description: Use when 用户提供原始口播视频和文案，希望完成封面、内容提炼、剪辑、A-roll、B-roll、字幕、样片、预览与交付，并在关键决策点人工确认。
---

# HD 口播全流程

本 Skill 是现有口播后期工作流的执行合同。每条视频建立一个独立 Job，以批准状态、文件哈希和人工审核推进。它只支持 `full-v2` 十二阶段流程和 VisualPlan schema v3 / ShotRecipe v2，不兼容旧 visual Job。旧 visual Job 重新执行 `visual_direction`，不读取或转换旧视觉计划。

本包不限定 Agent 品牌；需要能读取文件、运行脚本及尊重人工门的宿主。它包含流程与辅助脚本，不包含完整剪辑引擎；`<project>` 必须提供兼容的 `edit/hd` 运行时，不能把“复制 Skill 成功”当成全流程已可执行。完整包发布与跨 Agent 调用见 [发布与调用合同](references/release-contract.md)。

本 Skill 的职责是编排和验收，不重新实现已有 Skill 的媒体能力。每个阶段先按依赖清单确定能力提供方，再读取该 Skill 的原始说明并实际调用其入口，最后核对本次输入身份、调用记录、真实产物及阶段质量门。`已安装`、`预检可调用`、`实际调用成功`、`产物验收通过`是四种不同状态；不得用阅读说明、借用参数或运行无关 helper 冒充该阶段由第三方 Skill 完成。现有 Skill 覆盖不了的 Job 状态、素材绑定及项目专属 QA，才由本包和 `edit/hd` 执行；能力未接通时停在该阶段，不能悄悄切回自写实现。

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
- [上游场景 Skill 与本地渲染合同](references/upstream-scene-skills.md)
- [生成型 B-roll 的子 Skill 编排](references/generated-broll-skills.md)（白板、拼贴、手绘动画进入候选时；区分真实调用测试与正式准入）
- [官方视频下载 Skill 调用与验收](references/official-video-acquisition.md)（`official_material` 选中在线视频时）
- [第三方模板双输入实测资格](references/template-qualification.md)（新增、更新或审查模板登记时）
- [正式生产绑定](references/production-bindings.md)
- [Huashu 原生动效接入](references/huashu-native-motion.md)（选择 Huashu 原生动效或检查其 brief、时间轴与调用边界时）
- [视觉资产前置检查](references/visual-assets-preflight.md)
- [视觉修订与未变镜头复用](references/visual-revision-reuse.md)（修改已生成视觉计划或重试正式镜头时）
- [封面输出与质量合同](references/cover-contract.md)
- [封面标题视觉样式合同](references/cover-title-style.md)（封面方向或标题排版时；含项目内 Punk 封面路线）
- [Guizang Swiss 9:16 封面适配](references/guizang-swiss-9x16-adapter.md)（仅用户明确选择该极简风时加载；不作为默认封面风格）
- [封面入场、A-roll 开场与可选配乐](references/cover-opening-bgm.md)（设计开场、修改开头或用户要求 BGM 时）
- [全片字幕样式与上游调用](references/subtitle-style-contract.md)（进入 `subtitles` 或检查字幕预览时）
- [A-roll 透明贴片调用与验收](references/aroll-overlay-contract.md)（纯 A-roll 需要语义图形时）
- [权威素材使用回执与变更事务](references/material-usage-contract.md)（新增、替换或撤回用户资料时）

封面与可选 BGM 使用正式 `preview_v2.prepare_preview_v2(job, opening=..., music=...)`，参数、统一时间偏移、许可和审计附件以封面入场合同为准。默认无 BGM；启用时仍需本次选择和真实试听批准。其他机器缺少运行时时读取 [运行时部署](references/runtime-deployment.md)，先导出、校验、安装兼容代码，再执行依赖预检；不复制多个活动 Skill，不迁移旧 Job。

## 1. 新 Job 的连接检查与唯一目录

每个新视频都必须重新执行一次：

依赖预检前，先运行 `python3 <skill>/scripts/ensure_visual_broll_skills.py --project-root <project> --skill doudou-remotion-whiteboard`，准备本项目新增的手绘白板依赖；只安装项目 vendor 固定提交，不改变全局 Skill。

同样执行 `ensure_visual_broll_skills.py --project-root <project> --skill gbro-collage-broll`，补齐用户指定的半调纸拼贴 Skill；启动清单只检查原始说明及文件完整性，不执行其 Gemini 自检或视频脚本。选中后实际执行隐喻与静帧设计，内置生图和 Lovart Kling O1 分别负责图片与视频，调用约束及拼贴质量检查见[GBRO 编排](references/generated-broll-skills.md#gbro-调用约束与拼贴验收)。不因新增路线自动替换已批准 B-roll。

同样先执行 `ensure_visual_broll_skills.py --project-root <project> --skill lemo-opuscar` 和 `--skill onetake`，补齐项目内固定源码及缺失的本地渲染运行时。实际选中后仍须通过绑定探针；准备成功不是出片验收。详见[上游场景 Skill 与本地渲染合同](references/upstream-scene-skills.md)；不得全局安装、自动更新或运行自动 reset/setup。

选择 Huashu 原生动效时，先读[Huashu 原生动效接入](references/huashu-native-motion.md)，由我们的 adapter 实际调用固定 vendor 的 `render.py --spec`，不修改第三方源码、模板、字体或动效。当前已登记 `y1_kurzgesagt` 三节点机制流程（`title` / `point` / `flow`，不含 hierarchy、`highlight` 或 `enter`）、`y2_vox` 单张横向来源图的整行高亮，以及 `t2_keynote_ui` 的三张原生功能卡（仅 `product_features`）。Vox 调用先按该页的输入版式与实测避让规则准备真实材料，不用窄框强推近，也不裁掉来源信息；当前镜头仍须检查高亮过程中的正文、脚注、标签和圆窗/字幕避让。三条路线共用进程内原生启动器，独立子进程的连接等待容量统一为 64，不改变上游文件或原生动效。普通 Job 只消费已登记能力，不重复资格实验；未接通或验收失败时暂停对应路线，不自动修改第三方、重试、切换或加入自写 fallback。

另执行同一脚本的 `--skill adu-motion-video`，检查 Adu 最小本地运行时，缺失时仅在项目 vendor 准备。Adu 只准备渲染所需环境，不调用人物提取、配音或 mix。选中 Adu 后必须通过其独立 binding probe。

1. 取得视频绝对路径、文案文件绝对路径或聊天中的完整文案，以及用户提供的图片、视频、音频和文档。
2. 确认 `python3`、预检脚本和 `edit/hd/tools/state.py` 可用；先运行 `python3 <skill>/scripts/ensure_punk_cover.py --project-root <project>`，检查项目内 Punk 封面 Skill，缺失时自动安装已测试版本到 `skill-development/vendor/Punk-Skill`，已有且完整时不重复安装；异常目录或安装失败时保留现场并停止，不改全局 Skill。同时检查项目内 `skill-development/vendor/OpenMontage-video-download/.agents/skills/video-download/SKILL.md` 及固定提交，缺失时按[官方视频下载合同](references/official-video-acquisition.md)安装到项目内，不改全局 Skill。随后运行 `python3 <skill>/scripts/verify_skill_release.py` 校验完整包，并运行 `python3 <project>/edit/hd/integrations/talkcraft/check_runtime.py`：它必须确认生产运行时依赖精确就位、运行时闭包与渲染器匹配、兼容记录和卡片索引绑定当前注册表、上游基线可读、工作台调参和可选 Fish Audio 入口存在。生产运行时属于 108 张资格身份，不得用上游共享 runtime 自动覆盖或自动升级。其它缺文件、哈希变化或版本不一致时停止，列出准确的安装或路径修正动作，等待一次用户确认；不得现场重写发布清单掩盖缺失。
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
5. 用同一个已选 Python 运行 `scripts/dependency_preflight.py --job-context <workspace>/job-context.json`，报告写入 `<job>/manifests/dependency-preflight.json`。TalkCraft 运行时健康检查是必需项，须在这里重新执行并通过，不能仅凭步骤 2 的人工运行记录放行。区分发现/安装、`configured`、`connected`、`callable`、`bound`；必需项未通过时停止。预检只做本地检查，不执行媒体生成。
6. 一次展示本 Job 的 provider、精确模型、endpoint 标识、参考图能力、原生 9:16、无声输出、连接证据、额度、并发，以及实际 Python、项目路径和合成器版本，询问是否修改。用户确认后调用 `scripts/confirm_job_setup.py --job-context <workspace>/job-context.json --user-confirmation "<本次确认原文>"`，记录 `manifests/setup-approval.json`；成功才进入 `inspect`。不得用测试文本或过去的“确认”代替本次批准。
7. 用户选择 `grok-imagine-video` 时，模型 ID 必须精确一致；不自动切换模型。后续 provider 请求前仍复核真实连接与额度，预检成功不等于付费生成授权。

`job-context.json` 还记录 `skill_release` 及真实 `runtime` 身份。初始化在创建目录前验证发布包及模块来源；`state.require_runnable` 对 Skill 管理的 Job 强制检查当前包、运行时、Job 绑定预检和配置批准。恢复同 Job 时复用未变化的批准；报告超过 24 小时需刷新，配置不变不重复询问。项目/解释器/源码/Skill 身份变化必须先做明确迁移，不能静默重写上下文或重做已批准素材。裸状态引擎测试不走此门，不能作为 Skill 的启动捷径。

输入缺视频或文案时，只询问缺失项，不猜路径。内联文案通过初始化器的 `--script-stdin` 或 `--script-text` 代替 `--script`：初始化器直接在新 workspace 内保存 UTF-8 原文并建立索引，不要求先存在 Job，不把输入写入 Skill 目录。长文案优先通过 stdin 传入，使用宿主参数数组/输入流，不将原文拼接进 shell。

初始化发布 workspace 时已写入 `initialization.json`。若后续初始化中断，使用同一 Python 执行 `scripts/initialize_video_job.py --resume-workspace <workspace>`，不再次使用新建参数。它只复用导入字节和同一 workflow，原件移走也不重新复制；运行时/发布身份变化、损坏文件或非空事务残留会停止并保留现场。已完成 Job 不自动补造丢失 workflow；没有恢复记录的历史 Job 不适用这个入口。具体边界见工作区合同。`workflow.json` 是唯一状态事实，不得手工修改。

## 2. 十二阶段与确认策略

产品顺序固定为：

`inspect` → `content_analysis` → `cover_direction` → `cover` → `speech_cleanup` → `edit_structure` → `visual_direction` → `visual_canary` → `visual_assets` → `subtitles` → `preview` → `delivery`

一次只运行一个正式 runner。主控先统一文案、时码和镜头风格分配，再允许最多 3 个子任务并行准备不同镜头的方案、素材与只读检查；子任务不得修改 workflow、正式清单或批准记录。图片和视频生成共用当前 Job 的 2 个名额，具体领取、响应保存和恢复见[有界生成编排](references/production-bindings.md#有界生成编排)。每次正式动作前重新 `load_job`，按产品顺序找到最早未完成阶段；它必须是唯一候选，且依赖全部 `approved`。候选缺失、不唯一或状态不一致时记录当前状态并明确停止。每个 runner 仍必须先发布到 `ready_for_review`，再由确认策略完成内部校验和推进。

默认采用“结果确认”模式：用户确认 Job 配置、付费/外部账号动作、不可逆素材变更，以及最终预览/成片结果；中间阶段（转写、清理提案、A-roll、视觉计划、canary、资产、字幕）只要确定性校验、绑定校验和本地 QA 全部通过，就由宿主自动批准并继续，不逐阶段打断用户。若用户明确要求查看某一阶段，或 QA 出现歧义、视觉明显偏离、素材/模型/费用选择发生变化，才暂停等待确认。自动推进不等于跳过 runner、哈希、回执、事务恢复或最终交付审批。

同一候选画面只报审一次：记录已展示的产物身份及用户反馈。后续只变更执行记录、时码校验、编码或其他不改变观感的技术证据时，内部验收并继续，不再次发送同一视频或索取确认；预览文件哈希变化也不能单独证明画面已变。只有画面、声音、字幕或内容出现用户需要判断的实质变化，或到达尚未确认的最终成片门，才展示当前结果并说明具体变化；用户主动要求重看除外。开发样片的认可不得冒充正式 Job 的最终确认。

最终成片只确认一次：宿主完成 `preview` 的实际画面、原声和字幕 QA 后内部批准该阶段，运行正式 `delivery` 导出同字节的待确认成片，再向用户展示 `final.mp4` 并保存该次报审 revision 与文件 SHA-256。用户对这份实际成片确认后才调用最终确认入口；预览内部批准只是允许整理交付包，不代表用户认可或正式完成。不得把同一份视频再拆成“预览确认”和“交付确认”两次，也不得将旧版本的认可绑定到修订后的成片。

封面有两个不可合并的人工门：`cover_direction` 批准内容与设计方向，`cover` 批准实际图片。文案理解、重点和关键词只在 `content_analysis` 决策一次；下游不得重新提炼或询问同一问题。
用户反馈“关键词、A-roll 贴片或 B-roll 太少”时，先从正式预览按内容章节量出高亮分布、贴片/B-roll 位置与累计时长，再逐句找未被可视化的语义机会。关键词源头漏项修订 `content_analysis`；镜头稀疏修订 `visual_direction`，并遵循状态级联，不能只在最终预览上叠几个临时元素或以固定数量代替语义判断。执行与验收分别遵守[字幕样式合同](references/subtitle-style-contract.md)和[9:16 视觉质量合同](references/visual-quality-contract.md)。
用户同时指出样式同质化时，扩展的是本期可实际调用的原生组件候选，不是把已接通的两张图重复插入。按[画面多样性](references/visual-quality-contract.md#画面多样性)比较全片及最近两个增强窗口的主体、构图和动作；充分表达台词、实际质量相当的候选优先选不同家族。已明确否决的本期效果不自动复用，但不因此禁用整个上游 Skill。现成组件只缺竖屏、透明输出或文本槽交接时先做薄适配，不能把“还没有 adapter”误判为上游没有能力。
用 `scripts/audit_visual_coverage.py --visual-plan <当前visual-plan.json> --subtitle-plan <当前subtitle-plan.json>` 输出每 20 秒的实际口播、高亮、贴片和 B-roll 分布及贴片时窗里的真实台词；逐项核对后才决定修订范围。该报告只定位缺口，不用数字代替语义审片。贴片时机、美观度或字幕碰撞被用户指出时，旧预览直接判未通过；先用带原声的代表样段验证词锚、真人避让和入／中／出画面，再重渲全片，不重复报审未发生观感变化的旧视频。
本项目默认采用较密、均匀分布的 B-roll 节奏，具体安排遵守[视觉质量合同的密度规划](references/visual-quality-contract.md#b-roll-密度规划)。盘点时同时检查首个 B-roll 时间、累计占比和最长无 B-roll 区间；A-roll 贴片不能截断这项空白统计。用户要求重新安排时先保存本 Job 的逐镜时间、对应原声、画面动作及上游调用方案；未完成来源绑定的安排明确标为待制作，不冒充已编译或已渲染的 VisualPlan。
新一期封面须从本 Job 已批准的内容重点生成新的画面创意：重新设计人物动作、主题隐喻、道具和场景，只继承已通过样例的标题层级、对比度与视觉完成度。样例是风格参考，不是可替换标题和人物的底图模板；生成候选前按[封面标题视觉样式合同](references/cover-title-style.md)绑定本期人物来源、逐字标题与主题动作，并用实际新图验证，不能把复制旧图或本地套版当成自动生成通过。
用户认可的是完整带字封面时，锁定那张 PNG 的 SHA-256，正式 `cover` 直接原样复用，不生成或要求无字底图，也不让模型重画、本地叠字；封面不制作或展示缩略图，只展示正式尺寸成图。已认可成图的文案与旧方向记录不一致时，先把方向修订为成图中的逐字文案，再发布同一张图，不生成“相似版”。只有用户认可的仅是构图方向、尚未认可实际成图时，才可选择无字底图加本地排字的候选流程。

到达 `cover_direction` 和 `cover` 时完整阅读封面输出与质量合同。9:16 真人知识封面优先读取项目内 `skill-development/vendor/Punk-Skill/skills/punk-cover/SKILL.md`，按其单一 `interleaved-title-editorial-poster` 风格编排本期文案、人物参考、主题动作和完整候选图；保存实际提示词、候选图及来源，不把手写提示词冒充子 Skill 调用。已批准的比例和文案优先于子 Skill 默认值，人物可与标题发生不影响识别的发丝穿插，五官和叙事手部必须清楚。原 `gbro-cover-design` 仅用于无字底图加本地排字的候选链路；Punk 完整带字成图经正式 runner 原样发布、像素核对和 `cover` 人工门通过后才称为正式封面，不为发布补造无字底图。
Punk 实际方向候选须存入本 Job 独立的 `punk-assets` 目录，并调用 `prepare_cover_direction(..., direction_preview=...)` 原样发布；不得用旧主题固定示意图代替本期语义。

`speech_cleanup` 的字级转写能力归属 `video-use`：先读其 `SKILL.md`，经本次音频上传与额度许可、凭据就绪后，从本 Job 预检绑定的 `video-use-runtime.resolved_path` 实际调用 `helpers/transcribe.py <源视频> --edit-dir <本Job工作区/edit>`。以预检发现的 `video-use-skill.resolved_path` 为进程工作目录，使上游 helper 读取该已安装 Skill 的私有 `.env`；若凭据来自安全注入的进程环境，也可直接使用，不复制密钥到项目。调用前确认输出路径未被其他源素材的缓存占用；记录入口绝对路径、退出码、源视频 SHA-256 和原始 JSON SHA-256。再将原始 JSON 路径与这四项调用证据传给 `transcribe.transcribe_job(job, video_use_result=..., invocation=...)`，由项目适配器校验时码、保留原始响应、对照文案并制作清理提案。没有许可、凭据、真实调用或可验证输出时停在此阶段；本地 Whisper 不能替代 `video-use` 的正式转写。

## 3. 批准、修改和 blocked

每个 runner 只能推进到 `ready_for_review`；结果确认模式下，宿主在同一串行任务中完成内部审查后自动批准，不向用户重复发送阶段确认。发生暂停时，报审只展示当前阶段，并使用以下稳定格式：

```text
阶段：<stage>
状态：<ready_for_review | blocked>
结果：<可审核产物与忠实简洁摘要>
注意：<无已知问题 | 具体问题>
下一步：<等待确认 | 修改意见 | blocked 选择>
```

暂停阶段需要用户确认时，才执行：重新加载 → 验证唯一 `ready_for_review` → 只 `approve` 该阶段 → 再加载并验证提交 → 有下游时只运行一个下一阶段。结果确认模式的自动批准必须记录本地 QA、产物哈希和自动批准原因，不得把自动批准写成用户确认。最终 `delivery` 仍必须使用用户对完整成片的确认回执。

最终 `delivery` 使用 `edit.hd.tools.delivery_approval.approve_delivery` 或正式 CLI 的 `approve --stage delivery` 分支：传入报审时保存的 revision、最终 MP4 SHA-256 和本次用户确认原文，具体参数及中断恢复见十二阶段合同的“最终确认入口”。不能用裸 `state.approve` 代替这条最终确认链路，也不能自行编写 `approval-receipt.json`。

修改意见只作用于当前待审或已批准阶段，将用户原意的忠实简洁摘要传入 `revise`。单个正式视觉段使用 `artifact_scope=("seg-xxx",)`；不手工改 `workflow.json`。

修订已有视觉计划时读取视觉修订合同。用户要求保留或认可的开头、贴片及 B-roll，须当场写入本 Job 的 `manifests/confirmed-content.json`，并接入正式计划；不得只保存在局部样片。正式视觉发布和预览入口检查这份保留记录，缺项即停止，不输出缩水成片。支持 `segment-inputs` 的运行时会在新计划及 canary 获批后，按完整输入指纹与原批准证据复用未变正式片段，不因其他镜头变化重复生成。局部修改 B-roll 时，正式字幕入口按[字幕轨复用判据](references/visual-revision-reuse.md#未变字幕轨复用)复用完全未变的透明轨，不重渲全片相同字幕；新计划、回执和下游校验仍重新建立，不继承旧批准。此能力不改变下游状态 DAG，也不自动迁移历史成片。

用户资料变化必须先读工作区与素材回执合同，使用 `scripts/manage_user_materials.py` 的 `plan` → 人工确认 `plan_hash` → `apply --confirmed-plan-hash` 唯一入口。新 Job 的每个已发布阶段都必须包含完整 `material-usage.json`；无引用也发布空声明。已使用资料的替换/撤回依据当前回执计算 `earliest_stage` 和 `artifact_scope`，经 `prepared` → `material_committed` → `workflow_revised` 三阶段事务后恰好调用一次 `state.revise`。原字节和旧 material ID 保留，未变片段按输入指纹复用，受影响及下游阶段仍须逐门重审。回执缺失或身份不一致时 fail closed；旧 Job 不补造回执。资料变更期间暂停当前 Job runner，同一 `operation_id` 仅用于原事务恢复。

视觉来源执行阶段进入 `blocked` 后不自动重试，只展示两个互斥选项并明确停止：

- `retry_same_strategy`：保持已批准语义、来源类型和配方，在连接或运行条件恢复后重试。
- `replan_visual_direction`：返回 `visual_direction`，由用户重新批准语义选择与来源绑定。

仅对已由精确提交回执或精确单任务查询证明为 `failed` 的请求提供受控重试：先用
`prepare_retry(job, request_id)` 冻结父项、失败回执摘要、原请求指纹、当前配置摘要、输入身份和
`count=1`，再取得针对这份计划的一次真实用户授权，并调用
`retry(job, plan, user_confirmation, expected_plan_sha256)`。它在锁内创建唯一的 `ready` 子项，保留
`retry_of` 和原始分镜 `plan_request_id`；重复同一计划只返回同一子项，不再次发起工具调用。不得自动挑选“最新失败项”、重置或覆盖旧项，也不得把队列 ID 当作供应商 task ID。
`submitting`、`pending`、`unknown`、`not_found`、`moderated` 以及“已完成但视觉不合格”均不走这条重试；后两类分别进入重新规划或既有视觉修订。聚合失败、同一请求多个 task ID 的总状态不能证明全部失败，必须逐项核实。`not_found` 保留原始回执、本地保持 `unknown` 并占用名额，停止自动轮询，改为回查已保存的实际任务或项目记录。`resume` 只解除暂停并允许后续 `ready` 项领取，不能复活失败或未知项；创建重试也不会自动恢复暂停。重试不改变原参数、模型、项目或素材，任何变更都必须重新规划。

其他阶段保持当前阶段的修订边界：报告准确状态后停止，不跳到尚未解锁的 `visual_direction`。`cover` 返回当前封面 revision，仍可由用户明确选择 code-generated alternative `aroll-code-cover`；它只适用于 `cover`，必须形成 revision 并重新报审，不能改写 B-roll 的来源选择。

## 4. B-roll 语义合同

B-roll 默认追求高有效信息密度，区别于全片的插入频率和时长占比。调用上游制作前，把本句的关键对象、核心动作、关系变化及必要上下文拆成可见语义拍，随真实词锚交给子 Skill；不能只给关键词和画风。按[单镜信息密度](references/visual-quality-contract.md#单镜信息密度)规划和检查，既不漏掉关键动作，也不靠堆文字、装饰或重复字幕凑信息。已认可的交接表达可作为动作设计参考，不把其道具和构图固定成所有 B-roll 的模板。

遇到概念拆解、分类和层级关系时，也匹配[思维导图与分支关系动效](references/generated-broll-skills.md#思维导图与分支关系动效)：优先核对 HyperFrames 现成决策树/中心关系入口，手绘方向调用 Doudou 真实组件。静态导图和交互网页不是动态 B-roll；候选登记不等于已出片或正式接通。

选择 Doudou 后，先按[原生手绘制作交接](references/generated-broll-skills.md#doudou-项目内调用)执行上游场景制作：把主体对象、构图、绘制动作与当前词锚交给制作阶段，实际使用其画布、笔刷或绘图算法，而不是先拼普通 CSS 框图再加箭头。本项目手绘默认使用原生 `RealHandFollower` 与已冻结的透明握笔图，不能把孤立铅笔当作真实手部。随后使用 `scripts/doudou_adapter.py` 冻结本期场景和手图并交给统一组件执行器；不另造白板模板或动画引擎。父级仍统一合成圆形人物小窗与唯一字幕轨。批准过的视觉方向不重复报审；改变语义、来源或配方时才进入相应修订流程。

新计划充分使用现成 B-roll 能力：父 Skill 只做语义导演、镜头编排、批准门和最终合成验收；制作前完整读取并实际调用所选上游 Skill。候选先按语义匹配分，再按美观质量分排序，两分相同才比较来源资格，最后比较重复间隔。优先组合现成能力；只有记录真实能力缺口后才允许最小新增实现。使用依赖时如实写 `producer_type=dependency` 与 `dependency_id`，另记复用能力与新增实现；`custom_fallback / structural` 是适配资格，不等于自研，也不冒充第三方整屏模板。Lemo-Opuscar、OneTake 使用项目内固定提交。HyperFrames 透明贴片/轻组件、TalkCraft 精确数据、Doudou 白板/思维导图、Paper 分层拼贴、Lovart Kling O1 场景动作保留各自边界；prompt 库不是制作依赖。入口与验收见[上游场景 Skill 合同](references/upstream-scene-skills.md)与[生成型 B-roll 编排](references/generated-broll-skills.md)。

调用前区分现成模板、创作工具包与生成服务。Lemo 是原生风格创作工具包，不是填词导出模板：父级交付语义、真实词锚、时长、圆窗/字幕避让和相邻镜头外观，不先锁定“三卡片＋箭头＋圆点”。按其 DIRECTOR → 本期 treatment → STYLE/DEMO 技术学习 → 原生制作流程，让上游设计主要视觉动作；本期场景代码如实记为结构改编。美术质量看真实原尺寸画面与全速动作，多样性看实际构图和运动，不能用不同 Skill 名、函数引用或渲染成功代替。具体交接与审阅见[上游场景 Skill 合同](references/upstream-scene-skills.md)。

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

选型前先读完整语义段落，解清人物指代、动作、否定、对比和前后因果，再限定当前时窗实际说到哪一步。交给子 Skill 的画面任务必须同时包含上下文、当前口播和不能提前出现的后续结果；不只抽“小调研”等关键词配图。先验收画面是否准确表达当前这一步，再看画风和动画；黑白变彩色等显现效果不等于叙事动作已经成立。用户指出语义不符后撤回该片段的语义通过状态，保留技术证据，修订后重新看实际成片；美观认可不代替语义认可。

抽象结论不强求 B-roll。候选在正常播放速度下须让人从可见对象、动作和必要的简短标签看出本句的具体变化；若必须听创作者解释“这个道具象征什么”，就先判语义不成立，选择 `mode=none` 保留真人 A-roll，等后文讲到可直观表现的具体动作再切 B-roll。不能为了保留已生成素材，把后文的动作或成果提前塞进当前时窗；静帧美观、视频确实在动、媒体参数通过都不能覆盖这项判断。冻结计划前沿全片口播逐段核对已批准的具体论点、可视化动作及对应时窗，不能只为中间几个现成素材留 B-roll。列出开头、中段、结尾实际 B-roll 时窗及最长连续纯 A-roll 时长；若某个完整语义章节一直没有 B-roll，先找能直观呈现的原声动作句，确实没有再记具体理由。预览验收以真实画面的全片分布为准，片段存在、计数通过不等于观众能感知到 B-roll；不设脱离语义的片段配额。

本项目要求动态 B-roll：主体须有与本句相关、可辨认的动作或状态变化。仅静图推拉、擦除、上色、淡入淡出或粒子装饰不满足要求，即使文件是 MP4。选型先核对现成 Skill 的具体入口能否完成所需动作；只能生成插画或显现效果的入口可用于准备素材，但不得单独作为动态成品。优先编排能完成动作的现成能力，按[生成型 B-roll 编排](references/generated-broll-skills.md)验收动作前、中、后；图生视频模型及费用变化仍须确认，不能因尚未授权而静默交付静图动效。

检索前先读当前 Job 已索引的用户资料，避免重复下载或生成相同内容；这是检索去重，不改变五类来源的语义平等地位。

- `local_material` 从当前 Job 的 `00-user-provided/material-index.json` 绑定少量用户图片、视频或文档。
- `official_material` 绑定第一方图片、视频或页面记录，保留来源、人物职务和内容真实性检查。选中在线视频时先读官方视频下载合同，实际调用项目内 `video-download` Skill；只取得页面、字幕或下载命令不算已获取视频，必须核对本地视频的画面、声音、时码、哈希及适用清晰度。
- `code_generated` 调用现有依赖 Skill，按 ShotRecipe 执行，并保留 Skill 调用证据、`dependency_id`、`entrypoint` 和 `producer_version`。
- `external_stock` 根据语义检索经批准 provider，保留许可记录、作者、来源 URL 和下载身份。
- `ai_generated` 是主动语义选择；它绑定 provider、精确模型、参考图和 generation identity。复用 Lovart 已完成视频时，按[生成型 B-roll 编排](references/generated-broll-skills.md)先调用 `prepare_existing_binding` 核验并准备绑定，再编译、正常批准和执行；不手改配方、不重新生成、不改标为本地资料。竖屏无声 AI 动态 B-roll 源视频可为原生 720×1280/24fps，配方按实测源尺寸编译，合成后仍须达到 1080×1920/24fps；不把放大后的结果称为原生 1080p。其他尺寸的单条补边例外须绑定原视频、派生视频和已确认预览的摘要，不扩展到其他素材。

当前已选的 AI 动态 B-roll 视频生成服务是 Lovart；具体模型仍按本 Job 的能力、费用和批准配置确认。Flat/GBRO 的原生 Gemini 视频入口不作为备用路线，服务不可用时停止，不自动切换。

需要生成型画面时，按[生成型 B-roll 编排](references/generated-broll-skills.md)在 Whiteboard、Paper Collage、Flat Animation、GBRO Collage 等现成 Skill 中按语义选型，再检查实际可执行入口与适配缺口；不因单次样片失败排除整个 Skill，也不因已接通某条路线就统一选它。优先调用上游已有配置与能力，缺口才做最小适配，并实际出片验收。Paper 分层入口与 Whiteboard 原生 SVG 分组入口已分别通过该页的 `paper_collage_adapter`、`whiteboard_adapter` 接入公共组件执行器。Flat/GBRO 仅负责其视觉方案和静帧阶段，视频统一由 Lovart 生成并由现有 Lovart 适配器验收，不能把 Lovart 视频记作这两套上游的原生视频调用，也不再要求 Gemini 密钥。原生 720p AI 视频不因分辨率被排除，但 Lovart 本次出片及当前片段语义/画质仍须真实验收。已接入入口也不是通用已验证模板，每段仍须检查语义与美观。图片生成与动画来源分别绑定，子 Skill 只产出无声整屏镜头，圆窗、原声和全片唯一字幕轨仍由父级统一处理；不跨已批准来源类型替换，不绕过执行与确认门。

`code_generated` 的排序是 `semantic_match_score` → `quality_score` → `template_origin` → `reuse_gap`。语义和质量同分时，资格才按 `verified_third_party` → `verified_local_canonical` → `custom_fallback` 比较。引用验证模板前仍须运行 `verify_broll_template.py` 核对真实登记；`structural` 或自由新场景不能继承第三方身份。填充本期内容后做三态 QA，冻结真实 `producer_type`、`dependency_id`、入口、当前请求、制作与调用证据；历史样片不能代替当前验收。

TalkCraft 108 张卡使用独立生产注册表，不冒充旧 `verified-template-registry`。当段落已选 `code_generated` 且适合 TalkCraft 时，必须先调用 `edit.hd.tools.talkcraft_matcher.match_cards`，把当前口播原文、语义目标、关键词、信息单元、组件角色、已有媒体和人物需求作为输入；再用 `build_binding` 冻结首选卡片。匹配器只读锁定的 `runtime/card-semantic-index.json`，运行时仍以 `runtime/card-registry.json` 的 qualified 身份为唯一准入依据；缺必需图像/视频/人物、角色不符或索引身份变化时显式停止，不在 adapter 或执行阶段重新选卡。这个自动选卡结果仍需要当前 Job 的 brief 参数化、三态 QA 和 canary 本地 QA 与内部批准。

需要工作台微调时，先用 `edit.hd.tools.talkcraft_workbench.build_v4_edit_contract` 从当前 VisualPlan v4 和 draft brief bundles 生成稳定目标及可编辑字段，再用 `apply_v4_overrides` 生成新的 draft bundles。工作台只允许改合同公开的语境参数，当前只开放显示文案与深浅主题；未知目标、未知字段、非法值或计划身份变化都停止。回写结果保持 `editable_draft_only`，不得覆盖已批准 bundle，也不得跳过 canary 与本地 QA/内部批准。上游 Workbench 的 `overrides.json`、共享 React 19 / Remotion 4.0.519 只服务上游编辑与冒烟；正式渲染继续使用项目已资格的 React 18 / Remotion 4.0.520 运行时。

Fish Audio 仅是无成品配音时的可选输入方式，不改变默认“使用用户成品口播”的原则。只有用户明确选择合成配音、当前 Job 已确认精确模型/声音/费用且存在 `FISH_AUDIO_API_KEY` 时，才调用 `edit/hd/integrations/talkcraft/upstream/scripts/tts_fishaudio.py`；不得把密钥写入 Job 或 Skill，不得自动发起试音或付费请求。其输出音频和时间戳仍按用户提供音频同样进入 Job、校验并报审。

当前注册表有十五套可验证整屏模板：四套 `verified_third_party`、五套本地 canonical（`process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword`）、`hd-talking-head/relation-motion`，以及五套已登记 SemanticState（`replacement`、`threshold`、`delay`、`hierarchy`、`feedback`）。五套通用本地 canonical 共用 `scripts/local_canonical_renderer.cjs` 和 `scripts/local_canonical_adapter.py`；`evidence-source` 的主媒体可为图片或视频。RelationMotion 与 SemanticState 直接消费各自已冻结的语义动效计划。五套 SemanticState 的登记绑定双输入真实执行、逐态像素、动作顺序和用户批准的 25 秒头像合成样片；这些历史资格仍不取代当前 Job 的语义选择、实际填充三态 QA 与 canary 本地 QA 与内部批准门。

`visual_direction` 冻结 `source_bindings`，并编译 `ShotRecipe v2`。`visual_canary` 只执行已批准配方，不做语义重选。`visual_assets` 严格复用 canary 字节和剩余已冻结配方，不重新做来源判断。

纯 A-roll 的语义贴片优先调用现有 HyperFrames `hyperframes-registry` / `motion-graphics` 或 TalkCraft 透明线稿组件：按当前句子的图形关系查询现成组件；仅需关键词强调时才查询 `caption-*`、callout、annotation 或 lower-third。核对中文字体、透明背景、1080×1920 与当前已批准帧率、文案容量、脸部和字幕避让；用选中组件的原生变量或文本槽填入本 Job 文案，实际调用上游能力。正式流程使用 `aroll_with_overlay / mode=none`，由组件执行器调用透明制品，canary 和 `visual_assets` 共用 `render_arroll_segment(artifacts=...)` 合成到原 A-roll；保留普通字幕，不将贴片镜误判为 B-roll。真实三节点流程优先接入 HyperFrames Registry `hw-pipeline` 的 `hyperframes_hw_pipeline_adapter`；已确认的“固定能力点＋移动标准线”接入 `talkcraft_overlay`，沿用 TalkCraft 图形原语和已批准布局。两者竖屏适配都标为 `custom_fallback / structural`，不冒充未经适配的原生模板。其他语义仍先选现成组件，不能硬套这两张图。调用、依赖补齐与验收见 [A-roll 透明贴片合同](references/aroll-overlay-contract.md)。不得将检索、绑定成功或开发样片当作正式交付；TalkCraft 不透明整屏卡不能冒充透明贴片。

A-roll 贴片先判断能否增加理解：有对应资料 B-roll 的人物/机构介绍不重复贴标签；抽象观点若只能把口播原句放大重述，就保留真人画面。比较、结构、因果或状态变化优先找能直接表达关系的现成图形组件，不把 `caption-*`、乱码揭示或大字标题当作语义贴片。贴片可见区间须绑定口播语义句，进入下一主题前退场；带贴片的 A-roll 仍须显示普通字幕，不能因使用视觉组件就误判为 B-roll；A-roll 与 B-roll 都由同一条字幕轨覆盖。正式接入须同时贯通视觉计划、canary、A-roll 字幕识别和最终合成，开发期本地字幕排版试验不得代替正式 Scribe 词级转写。候选先在原尺寸真人画面上检查稳定帧：图形关系不成立、临时字符尚可见、文案不可读、遮挡人物或与字幕重复时立即淘汰，不继续渲视频或冻结正式计划。实际导出后再量透明区域与贴片主体的 alpha，并核对真人合成后的进入、中段和退出画面确实发生预期变化；流参数、单张静帧或能播放的视频都不能单独证明动态贴片通过。现成组件只能提供部分图形时，明确记录复用部分与新增实现部分，按新实现验收；不得声称整张贴片由上游 Skill 原生完成。

同一条 A-roll 样片的画面、主音轨、Scribe 词级时码、字幕和贴片必须绑定同一个源文件哈希及明确的源时间区间；不得根据文件名、旧笔记或推测的秒数拼接不同区间。合成前核对音频指纹/时码与源片一致，合成后同时检查最终画面的进入/中段/退出帧、实际字幕和最终音轨；透明 WebM/MOV 还要在真人合成后的画面中确认 alpha 生效，不能只凭透明元数据或播放器可播放判定通过。任一绑定或复核失败，样片标记为失败并停在当前阶段，不得进入人工确认或正式 Job。

全片 A-roll 与 B-roll 统一使用已确认的 TalkCraft 卡片式口播字幕；先读上游 `video-talkcraft` Skill，再由正式 `subtitles_v2` 实际调用项目内 `talkcraft/subtitles/render.mjs` 的版本化组件适配，绑定本 Job 的 Scribe 时码、批准文案及唯一透明字幕轨。字幕适配器从兼容运行时所在项目根调用上游，复用项目已准备的浏览器缓存，不因宿主位于 Job 或临时目录而重复下载。B-roll 字幕避让同步圆形小窗，由父级在视觉轨完成后统一叠加，子 Skill 不自行烧录。具体样式、调用证据和验收边界见 [全片字幕样式与上游调用](references/subtitle-style-contract.md)。启动时的 TalkCraft 依赖检查必须包含字幕适配入口；缺组件、词时码或身份不符时停止，不得回退旧 PIL 字幕，也不得把开发样片当作正式 Job 批准。

扩展第三方模板时，先按资格合同筛查完整文案可编辑范围、长度与中文字体、分词及语义动效；原生竖屏或换标题成功不等于可以直接用于本期内容。保留版本化的排除记录，不重复测试未变化的同一缺陷。

选中 `html-video/frame-data-rollup` 时，加载 [原生 DataRollup 执行接口](references/data-rollup-execution.md)；选中 `hyperframes/notification-cascade` 时，加载 [原生 Notification Cascade 执行接口](references/hyperframes-notification-execution.md)；选中 `hyperframes/chatgpt-exchange` 时，加载 [原生 ChatGPT Exchange 执行接口](references/hyperframes-chatgpt-exchange-execution.md)。第三套只用于“提问→回答→四项对照表→回读结论”的已验证语义，不代替普通对比海报。三者都通过包内 adapter 工厂接入正式执行器，不手工重画或停留在文字登记。新调用计划使用 `status=planned / exit_code=null`；实际成功以执行器输出证据为准，不能为了通过校验提前填写成功。其他模板没有这一执行验证时不得套用其结论。

正式片段、成片和 B-roll 合成画布保持 1080×1920；仅无透明通道的竖屏 AI 动态 B-roll 源视频允许原生 720×1280/24fps，合成时放大，须按[生成型 B-roll 编排](references/generated-broll-skills.md)检查实播画质。其他素材仍按原有规格或单条已批准补边许可绑定验收，不能伪称原生达标。当前 full-v2 计划与成片固定为 24fps；输入素材可有其他原始帧率，但正式阶段先按运行时合同规格化，不接受其他输出帧率的计划，也不做横屏后裁切。B-roll 必须让资料/主题视觉占据整个竖屏版式，口播人物只作为同时间轴的小窗或头肩头像；禁止在全屏 A-roll 上贴一块资料小窗来冒充 B-roll。B-roll 保留与原声逐词对应的唯一普通字幕，放在圆形小窗上方并与画面内标题、关键标签错开；小头像使用 head-shoulders 裁切。实际媒体由已冻结记录和 SHA-256 解析；不用空海报代替。切入切出用 8–12 帧 alpha 回到同时间轴 A-roll。本地重渲染一次只运行一个；云端生成在材料准备阶段使用统一名额，不提前执行尚未解锁的正式 canary、字幕或交付。

开发期可用估计时窗制作纯视觉草稿；但带原声、供用户判断声画对应的 B-roll 样片必须先用同源 `video-use`/Scribe 词级时码锁定目标句，在 24fps 整帧边界保留 30–200ms 起止余量。校正时窗后重渲子 Skill 镜头及父级原声、小窗合成，核对首尾未夹入相邻句且最终音轨来自同一原片。缺少真实转写时只标为视觉草稿，旧草稿的视觉认可不等于新时窗的声画验收。

到达 `visual_direction` 时必须完整阅读 9:16 视觉质量合同、B-roll 语义能力路由和开源能力适配矩阵。到达 `visual_assets` 时必须完整阅读正式生产绑定与视觉资产前置检查。本地绑定、字体、哈希、路由或 `safe_zone` 不合格时，先停止当前执行，不发出供应商请求。

## 5. 完成边界

当前 full-v2 不生成或交付缩略图、联系表或 `contact-sheet.png`，字幕、预览与交付库存均不依赖它们。内部 QA 仍从实际视频抽取原尺寸关键帧，不缩小或拼图；向用户展示可播放视频和正式尺寸封面。历史模板资格证据保留原样，不用本次规则重签旧记录。

Preview 使用剪辑后 A-roll 的口播音频主时钟，默认不加背景音乐。机器 QA PASS 只是 `ready_for_review`；`delivery` 仍需最终确认、正式回执及完成审计。仅有 `delivery approved` 状态不足以宣称正式完成。

交付后用 `scripts/audit_job_completion.py --workspace <workspace> --json` 做只读审计。它只能返回 `formal_complete`、`legacy_external_approval`、`incomplete` 或 `inconsistent` 四态，并展示已验证/未证明边界；不修改 workflow、回执或文件。新 Job 只有当前 revision 十二阶段全批准、交付媒体与 manifest 一致，且最终人工 approval receipt 精确绑定实际文件 SHA-256 时，才能返回 `formal_complete`。

正文默认从实拍 A-roll 引入话题，再切入语义对应的 B-roll；如启用封面，顺序为“封面 → A-roll 引入 → B-roll”，不能封面后立即被官方片头或海报接管。具体时长依据已批准口播动态决定，用户明确批准其他开场结构时记录例外。设计或修订开场时读取对应合同，只审核新增合成方式并复用现有资产；正式首帧、时间偏移与音乐实际可听性必须验证。

未明确要求时不上传 ChatCut 或其他外部编辑器，不自动发布或发消息。保持 1 个主控，最多 3 路独立准备；生成名额不能由子 Skill 各自领取一套。本地重渲染、正式组装、回执和批准仍串行；并发不增加获准的生成次数，不重做已验收成片。
