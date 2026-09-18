# 十二阶段执行合同

## 目录

1. 全局顺序与阶段表
2. 内容唯一性与不重复
3. 状态操作
4. 十二阶段逐项合同
5. 视觉生产必须项
6. 完成边界

本文件只描述 `full-v2` 正式流程。视觉阶段只接受 VisualPlan schema v3 和 ShotRecipe v2，不兼容旧 visual Job；旧 visual Job 重新执行 `visual_direction`。每个 runner 只能把当前阶段推进到 `ready_for_review`；机器 PASS 不等于人工批准。

十二阶段不是依赖安装器。进入 `inspect` 前，当前 Job 必须已有通过的 `manifests/dependency-preflight.json`，并完成本 Job 的动态 provider/插件配置确认。缺少必需运行时、runner 或 Skill 时停在阶段外的依赖门；不得先运行部分阶段再补依赖。

该门由 `state.require_runnable → startup.require_startup` 实际执行：读取 workspace 的 `job-context.json` 以及 job_dir 内的 `manifests/provider-config.json`、`manifests/dependency-preflight.json`、`manifests/setup-approval.json`。配置批准通过 `confirm_job_setup.py` 保存，不新增第十三个媒体阶段。环境证据失效不自动重做已批准内容、封面或剪辑。首次 inspect 支持预建空目录；未知文件及不完整旧产物仍停止并保留。

产品执行顺序固定为：

`inspect → content_analysis → cover_direction → cover → speech_cleanup → edit_structure → visual_direction → visual_canary → visual_assets → subtitles → preview → delivery`

底层状态是精确 DAG，但控制器仍按上述产品顺序选择最早未完成阶段，一次只报审一个。这保证封面方向和文案重点在开头决定，不在后面重复工作。

## 阶段表

| 阶段 | 公共入口 | 固定产物 | 人工审核重点 |
| --- | --- | --- | --- |
| `inspect` | `edit.hd.tools.inspect_inputs.inspect_job(job)` | `01-inspect/report.json` | 视频/音频流、时长、编码宽高、SAR 与 DAR、文案身份 |
| `content_analysis` | `edit.hd.tools.content_analysis.prepare_content_analysis(job, analysis)` | `02-content-analysis/content-analysis.json`, `review.md` | 唯一内容理解、核心观点、重点、精确关键词、事实/人物/数字、B-roll 语义角色 |
| `cover_direction` | `edit.hd.tools.cover_direction.prepare_cover_direction(job, direction)` | `03-cover-direction/person-reference.png`, `cover-direction.json`, `review.html` | 封面大体内容、唯一输出比例、标题、人物动作、环境、构图和字体方向 |
| `cover` | 显式加载 `gbro-cover-design`，再调用 `edit.hd.tools.cover.prepare_cover(job, ...)` | `04-cover/cover-<approved-ratio>.png`, `cover-delivery-raster.png`, `cover-report.json` | 只交付批准比例；实际封面图、脸部不遮挡、隐喻可辨、动作/环境贴题、中文无误 |
| `speech_cleanup` | `edit.hd.tools.speech_edit_v2.prepare_transcription(job)` 后同一阶段调用 `speech_edit_v2.prepare_cleanup_proposal(job, plan)`；内部必须应用已绑定 `video-use` pacing profile | `05-speech-cleanup/` 内 7 件完整产物 | 转写覆盖、删改差异、0.40 秒长停顿切分、预估时长；中间 3 件不单独报审 |
| `edit_structure` | `edit.hd.tools.speech_edit_v2.render_edit(job)`；有剪点时必须调用预检报告绑定的 `video-use/helpers/render.py` | `06-edit-structure/edit-plan.json`, `edited-aroll.mp4`, `timeline-map.json` | EDL 真实剪辑、原口播音频主时钟、30ms 音频边缘、原生 9:16 A-roll |
| `visual_direction` | `edit.hd.tools.visual_plan.prepare_visual_direction(job, director_brief, official_registry)` | `07-visual-direction/visual-plan.json`, `visual-routing.md` | 五类同级语义选择；冻结 `source_bindings`、编译 ShotRecipe v2 |
| `visual_canary` | `edit.hd.tools.visual_canary.prepare_visual_canary(job, ...)` | `08-visual-canary/visual-canary.mp4`, `canary-manifest.json`, `segments/` | 不超 30 秒的真实长片段落；只执行已批准配方 |
| `visual_assets` | `edit.hd.tools.visual_assets_v2.prepare_visual_assets_v2(job, ...)` | `09-visual-assets/asset-manifest.json`, `visual-track.mp4`, `segments/` | 已批准 canary 字节哈希完全一致；严格执行剩余已冻结配方 |
| `subtitles` | `edit.hd.tools.subtitles_v2.prepare_subtitles_v2(job)` | `10-subtitles/subtitle-plan.json`, `subtitles.webm`, `subtitles.srt`, `contact-sheet.png` | 只有 A-roll 常规字幕；艺术字只能是精确已批准关键词 |
| `preview` | `edit.hd.tools.preview_v2.prepare_preview_v2(job)` | `11-preview/review.mp4`, `qa-report.json`, `contact-sheet.png`, `keyframes/` | 1080×1920/24fps、一视频一主音轨、默认无背景音乐、来源/字幕/安全区/转场 QA |
| `delivery` | `edit.hd.tools.qa_delivery_v2.prepare_delivery_v2(job)` | `12-delivery/final.mp4`, 封面、字幕、plans、qa、用户资料索引、`delivery-manifest.json` | 交付与已批准 preview 同哈希；确认后才完成 |

上表每个阶段进入 `ready_for_review` 时都额外发布同目录 `material-usage.json`，并将它加入该阶段正式 artifact 集。回执必须是 `complete_reference_declaration=true`；没有使用用户资料的阶段发布空 `references`，不得省略声明。完整字段、校验和变更规则见 [权威素材使用回执与变更事务](material-usage-contract.md)。

## 内容唯一性与不重复

`02-content-analysis/content-analysis.json` 是唯一语义事实源。封面标题、视觉路由、A-roll 贴片、B-roll 上屏文案和字幕艺术字只能引用已批准 item/source_text/keywords。下游不重新调用 LLM 提炼，不再向用户询问“哪些是重点”。

`cover_direction` 是设计方向批准，`cover` 是实际图片批准，二者不可合并。`visual_canary` 是正式段落，`visual_assets` 必须复用其 generation identity 和媒体 SHA-256，不得“照样再做一次”。

五类 B-roll 的权威策略块为：

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

每段可选 `none` / `single` / `hybrid`；语义角色与素材来源分离。五类同级，不设来源优先级、不设来源配额、不做跨类替换；它们之间不是降级关系。

## 状态操作

- runner 返回后重新 `load_job`，验证当前阶段为唯一 `ready_for_review`。
- 用户确认后只批准当前阶段，再重新加载状态；最终 `delivery` 使用下文的最终确认入口，不直接调用裸 `state.approve`。
- 修改意见调用 `revise`。只改单个正式视觉段时使用 `artifact_scope=("seg-xxx",)`。
- 已选来源暂时无法执行时 `block`，当前 generation 不自动重试；只给出 `retry_same_strategy` 或 `replan_visual_direction`。
- `delivery ready_for_review` 仍不是完成；`delivery approved` 加上正式回执及只读审计通过，才可宣称正式完成。

## 视觉生产必须项

`visual_direction` 使用 `scripts/broll_capability_router.py` 为每个段落编译稳定 ShotRecipe v2。五类候选都按语义匹配、内容真实性、原生竖屏、画质可读性和来源记录评估，然后冻结 mode、components、`source_bindings` 和 composition。`code_generated` 调用现有依赖 Skill 并保留 Skill 调用证据；`external_stock` 保留许可记录；`ai_generated` 是主动语义选择，不是其他来源无法执行后的替代项。

只生产 1080×1920/24fps 视频。A-roll 保留实拍背景且不抠像；B-roll 无常规字幕；头像为统一 head-shoulders 裁切。渲染串行，重型并发固定为 1。

## 十二阶段逐项合同

### 1. `inspect`

**输入**：当前 Job 索引中的主视频和文案。

**执行**：调用 `inspect_inputs.inspect_job(job)`，校验文件哈希、视频/音频流、时长、旋转、编码宽高、SAR 与 DAR、帧率、可解码性和文案编码。画面方向只按 DAR 判断；1080×1080、SAR=9:16、DAR=9:16 是有效 9:16 竖屏。不转写文案，不生成封面，不调用外部 provider。

**产物**：`01-inspect/report.json`。

**人工审核**：输入是否正确，时长/尺寸/声音是否符合预期。通过后只解锁 `content_analysis`。

### 2. `content_analysis`

**输入**：已批准 inspect 与绑定文案全文。

**执行**：一次性形成 thesis、hook、sections、items、claims、人物/机构/数字、精确关键词、证据状态和 B-roll 语义角色。每个上屏字串必须能追溯到文案。

**产物**：`02-content-analysis/content-analysis.json` 与 `review.md`。

**人工审核**：核心观点、重点句、关键词、事实、人物、数字和 B-roll 语义角色。批准后封面、视觉、贴片和字幕只读这份内容地图，不重做理解。

### 3. `cover_direction`

**输入**：已批准内容地图与当前 A-roll 人物参考帧。

**执行**：`cover_direction.prepare_cover_direction` 绑定当前 A-roll 或用户提供的人物参考，确定唯一输出比例、封面标题、人物动作/表情、环境、道具、构图、色板、字体和禁止项。显式加载 `gbro-cover-design` 作为构图提示词工具，但不继承它的固定比例默认值。

**产物**：`03-cover-direction/person-reference.png`、与批准比例一致的 `direction-preview.png`、`cover-direction.json`、`review.html`。人物参考图只绑定身份；审核页必须以方向样板为主图。

**人工审核**：先确认“要表达什么、人在做什么、环境是什么、标题是什么”。方向样板不是最终生成图，但必须用实际比例直接画出构图和核心语义；不能拿人物参考图或纯文字说明代替。

### 4. `cover`

**输入**：已批准封面方向、人物参考图和本 Job 已确认生图环境。

**执行**：`cover.prepare_cover(job, ...)` 只消费已批准 direction。生成器以批准比例制作无最终中文字层的场景/人物底图，cover runner 负责人物合成、本地中文排版、头脸保护区、外层/内层隐喻可辨性、边界和质量 QA。

**产物**：`04-cover/cover-<approved-ratio>.png`、`cover-delivery-raster.png`、`cover-report.json`；不得生成未批准比例的替代版。

**人工审核**：实际生成图，不是再确认一次方向。检查比例正确、脸部和头发不被挡、人物动作/环境符合主题、外层与内层叙事一眼可辨、中文准确和视觉吸引力。机器 QA 明显失败时不得报审。

### 5. `speech_cleanup`

**输入**：已批准 inspect、原口播视频和文案。

**执行**：`speech_edit_v2.prepare_transcription` 生成字级时码，`speech_edit_v2.prepare_cleanup_proposal` 只提议删除口误、明显重复和非语义停顿。不修改观点，不生成 B-roll。

不得只信单次 ASR。在报审前必须对全片做第二次独立转写，优先使用已绑定本地大模型的 Whisper DTW 词级对齐，并与首次转写、原稿及用户反馈交叉对照。要覆盖三类漏项：词内口吃（如“分—分享”）、相邻重复词、未完成后整句重说。ASR 合并了口吃或整句时，使用 v2 提案的 `reviewed_cut_ranges` 记录精确源时间、原因和证据，不伪造转写词边界。这些切点必须生成局部核听样片，人工审核确认后才能渲染正式 A-roll。

二次 ASR 的时间戳不得直接当作原片绝对时间；它只用于发现可疑文本。对每个候选切点，都要从原片音轨单独抽取局部片段，用唯一左右文重新定位绝对时间。同词多次出现时，禁止按第一个命中项猜测；必须证明选中的是用户指出的那次。`prepare_cleanup_proposal` 还必须验证 `reviewed_cut_ranges` 命中有效语音，不能基本是静音；核听片必须使用同一正式 renderer 和原片绝对 EDL 生成。输出 ASR 可以辅助核对上下文，但它会归一化口吃，不能单独证明重字已被删除。

**产物**：`05-speech-cleanup/word-transcript.json`、清理建议、差异和审核文档；该阶段的中间文件一次报审，不拆成重复人工门。

差异报告 `diff-summary.json` 的 `risk_assessment` 是只读规则提示（`version=1`、`method=conservative_rules_v1`），不是语义分类器或自动批准：

- `high`：候选涉及否定、限定、数字、条件/因果词，或带句末标点/较长文本的删除。保护词可跨转写词边界识别；规则可能误报，必须结合原声和上下文审核。
- `low`：仅限紧邻保留词的短前缀口吃，且保留依据未被人工时间裁切触及；完整重复词、远距离重复和未知短语不能据此判为低风险。`low` 也必须核听，不自动改剪点。
- `review`：其余候选默认待核听。`candidates` 保留源时码、词索引、上下文、原因、命中规则和局部核听范围；人工时间裁切另保留证据，`affected_text` 仅表示重叠词，不能冒充实际删掉的完整字词。无词重叠的裁切不虚构文本或索引。
- 风险提示不新增 ASR、独立文件或人工门，也不修改原词、文案及清理计划。修订计划或纠正转写后重新计算；纠错入口校验已有风险报告与所绑定的旧词/计划一致，不沿用旧结论。无风险字段的历史报告不代表已做风险检查。

审核时优先核听 `high`，再检查 `review` 与 `low`；`advisory_only` 和 `requires_audio_review` 始终为 true。完整观点、否定范围、反问及语气强调仍须人工判断，不能宣称规则已自动发现全部误删。

预检中的 `video-use-runtime` 和 `video-use-skill` 必须已满足。`prepare_cleanup_proposal` 在不删除正确字词的前提下，将同一 keep 段中大于等于 0.40 秒的无声间隙切成多个 EDL keep range，每侧保留 0.08 秒呼吸边缘；口误/重说仍以人工可审的 delete segment 表达。目录存在但入口或阶段绑定失败时不得生成提案。

**人工审核**：转写准确性、删改边界、第二次转写发现的重字/重说、局部核听样片和预计剪后时长。

#### 已确认的转写文字更正

只用于“原声正确、转写文字错误”，不删除音节、不改变词数量或时码。用户明确提出更正后，先读取当前登记的 `word-transcript.json`，保存其 `path`、`sha256`、`bytes` 和待改词的原始 `text/start/end`。使用 `revise(job, "speech_cleanup", <用户修改意见>)` 返回该阶段，重新加载并确认 `needs_revision`；更正源身份必须与此时 `lineage` 中的转写记录一致。不要直接编辑源 JSON 或手写 workflow。

在当前 Job 的独立维护输入位置保存 UTF-8 JSON manifest（不放进受控的七件产物目录）。精确字段如下；尖括号及示例时码必须替换为实际值：

```json
{
  "version": 1,
  "source": {
    "path": "05-speech-cleanup/word-transcript.json",
    "sha256": "<源文件实际小写 SHA-256，64 位>",
    "bytes": 123
  },
  "corrections": [{
    "word_start": 0,
    "word_end": 1,
    "expected_words": [{"text": "openai", "start": 0.2, "end": 0.8}],
    "replacement_texts": ["OpenAI"],
    "reason": "<本次核听和用户确认的更正依据>"
  }]
}
```

索引从 0 开始，区间为 `[word_start, word_end)`；多项按索引递增且不重叠。`expected_words` 和 `replacement_texts` 长度都必须等于区间词数；原词文字和时码逐项精确匹配，替换文字非空。只允许上述字段，不能附加疑点报告字段；不能借空字符串删词、合并词或猜测哈希。需改变词边界或真实剪点时，使用原清理提案流程，不强塞进文字更正 manifest。

执行 `PYTHONPATH="<project>" <python> -m edit.hd.tools.cli apply-cleanup-corrections --job "<job-dir>" --corrections "<absolute-manifest>"`。入口验证源身份并发布一套完整清理提案，保留更正审计历史；不会自行批准。成功后重新加载并报审 `speech_cleanup`，不直接跳回字幕。失败保留现场并核对身份／状态，不修改旧哈希让它通过。

### 6. `edit_structure`

**输入**：已批准清理建议与字级时码。

**执行**：`speech_edit_v2.render_edit` 按可追溯时码真实剪辑。口播音频为唯一主时钟；不重录音频，不通过复制末帧伪造对齐。

**产物**：`06-edit-structure/edit-plan.json`、`edited-aroll.mp4`、`timeline-map.json`。

存在剪点时，`render_edit` 只能从本 Job `manifests/dependency-preflight.json` 解析状态为 `bound` 的 `video-use-runtime`，生成临时 `video-use-edl.json` 并调用其正式 renderer；不得从聊天路径猜测，也不得回退到另一套无边缘淡化拼接。无剪点时可复制原音频元素流。临时 EDL 和中间分段在发布前清理，最终 `edit-plan.json` 与 `timeline-map.json` 必须记录 `render_adapter`。
`video-use` 的中间输出可能继承源素材的编码宽高和非方形像素，因此不能直接发布。必须在不重新处理已淡化音轨的前提下，先按 DAR 将非方形像素转换为方形像素，再规格化为 1080×1920/24fps。最终输出必须是 SAR=1:1、DAR=9:16；然后实际探测输出的视频宽高、SAR、DAR、帧率、视频时长、音频时长和二者差值。

**人工审核**：实际剪后视频、口播连续性、音画对齐和原生 9:16。

### 7. `visual_direction`

**输入**：已批准 content analysis、edit plan、timeline map，以及五类候选的 Job 内记录。

**执行**：先完成语义角色，再对 `local_material`、`official_material`、`code_generated`、`external_stock`、`ai_generated` 同级候选做语义判断。每段选择 `none` / `single` / `hybrid`；草案选中外部素材或 AI provider 时，先复核当前 Job 连接，再搜索、下载或生成并写入 Job。实际素材与记录齐全后冻结 `source_bindings`，编译 ShotRecipe v2，然后才报审。`code_generated` 组件冻结依赖 Skill 入口和调用记录；`external_stock` 冻结许可记录；不设来源优先级或配额，不做跨类替换。

**产物**：`07-visual-direction/visual-plan.json` 与 `visual-routing.md`。

**人工审核**：只确认视觉路由和镜头设计，不重问重点关键词。命名 CEO/研究者必须绑定第一方人物图片或官方视频及职务。

开场按 [封面入场、A-roll 开场与可选配乐](cover-opening-bgm.md) 安排：默认先由实拍 A-roll 引入话题，再出现相应证据 B-roll；启用封面时在它之后接 A-roll。时长按已批准语义区间决定，不固定秒数，不重新设计已批准封面。用户明确批准其他顺序时记录例外。

### 8. `visual_canary`

**输入**：已批准 VisualPlan schema v3 和其 ShotRecipe v2。

**执行**：使用正式 `segment_render.py` 从真实长片选代表镜头，总时长不超过 30 秒。只执行已批准配方，不做语义重选，不改写 kind、semantic_role、binding 或 composition。每镜头使用最终文案、字体、媒体、头肩头像、动效和同时间轴 A-roll 边界。

**产物**：`08-visual-canary/visual-canary.mp4`、`canary-manifest.json`、`segments/`、进/稳/出关键帧。

**人工审核**：不审“大概风格”，而审正式字节：文案、字体、布局、媒体、动性、头肩裁切、自然转场与信息密度。

### 9. `visual_assets`

**输入**：已批准 canary、VisualPlan schema v3 与全部已冻结 ShotRecipe v2。

**执行**：已批准 canary 以相同 SHA-256 字节复用，其余镜头严格执行各自已冻结配方。本阶段不做语义重选，不重新做来源判断，不改写已批准 binding。媒体记录缺失或文件不一致时 blocked，不以空海报代替。

**产物**：`09-visual-assets/asset-manifest.json`、`visual-track.mp4`、`segments/`、每镜头 manifest 与关键帧。

**人工审核**：正片是否精确复用样片，其余镜头是否符合同一批准系统。单镜头重试可通过 `artifact_scope` 强制重做指定段；已生成计划的修订按 [视觉修订合同](visual-revision-reuse.md) 比较输入并复用未变媒体。现有 DAG 仍会重置字幕、preview 和 delivery；媒体复用不代表这些阶段的批准自动保留。

### 10. `subtitles`

**输入**：已批准 content analysis、timeline map 和 visual track。

**执行**：`subtitles_v2.prepare_subtitles_v2(job)` 生成唯一 A-roll 字幕轨。B-roll 不叠常规口播字幕。每个 cue 保持简短；重点字只能是已批准精确关键词，无背景底色，可整体旋转和基线错位。

**产物**：`10-subtitles/subtitle-plan.json`、`subtitles.webm`、`subtitles.srt`、`contact-sheet.png`。

**人工审核**：读速、分句、位置、艺术字与已批准关键词一致，不再做内容提炼。

报审前，在实际项目运行时执行只读入口（不重新生成字幕）：

```bash
PYTHONPATH="<project>" <python> -m edit.hd.tools.cli review-subtitles --job "<job-dir>"
```

将返回的 `revision`、`artifact` 与当前字幕产物一起报审，在原有“注意”栏展示 `terminology_review.doubts`：每项列出 `observed`、候选 `expected`、原因及 `source_range`。该范围是原口播源时间（秒），`word_indices` 是源转写词索引，不是剪后视频或带封面成片时码；核听原片对应范围，不能直接跳到成片同一秒数。

- `available` 且疑点为空：只表述“本轮规则未发现术语疑点”，不能宣称全文准确。规则只覆盖明确历史更正可能重现和批准术语的大小写变体，不是完整语义校对。
- 有疑点：结合原声、上下文和历史更正来源核听；`expected` 是待确认候选，不自动替换字幕或原声。同一旧词在不同上下文有不同更正目标时，保留各项，不合并为全局替换。
- `legacy_report_unavailable`：明确说明“旧字幕产物没有术语报告，未证明已检查”；不当作无疑点，不补写旧产物或重签批准。
- 命令失败或报告身份变化：停止报审，报告错误并重新核对当前 Job；不直接读取未经验证的 JSON 绕过检查，也不重新生成已批准资产来掩盖失败。

该检查并入当前字幕人工门，不增加独立确认。用户指出源转写错误时，沿已有 `speech_cleanup` 修订链处理；运行时更正入口为 `apply-cleanup-corrections --job <job-dir> --corrections <manifest>`，必须按当前运行时合同准备绑定源转写身份的更正 manifest，不把疑点 JSON 直接作为 manifest。源音视频中真实口吃或念错不能靠改文字修复，仍需清理阶段的精确剪点和核听。返回上游后按既有依赖重审，不沿用已失效的字幕批准。

### 11. `preview`

**输入**：已批准视觉资产、字幕和剪辑后 A-roll 音频。

**执行**：`preview_v2.prepare_preview_v2(job)` 以 A-roll 口播音频为主时钟合成。默认无背景音乐，不产生第二个口播音轨。检查尺寸/帧率/帧数、转场、来源、字幕、安全区、头像和音画差。

用户明确要求开场封面或配乐时，另读 [封面入场与可选配乐](cover-opening-bgm.md)，使用 `prepare_preview_v2(job, opening=..., music=...)`，仅传本次已选选项。正文与原声仅平移 `hold_frames`，导出最终时钟 SRT；不修改已批准正文结构。参数变化先修订 `preview`，重复调用不重渲染。音乐由正式预览混成单音轨，不单独修改最终 MP4。

**产物**：`11-preview/review.mp4`、`qa-report.json`、`contact-sheet.png`、`keyframes/`。启用封面时还登记 `opening-manifest.json` 和偏移后的 `subtitles.srt`，缺任一项停止复用或交付。

**人工审核**：完整观看全片，机器 PASS 不是批准。任何修改返回最小影响上游，不从头重做。

### 12. `delivery`

**输入**：已批准 preview 和它的 QA/哈希身份。

**执行**：`qa_delivery_v2.prepare_delivery_v2(job)` 将成片、封面、字幕、plans、QA、用户素材索引和所有必要 manifest 复制到不可变交付目录。不上传、不发布、不发消息。

**产物**：`12-delivery/final.mp4`、封面、字幕、`plans/`、`qa/`、`delivery-manifest.json`。

启用封面时交付 `opening-manifest.json`，SRT 与最终视频同一时钟；原透明字幕 WebM 改存 `plans/body-subtitles.webm`，明确仍为正文时钟。完成审计核对封面清单、最终字幕绑定、总时长和音轨，不因文件存在就认定偏移正确。

启用音乐时原样交付预览登记的音乐清单、音乐审计音频、许可原件和署名文本；成片与批准预览字节完全一致。自动响度检查不能代替 preview 人工试听，不能自动替用户批准。

**人工审核**：交付库与已批准 preview 身份一致。用户对当前 `delivery` 回复确认后，使用最终确认入口；不得把进度要求、机器 PASS 或历史确认当成本次批准。

### 最终确认入口

报审时保存当前 `revision`、`12-delivery/final.mp4` 的 SHA-256 及可观看路径；收到真实确认后传入这些已展示身份，而不是把新版本身份套到旧确认上。保持当前项目运行时和唯一 Job，调用：

```bash
PYTHONPATH="<project>" <python> -m edit.hd.tools.cli approve \
  --job "<job-dir>" --stage delivery \
  --expected-revision <reviewed-revision> \
  --delivery-sha256 <reviewed-final-sha256> \
  --user-confirmation "<本次用户确认原文>"
```

尖括号替换为当前任务值。宿主应使用参数数组传递原文，不能把用户文本拼接进 shell。Python 宿主可调用 `delivery_approval.approve_delivery(job, expected_revision=..., delivery_sha256=..., user_confirmation=...)`。其他阶段继续使用原批准入口，不增加重复确认。

入口核对已登记成片、批准预览、交付 manifest、全部交付文件集合和当前 revision。启动预检必须验证 `final-approval-runner` 的 `approve_delivery` 可调用，不能只检查交付文件生成器。`approval-receipt.json` 记录确认原文、UTC 时间、报审工作流身份及交付/manifest 的哈希；回执登记与 `delivery=approved` 共用一次工作流 CAS，只增加一次 revision。回执先写入时只是待提交意图，不是完成证据。

- 提交前中断：保持原文件和工作流，使用同一 revision、SHA-256、确认原文重试；不改回执，不重新请求用户批准未变内容。
- 写入期间硬中断：未发布的独占暂存目录留在 Job 根，不进入交付清单、不作为批准证据，也不阻塞原请求重试；发布采用排他原子移动，不能覆盖现有回执。自动清理仅限当前进程拥有的暂存目录，不扫描删除历史残留。
- 提交成功但响应中断：相同请求只读验证并返回，不再次增加 revision。
- 身份、清单或确认原文变化：停止；重新核对实际待审版本，不能强行覆盖回执。已有批准而没有原回执的历史 Job 不自动补签。
- 用户返修：仍走 `state.revise`，原回执随 artifact lineage 退出当前批准，不能授权新 revision。`revise` 当下不改历史文件；成功重建交付目录后旧回执退出文件集合，lineage 也会更新，它不是长期归档。新交付重新报审，不自动沿用旧确认。

成功后重新加载并调用 `scripts/audit_job_completion.py --workspace <workspace> --json`。只有回执已正式登记、绑定当前批准 revision、全部交付文件及 manifest 哈希匹配且实际媒体探测通过才返回 `formal_complete`；待提交或正常返修为 `incomplete`，登记文件丢失/篡改、未知交付文件或损坏记录为 `inconsistent`。检查范围包括字幕、封面、计划和 QA，不仅是 MP4。确认原文是宿主对真实用户输入的记录，不是独立身份认证；Agent 不得伪造它来通过机器检查。

## 完成边界

- 维护回归必须覆盖真实十二阶段端到端以及批准后的转写返修，不能只测独立模块。`full-v2` 的素材使用回执属于正式阶段库存和返修 lineage，须连同业务文件核对身份；不得为兼容旧测试而删掉回执。正式视觉资产清单中的复用段 ID 与输入身份必须一起传递并验证，不能只更新生产端而遗漏 preview 消费端。

- `ready_for_review` 不是完成；任何机器 QA 或渲染成功不得越过人工门。
- 一个已批准阶段不因下游反复询问而重做；只在它自身的输入、绑定、字节或用户决策改变时形成 revision。
- 开始下一个新视频时必须新建独立 workspace，不复制上一 Job 的状态或 provider 连接状态。
- 终态用 `scripts/audit_job_completion.py` 做只读审计，只返回 `formal_complete` / `legacy_external_approval` / `incomplete` / `inconsistent`。审计不补回执、不批准阶段、不修改媒体；新 Job 必须以当前 revision 的十二阶段、交付媒体探测/哈希与最终人工批准回执同时闭环，才可称 `formal_complete`。
