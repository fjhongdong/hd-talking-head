# 十二阶段执行合同

## 目录

1. 全局顺序与阶段表
2. 内容唯一性与不重复
3. 状态操作
4. 十二阶段逐项合同
5. 视觉生产必须项
6. 完成边界

本文件只描述 `full-v2` 正式流程。视觉阶段冻结的主计划为 VisualPlan schema v3 和 ShotRecipe v2，不兼容旧 visual Job；旧 visual Job 重新执行 `visual_direction`。TalkCraft 工作台另消费派生的 span-aware v4 计划（同一 validator 校验），不改主计划冻结格式。每个 runner 只能把当前阶段推进到 `ready_for_review`；机器 PASS 不等于批准；中间阶段按本 Skill 的“结果确认”策略完成本地 QA 后由宿主内部批准。用户确认保留在配置、付费/外部动作、封面方向、实际封面和完整 `visual-routing.md`；视觉清单确认后，后续成片阶段均由宿主内部 QA 推进，不再请求用户确认。

十二阶段不是依赖安装器。进入 `inspect` 前，当前 Job 必须已有通过的 `manifests/dependency-preflight.json`，并完成本 Job 的动态 provider/插件配置确认。缺少必需运行时、runner 或 Skill 时停在阶段外的依赖门；不得先运行部分阶段再补依赖。

该门由 `state.require_runnable → startup.require_startup` 实际执行：读取 workspace 的 `job-context.json` 以及 job_dir 内的 `manifests/provider-config.json`、`manifests/dependency-preflight.json`、`manifests/setup-approval.json`。配置批准通过 `confirm_job_setup.py` 保存，不新增第十三个媒体阶段。环境证据失效不自动重做已批准内容、封面或剪辑。首次 inspect 支持预建空目录；未知文件及不完整旧产物仍停止并保留。

产品执行顺序固定为：

`inspect → content_analysis → cover_direction → cover → speech_cleanup → edit_structure → visual_direction → visual_canary → visual_assets → subtitles → preview → delivery`

底层状态是精确 DAG，但控制器仍按上述产品顺序选择最早未完成阶段，一次只报审一个。这保证封面方向和文案重点在开头决定，不在后面重复工作。

## 阶段表

| 阶段 | 公共入口 | 固定产物 | 验收重点 |
| --- | --- | --- | --- |
| `inspect` | `edit.hd.tools.inspect_inputs.inspect_job(job)` | `01-inspect/report.json` | 视频/音频流、时长、编码宽高、SAR 与 DAR、文案身份 |
| `content_analysis` | `edit.hd.tools.content_analysis.prepare_content_analysis(job, analysis)` | `02-content-analysis/content-analysis.json`, `review.md` | 唯一内容理解、核心观点、重点、精确关键词、事实/人物/数字、B-roll 语义角色 |
| `cover_direction` | `edit.hd.tools.cover_direction.prepare_cover_direction(job, direction)` | `03-cover-direction/person-reference.png`, `cover-direction.json`, `review.html` | 封面大体内容、唯一输出比例、标题、人物动作、环境、构图和字体方向 |
| `cover` | 优先加载项目内 `punk-cover` 生成完整候选；正式发布仍调用 `edit.hd.tools.cover.prepare_cover(job, ...)` | `04-cover/cover-<approved-ratio>.png`, `cover-delivery-raster.png`, `cover-report.json` | 只交付批准比例；实际封面图、五官清楚、隐喻可辨、动作/环境贴题、中文无误 |
| `speech_cleanup` | `video-use/helpers/transcribe.py` 负责字级转写；项目适配器以 `transcribe.transcribe_job(job, video_use_result=..., invocation=...)` 验收原始结果，再调用 `speech_edit_v2.prepare_cleanup_proposal(job, plan)`，并应用已绑定的 pacing profile | `05-speech-cleanup/` 内完整产物及原始调用证据 | 源视频身份、真实调用、字级时码与覆盖率、删改差异、0.40 秒长停顿切分、预估时长；中间产物不单独报审 |
| `edit_structure` | `edit.hd.tools.speech_edit_v2.render_edit(job)`；有剪点时必须调用预检报告绑定的 `video-use/helpers/render.py` | `06-edit-structure/edit-plan.json`, `edited-aroll.mp4`, `timeline-map.json` | EDL 真实剪辑、原口播音频主时钟、30ms 音频边缘、原生 9:16 A-roll |
| `visual_direction` | `edit.hd.tools.visual_plan.prepare_visual_direction(job, director_brief, official_registry, treatment_path=...)` | `07-visual-direction/visual-plan.json`, `visual-routing.md` | 基于剪后语义生成 tags，匹配具体模板并列出整片视觉清单；用户一次确认后冻结 `source_bindings`、编译 ShotRecipe v2 |
| `visual_canary` | `edit.hd.tools.visual_canary.prepare_visual_canary(job, ...)` | `08-visual-canary/visual-canary.mp4`, `canary-manifest.json`, `segments/` | 不超 30 秒的真实长片段落；只执行已批准配方 |
| `visual_assets` | `edit.hd.tools.visual_assets_v2.prepare_visual_assets_v2(job, ...)` | `09-visual-assets/asset-manifest.json`, `visual-track.mp4`, `segments/` | 已批准 canary 字节哈希完全一致；严格执行剩余已冻结配方 |
| `subtitles` | `edit.hd.tools.subtitles_v2.prepare_subtitles_v2(job)` | `10-subtitles/subtitle-plan.json`, `subtitles.webm`, `subtitles.srt` | A-roll 与有口播的 B-roll 共用唯一常规字幕轨；艺术字只能是精确已批准关键词 |
| `preview` | `edit.hd.tools.preview_v2.prepare_preview_v2(job, opening=...)`；默认值见封面入场合同 | `11-preview/review.mp4`, `qa-report.json`, `keyframes/` | 1080×1920/24fps、Wake 正文首镜且零时间偏移、一视频一主音轨、默认无背景音乐、来源/字幕/安全区/转场 QA |
| `delivery` | `edit.hd.tools.qa_delivery_v2.prepare_delivery_v2(job)` | `12-delivery/final.mp4`, 封面、字幕、plans、qa、用户资料索引、`delivery-manifest.json` | 交付与已批准 preview 同哈希；视觉清单已确认且宿主 QA 通过后完成 |

上表每个阶段进入 `ready_for_review` 时都额外发布同目录 `material-usage.json`，并将它加入该阶段正式 artifact 集。回执必须是 `complete_reference_declaration=true`；没有使用用户资料的阶段发布空 `references`，不得省略声明。完整字段、校验和变更规则见 [权威素材使用回执与变更事务](material-usage-contract.md)。

## 内容唯一性与不重复

`02-content-analysis/content-analysis.json` 是唯一语义事实源。封面标题、视觉路由、A-roll 贴片、B-roll 上屏文案和字幕艺术字只能引用已批准 item/source_text/keywords。下游不重新调用 LLM 提炼，不再向用户询问“哪些是重点”。

字幕和高亮关键词仍须精确绑定原稿与实际口播。图形标签可按本句语义改写，但不得隐藏实际屏显文案或把释义塞进关键词：向 `prepare_visual_direction(..., reviewed_visual_text=...)` 传入 `{content_analysis_sha256, entries}`，每条 entry 精确记录 `segment_id/text/source_ref/source_quote/reason`。`source_ref` 只允许当前段已选的 `item:<id>` 或批准的 `thesis`，quote 必须逐字匹配其事实源；记录须覆盖所有非逐字屏显标签。身份、文字或来源变化时重新审阅，不沿用旧记录，不增加人名、金额或能力事实。宿主审阅否定范围、条件和未来设想，机器校验身份不能代替语义判断。审阅记录随正式 `visual-routing.md` 发布并绑定，不增加新审批阶段，也不改变原字幕。

`cover_direction` 记录设计方向批准，`cover` 记录实际图片批准，两类证据不能相互冒充。用户明确确认的完整图片能唯一绑定本 Job 候选时，后续技术登记和同字节发布不另要一次相同图片的确认；仍按两个阶段串行保存各自证据，不手改状态或代签。`visual_canary` 是正式段落，`visual_assets` 必须复用其 generation identity 和媒体 SHA-256，不得“照样再做一次”。

五类 B-roll 的权威策略块为：

五类来源同级：无优先级、无配额、禁跨类替换；权威策略块唯一维护在 [B-roll 语义能力路由](broll-capability-router.md#唯一选型入口与记录)，此处不再复制正文。

每段可选 `none` / `single` / `hybrid`；语义角色与素材来源分离。五类同级，不设来源优先级、不设来源配额、不做跨类替换；它们之间不是降级关系。

## 状态操作

- runner 返回后重新 `load_job`，验证当前阶段为唯一 `ready_for_review`。
- 中间阶段本地 QA 和绑定校验通过后内部批准当前阶段，再重新加载状态；需要用户决定的阶段等待真实确认。视觉清单确认后，后续阶段使用宿主内部批准，不直接调用裸 `state.approve`。
- 修改意见调用 `revise`。只改单个正式视觉段时使用 `artifact_scope=("seg-xxx",)`。
- 已选来源暂时无法执行时 `block`，当前 generation 不自动重试；只给出 `retry_same_strategy` 或 `replan_visual_direction`。
- `delivery ready_for_review` 仍不是完成；视觉清单确认、宿主 QA、正式回执及只读审计通过，才可宣称正式完成。该完成状态表示已制作交付，不表示用户另行验收成片。

## 视觉生产必须项

`visual_direction` 使用 `scripts/broll_capability_router.py` 为每个段落编译稳定 ShotRecipe v2。五类候选都按语义匹配、内容真实性、原生竖屏、画质可读性和来源记录评估，然后冻结 mode、components、`source_bindings` 和 composition。`code_generated` 调用现有依赖 Skill 并保留 Skill 调用证据；`external_stock` 保留许可记录；`ai_generated` 是主动语义选择，不是其他来源无法执行后的替代项。

只生产 1080×1920/24fps 视频。A-roll 保留实拍背景且不抠像；B-roll 与 A-roll 共用唯一原声字幕轨，避开统一 head-shoulders 圆形头像。本地重渲染和正式 runner 串行；最多 3 路独立材料准备，图片和视频通过[有界生成编排](production-bindings.md#有界生成编排)共用 2 个名额。正式状态转换、组装、材料回执和最终交付仍由主控顺序完成。

## 十二阶段逐项合同

### 1. `inspect`

**输入**：当前 Job 索引中的主视频和文案。

**执行**：调用 `inspect_inputs.inspect_job(job)`，校验文件哈希、视频/音频流、时长、旋转、编码宽高、SAR 与 DAR、帧率、可解码性和文案编码。画面方向只按 DAR 判断；1080×1080、SAR=9:16、DAR=9:16 是有效 9:16 竖屏。不转写文案，不生成封面，不调用外部 provider。

**产物**：`01-inspect/report.json`。

首次检查尚未发布产物时，即使任务因启动问题已进入 `needs_revision`，仍允许替换初始化器创建的普通空目录；必须同时没有当前产物和历史 lineage，并继续通过原有目录及文件身份检查。存在发布历史、未知文件或不明事务时停止恢复，不把丢失的旧结果当作首次制作，也不手工清空目录来通过。

**验收**：输入是否正确，时长/尺寸/声音是否符合预期。通过后只解锁 `content_analysis`。

### 2. `content_analysis`

**输入**：已批准 inspect 与绑定文案全文。

**执行**：一次性形成 thesis、hook、sections、items、claims、人物/机构/数字、精确关键词、证据状态和 B-roll 语义角色。每个上屏字串必须能追溯到文案。

**产物**：`02-content-analysis/content-analysis.json` 与 `review.md`。

**验收**：核心观点、重点句、关键词、事实、人物、数字和 B-roll 语义角色。批准后封面、视觉、贴片和字幕只读这份内容地图，不重做理解。

### 3. `cover_direction`

**输入**：已批准内容地图与当前 A-roll 人物参考帧。

**执行**：`cover_direction.prepare_cover_direction` 绑定当前 A-roll 或用户提供的人物参考，确定唯一输出比例、封面标题、人物动作/表情、环境、道具、构图、色板、字体和禁止项。9:16 图文穿插方向优先加载项目内 `punk-cover` 及唯一选中的风格，形成构图和完整候选；现有 `gbro-cover-design` 仅用于旧 runner 的 brief/无字底图路径。子 Skill 的默认比例都不改写本 Job 的批准比例。

**产物**：`03-cover-direction/person-reference.png`、与批准比例一致的 `direction-preview.png`、`cover-direction.json`、`review.html`。人物参考图只绑定身份；审核页必须以方向样板为主图。

**验收**：先确认“要表达什么、人在做什么、环境是什么、标题是什么”。方向样板不是最终生成图，但必须用实际比例直接画出构图和核心语义；不能拿人物参考图或纯文字说明代替。

### 4. `cover`

**输入**：已批准封面方向、人物参考图和本 Job 已确认生图环境。

**执行**：`cover.prepare_cover(job, ...)` 只消费已批准 direction。若用户已认可带字的完整封面预览，先核对其文字与方向一致，再传 `approved_preview`、原图 SHA-256 和实际生成提示词原样发布；不生成或要求无字底图，不重新生图或叠字。若只批准了方向、尚未批准成图，才可选择无字底图加本地中文排版的候选路线。两种路径都检查比例、中文、人物和主题表达；完整图的五官、手部与字形由人工在正式尺寸下检查，不伪造本地排字的像素框，具体见封面合同。

**产物**：`04-cover/cover-<approved-ratio>.png`、`cover-delivery-raster.png`、`cover-report.json`；不得生成未批准比例的替代版。

**验收**：实际生成图，不是再确认一次方向。检查比例正确、五官和叙事手部清楚、人物动作/环境符合主题、外层与内层叙事一眼可辨、中文准确和视觉吸引力；用户认可的少量发丝与标题穿插允许保留。机器 QA 明显失败时不得报审。

### 5. `speech_cleanup`

**输入**：已批准 inspect、原口播视频和文案。

**执行**：先核对本次原声上传/额度许可和凭据，从本 Job 预检绑定的 `video-use-runtime.resolved_path` 解析并实际调用 `helpers/transcribe.py <源视频> --edit-dir <本Job工作区/edit>`。进程工作目录使用同一预检报告中的 `video-use-skill.resolved_path`，以便 helper 读取已安装 Skill 的私有 `.env`；若凭据由进程环境安全注入则无需改工作目录，不把密钥复制到项目或回执。确认输出路径不会命中其他源素材的同名缓存；保留原始 JSON，记录 `invocation={"entrypoint":入口绝对路径,"exit_code":0,"source_sha256":本Job视频哈希,"result_sha256":原始JSON哈希}`。调用 `transcribe.transcribe_job(job, video_use_result=原始JSON路径, invocation=invocation)`；适配器核对入口绑定、原片身份、响应、字级时码顺序/范围和文案覆盖率，原始 JSON 发布为 `scribe.json`。Scribe 的纯句读（包括省略号和破折号）和空白只保留文本，不独立占用发声时段，也不扩大实词起止时间；零时长实词仅在与前一有效词的结束时间重合时合并文本，分离时停止并保留证据，不猜发音区间。合并零时长事件不能延长前词，原始响应不改写。验收通过后，`speech_edit_v2.prepare_cleanup_proposal` 只提议删除口误、明显重复和非语义停顿。不修改观点，不生成 B-roll。单纯运行 `timeline_view.py` 或 `pack_transcripts.py` 不能代替转写调用；本地 Whisper 不能让此阶段通过。

不得只信单次 ASR。在报审前必须对全片做第二次独立转写，优先使用已绑定本地大模型的 Whisper DTW 词级对齐，并与首次转写、原稿及用户反馈交叉对照。要覆盖三类漏项：词内口吃（如“分—分享”）、相邻重复词、未完成后整句重说。ASR 合并了口吃或整句时，使用 v2 提案的 `reviewed_cut_ranges` 记录精确源时间、原因和证据，不伪造转写词边界。这些切点必须生成局部核听样片，宿主核听确认切点后才能渲染正式 A-roll；存在歧义或用户要求核听时才报审。

二次 ASR 的时间戳不得直接当作原片绝对时间；它只用于发现可疑文本。对每个候选切点，都要从原片音轨单独抽取局部片段，用唯一左右文重新定位绝对时间。同词多次出现时，禁止按第一个命中项猜测；必须证明选中的是用户指出的那次。`prepare_cleanup_proposal` 还必须验证 `reviewed_cut_ranges` 命中有效语音，不能基本是静音；核听片必须使用同一正式 renderer 和原片绝对 EDL 生成。审核样片应取一段连续口播并保留剪点前后语境，若展示给用户则在画面标明剪点；不得把相隔很远的剪点短片串成一条“卡顿合集”要求用户找问题。输出 ASR 可以辅助核对上下文，但它会归一化口吃，不能单独证明重字已被删除。

#### 辅助转写按句复用

第二次独立识别已有本 Job 内保存的真实 Whisper JSON 时，复用该结果，不因词级缓存读入失败再次运行模型。原生句段可用于对照文字；零时长词不代表识别进程没有完成，也不允许跨段拼词、均分时长或放宽通用词级检查。

明确选择离线按句复用后，经项目统一 Python 入口调用 `edit.hd.tools.reference_transcripts.import_saved_reference_segments(job_dir, material_id, raw_result=原始JSON绝对路径, expected_sha256=实际原始摘要, language=本次语言)`。入口核对当前 Job、素材、运行时、原始文件及语言，逐段保留 `transcription[].text` 和 `offsets`，发布 `precision=segment` 的辅助参考；正常词级入口仍保持原规则，不在失败后自动切换。已有不同结果或词级报告时停止，不覆盖。没有真实原始结果时报告缺口，不新增识别。

通过已有 Job 参考检索读取实际精度，命中仍为 `precise_cut_eligible=false`。只用这些粗略范围寻找需核听的位置，不能直接用于切点、字幕、关键词或视觉时钟；正式 Scribe 数据不变。原生文字、段边界和疑似重复完整保留，是否误识别或真实重说必须与原稿、Scribe 和原声交叉核对。离线导入与检索成功只证明参考资料可读，不代表口吃核听或 `speech_cleanup` 已验收。

**产物**：`05-speech-cleanup/word-transcript.json`、清理建议、差异和审核文档；该阶段的中间文件由宿主一并验收，不拆成重复人工门。

差异报告 `diff-summary.json` 的 `risk_assessment` 是只读规则提示（`version=1`、`method=conservative_rules_v1`），不是语义分类器或自动批准：

- `high`：候选涉及否定、限定、数字、条件/因果词，或带句末标点/较长文本的删除。保护词可跨转写词边界识别；规则可能误报，必须结合原声和上下文审核。
- `low`：仅限紧邻保留词的短前缀口吃，且保留依据未被人工时间裁切触及；完整重复词、远距离重复和未知短语不能据此判为低风险。`low` 也必须核听，不自动改剪点。
- `review`：其余候选默认待核听。`candidates` 保留源时码、词索引、上下文、原因、命中规则和局部核听范围；人工时间裁切另保留证据，`affected_text` 仅表示重叠词，不能冒充实际删掉的完整字词。无词重叠的裁切不虚构文本或索引。
- 风险提示不新增 ASR、独立文件或人工门，也不修改原词、文案及清理计划。修订计划或纠正转写后重新计算；纠错入口校验已有风险报告与所绑定的旧词/计划一致，不沿用旧结论。无风险字段的历史报告不代表已做风险检查。

审核时优先核听 `high`，再检查 `review` 与 `low`；`advisory_only` 和 `requires_audio_review` 始终为 true。完整观点、否定范围、反问及语气强调仍须人工判断，不能宣称规则已自动发现全部误删。

预检中的 `video-use-runtime` 和 `video-use-skill` 必须已满足。`prepare_cleanup_proposal` 在词间寻找连续安静中段，保留现有 40ms 窗 −40dB 与安静段平均 −48dB 门槛；不要求含真实词尾的整个 ASR 间隔都安静。只选择至少 0.40 秒的连续安静段，两端再各保留 0.08 秒；不跨过有声岛。新内部 padding 从实际删除边界与词时码相减得到，不能继承原段的长 padding，也不能一律设为 0.08 秒；原段外侧 padding 保持。跨 keep 只收紧实际保留音频的安静尾部/头部，已删掉的源时间不再计入，现有人工裁切不扩大。口误/重说仍以人工可审的 delete segment 表达。目录存在但入口或阶段绑定失败时不得生成提案。

#### 句间停顿与自然衔接

首次清理就检查句间节奏，完成后再冻结视觉计划；用户要求原样保留停顿时遵从本次要求。自动静音切分只是第一遍处理，不代表带呼吸声、低底噪的长空白已清理完。宿主结合已校对词、完整句意和原声复核明显拖长的等待，不调低静音阈值来替代判断，不仅凭标点或 ASR 词间距删声音。

- 普通知识口播可优先复核约 0.8 秒以上的句间间隔，特别是 1～2 秒的空白；它是找候选的参考，不是自动删除线。反问、强调、情绪转折、必要吸气及尚未讲完的语气要保留。长空白收紧后可先以约 0.3～0.5 秒作为核听起点，再按前句收尾与下句起声调整；不统一压成固定值，不以剪掉最多秒数为目标。
- 只剪已核对的空白中段，保留句尾、句首与呼吸边缘，不改变原语速。普通停顿只通过切分 `keep` 段和 `breathing_padding` 表达，不放入要求命中有效语音的 `reviewed_cut_ranges`，也不新增删词段。
- 在词索引 `k` 的间隔内删除源时间 `[a,b)` 时，将原 keep 拆为连续的两段：左段止于 `k`，右段始于 `k`；两段的 `source_start/source_end` 仍精确取各自首末词时码。左段 `after=a-words[k-1].end`，右段 `before=words[k].start-b`，外侧 padding 沿用原段。两个余量须非负；两段文字分别取各自词原文，词序、词数和原有删改不变。不要用扩大词时码或改成空字符串表示剪切。
- 使用现有 `edit_timeline.validate_edit_plan` 校验提案，再交给 `speech_edit_v2.prepare_cleanup_proposal` 和正式 `render_edit` 调用已绑定的 `video-use` renderer。沿用其 30ms 音频边缘淡化与声画共同剪辑，不自写拼接器，不只裁音轨或最终 MP4。末段遵从声明的 `breathing_padding.after`，不自动延至原片结尾。

已有成片返修时，先从当前成片定位间隔，再通过旧 `timeline-map.json` 映回原片词锚；由正式 `revise(speech_cleanup)` 返回清理阶段。重新发布时消费 lineage 绑定的当前校对词及校对历史，不退回原始 Scribe 错字。保存本轮剪点与已有维护输入即可，不复制上一 Job 的具体词索引、秒数或独立制作脚本。主时钟变化后的视觉复用及字幕对齐见[停顿返修后的时钟对齐](visual-revision-reuse.md#停顿返修后的时钟对齐)。

内部核对每个新剪口前后保留词的源音频范围没有缩短，再以连续上下文核听衔接；不能仅凭总时长变短判定自然。已有转写与原声足够时不再转写；核对无歧义的常规停顿不逐处询问用户，也不新增收费调用。未实际核听时如实说明，不把波形或机器检查称为听感验收。

自动检查在本阶段返回 `cleanup_checks`：以 renderer 实际保留区间计算约 0.8 秒以上的残留间隔，并从当前保留文本中查找相邻中断起头、短片段重复前缀、完整句重说。字符映射跨 ASR 分词和 keep 分段；删除词不参与，完整时间裁切的词不再重复报警，部分词仍需核听。检测只是候选，不能凭相似文字自动删除有意强调或否定。文本候选同时写入原 `diff-summary.json` 的 `risk_assessment.retained_repetitions`，纠错时重算，不额外建报告。

宿主在本阶段自行抽取连续上下文并核听：确认口误时按现有 delete/reviewed_cut 流程处理，重新生成提案直到对应候选消失；确需保留时，在本次 `--review-json` 的 `speech_cleanup_resolutions` 中逐项提供 `{candidate_id, decision: "keep", reason: "核听后的具体保留原因"}`。空理由、泛称已处理、残留候选声称已剪掉、缺项/重复项均不通过。无歧义的常规处理不再询问用户。审批入口实时重算候选；`render_edit` 对残留项再要求绑定当前完整 speech_cleanup artifacts 的宿主回执，直接批准状态也不能绕过。原有删除风险提示仍为提示，不与这一残留候选门混为一谈。

**验收**：转写准确性、删改边界、第二次转写发现的重字/重说、局部核听样片和预计剪后时长。

#### 转写文字校对

只用于“原声正确、转写文字错误”，不删除音节、不改变词数量或时码。默认以本期原稿校对同音错字、术语、大小写及误识别标点；宿主结合原声上下文和二次 ASR 自动判断并执行，不向用户列字词选项，不要求每处更正批准。用户主动更正也使用同一入口。原稿是文字校对依据，不是替换实际口播的时间线：保留真实的口语补充、语气词和表达顺序；未念出的内容不能补入字幕。实际念错、漏念或改变含义时交回清理剪辑处理，不能用正确字幕掩盖错误声音；无法判明且影响含义时报告具体问题，不提供无依据的字词选择。
两路 ASR 文字不同本身不构成提问理由：原稿能支持的常规校对，以及能由独立识别和上下文判断的口语内容，均由宿主处理。只有剩余不确定性会实质改变事实或观点时才说明具体影响并询问；不把普通字词选择和整条口播核听设为默认确认门。用户已认可口播衔接后，纯文字校对不改变音频、剪点或时码，也不再次要求核听同一版。

先读取当前登记的 `word-transcript.json`，保存其 `path`、`sha256`、`bytes` 和待改词的原始 `text/start/end`。使用 `revise(job, "speech_cleanup", <本次校对依据或用户修改意见>)` 返回该阶段，重新加载并确认 `needs_revision`；更正源身份必须与此时 `lineage` 中的转写记录一致。不要直接编辑源 JSON 或手写 workflow。自动校对原因如实标为宿主按原稿处理，不伪造用户逐字确认。

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
    "reason": "<本期原稿对应文本与本次校对证据；用户主动更正时附原意>"
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
生成 EDL 时须剔除删词或标点切分后留下的无台词短碎片；不能把补留的呼吸边缘单独渲成一帧或数帧。确有语音的短词不能按时长一概删除，须保留并在成片剪点核查。
`video-use` 的中间输出可能继承源素材的编码宽高和非方形像素，因此不能直接发布。必须在不重新处理已淡化音轨的前提下，先按 DAR 将非方形像素转换为方形像素，再规格化为 1080×1920/24fps。最终输出必须是 SAR=1:1、DAR=9:16；然后实际探测输出的视频宽高、SAR、DAR、帧率、视频时长、音频时长和二者差值。

**验收**：实际剪后视频、口播连续性、音画对齐和原生 9:16。

### 7. `visual_direction`

**输入**：已批准 content analysis、edit plan、timeline map，以及五类候选的 Job 内记录。

代码/AI B-roll 先执行[两轮跨 Skill 选型](broll-capability-router.md#唯一选型入口与记录)，把本期新增、复用和资料镜头放入同一整片协调。正式入口显式传入当前 Job 的 treatment；缺记录或绑定偏离时先停止，不先生成、冻结或发布再补选型理由。原生版式和动作保留，不把不同 Skill 统一压成同一套卡片布局。

A-roll 透明贴片另按[贴片合同](aroll-overlay-contract.md#必须验收)在同一 treatment 填写 `overlay_selection`，由正式入口核对语义关系、真实组件和可见结构；同形重复须有具体 `repeat_review`。不把 B-roll 选型通过当作贴片已经完成选型，也不把可渲染目录当作正式可用入口。主控协调的是质感与可读性，保留每种原生构图和动作。

**执行**：先完成语义角色，再对 `local_material`、`official_material`、`code_generated`、`external_stock`、`ai_generated` 同级候选做语义判断。每段选择 `none` / `single` / `hybrid`；草案选中外部素材或 AI provider 时，先复核当前 Job 连接，再搜索、下载或生成并写入 Job。实际素材与记录齐全后冻结 `source_bindings`，编译 ShotRecipe v2，然后才报审。`code_generated` 组件冻结依赖 Skill 入口和调用记录；`external_stock` 冻结许可记录；不设来源优先级或配额，不做跨类替换。

**产物**：`07-visual-direction/visual-plan.json` 与 `visual-routing.md`。

**验收**：只确认视觉路由和镜头设计，不重问重点关键词。命名 CEO/研究者必须绑定第一方人物图片或官方视频及职务。

开场按 [封面首镜合同](cover-opening-bgm.md) 安排：首镜固定使用已批准封面调用完整 Lemo Wake，原声、字幕和编号从第 0 帧开始；首镜结束后按语义衔接 A-roll 和正文 B-roll。清单确认后执行原生子任务，不追加用户确认。

### 8. `visual_canary`

**输入**：已批准 VisualPlan schema v3 和其 ShotRecipe v2。

**执行**：使用正式 `segment_render.py` 从真实长片选代表镜头，总时长不超过 30 秒。只执行已批准配方，不做语义重选，不改写 kind、semantic_role、binding 或 composition。每镜头使用最终文案、字体、媒体、头肩头像、动效和同时间轴 A-roll 边界。

**产物**：`08-visual-canary/visual-canary.mp4`、`canary-manifest.json`、`segments/`、进/稳/出关键帧。

**验收**：不审“大概风格”，而审正式字节：文案、字体、布局、媒体、动性、头肩裁切、自然转场与信息密度。

### 9. `visual_assets`

**输入**：已批准 canary、VisualPlan schema v3 与全部已冻结 ShotRecipe v2。

**执行**：已批准 canary 以相同 SHA-256 字节复用，其余镜头严格执行各自已冻结配方。本阶段不做语义重选，不重新做来源判断，不改写已批准 binding。媒体记录缺失或文件不一致时 blocked，不以空海报代替。

**产物**：`09-visual-assets/asset-manifest.json`、`visual-track.mp4`、`segments/`、每镜头 manifest 与关键帧。

**验收**：正片是否精确复用样片，其余镜头是否符合同一批准系统。单镜头重试可通过 `artifact_scope` 强制重做指定段；已生成计划的修订按 [视觉修订合同](visual-revision-reuse.md) 比较输入并复用未变媒体。现有 DAG 仍会重置字幕、preview 和 delivery；媒体复用不代表这些阶段的批准自动保留。

### 10. `subtitles`

**输入**：已批准 content analysis、timeline map 和 visual track。

**执行**：`subtitles_v2.prepare_subtitles_v2(job)` 生成覆盖 A-roll 与有口播 B-roll 的唯一字幕计划与透明轨，实际视觉组件和时间轴适配按 [字幕样式合同](subtitle-style-contract.md) 调用 TalkCraft。B-roll 字幕位于圆窗上方，不能与画面内标题重叠或由子 Skill 重复烧录。每个 cue 保持简短；重点字只能是已批准精确关键词，不另加色块。若运行时仍调用旧 PIL 黄竖条样式，则当前字幕阶段未达到已确认标准，不可自动批准或进入正式预览。

**产物**：`10-subtitles/subtitle-plan.json`、`subtitles.webm`、`subtitles.srt`。不生成缩略图或联系表；字幕仍验真实透明轨、几何与时码。

**验收**：读速、分句、位置、艺术字与已批准关键词一致，不再做内容提炼。

报审前，在实际项目运行时执行只读入口（不重新生成字幕）：

```bash
PYTHONPATH="<project>" <python> -m edit.hd.tools.cli review-subtitles --job "<job-dir>"
```

将返回的 `revision`、`artifact` 与当前字幕产物一起报审，在原有“注意”栏展示 `terminology_review.doubts`：每项列出 `observed`、候选 `expected`、原因及 `source_range`。该范围是原口播源时间（秒），`word_indices` 是源转写词索引，不是剪后视频或带封面成片时码；核听原片对应范围，不能直接跳到成片同一秒数。

- `available` 且疑点为空：只表述“本轮规则未发现术语疑点”，不能宣称全文准确。规则只覆盖明确历史更正可能重现和批准术语的大小写变体，不是完整语义校对。
- 有疑点：结合本期原稿、原声上下文和历史更正来源核对；`expected` 只是检测候选，检测器不直接改字。确定为转写错误后，宿主按上面的文字校对接口自动处理，不再索取字词选择。原稿和实际口播含义不同不能只改字幕。同一旧词在不同上下文有不同更正目标时，保留各项，不合并为全局替换。
- `legacy_report_unavailable`：明确说明“旧字幕产物没有术语报告，未证明已检查”；不当作无疑点，不补写旧产物或重签批准。
- 命令失败或报告身份变化：停止报审，报告错误并重新核对当前 Job；不直接读取未经验证的 JSON 绕过检查，也不重新生成已批准资产来掩盖失败。

该检查并入当前字幕本地 QA，不增加独立确认。宿主发现或用户指出源转写错误时，沿已有 `speech_cleanup` 修订链处理；运行时更正入口为 `apply-cleanup-corrections --job <job-dir> --corrections <manifest>`，必须按当前运行时合同准备绑定源转写身份的更正 manifest，不把疑点 JSON 直接作为 manifest。源音视频中真实口吃或念错不能靠改文字修复，仍需清理阶段的精确剪点和核听。返回上游后按既有依赖重审，不沿用已失效的字幕批准。

### 11. `preview`

**输入**：已批准视觉资产、字幕和剪辑后 A-roll 音频。

**执行**：读取[默认制作配置](production-defaults.json)和[封面首镜合同](cover-opening-bgm.md)，确认首镜已在批准正文中调用 Wake；预览显式使用 `preview_v2.prepare_preview_v2(job, opening=None)`，不加静态前贴。原声、字幕和动效均从第 0 帧开始。以 A-roll 口播音频为主时钟，默认无背景音乐，不产生第二个口播音轨。检查实际首帧、首镜边界、画幅、转场、字幕和音画同步。

Wake 首镜属于正文，原声和导出 SRT 均不平移；不修改已批准正文结构。用户要求配乐时才向同一入口传 `music=...`；参数变化先修订 `preview`，重复调用不重渲染。音乐由正式预览混成单音轨，不单独修改最终 MP4。默认值不会改变或重渲已批准的历史 Job。

**产物**：`11-preview/review.mp4`、`qa-report.json`、`keyframes/`。关键帧保留视频原尺寸作为内部 QA，不缩小或拼成联系表，交付不复制缩略图。启用封面时还登记 `opening-manifest.json` 和偏移后的 `subtitles.srt`，缺任一项停止复用或交付。

**验收**：宿主审阅完整成片，结合原声、字幕和实际画面完成本地 QA；机器 PASS 不能代替这项审阅。通过后内部批准 `preview`，导出同字节交付包；不再请求用户确认样片、字幕、预览或成片。任何修改返回最小影响上游，不从头重做。

### 12. `delivery`

**输入**：已批准 preview 和它的 QA/哈希身份。

**执行**：`qa_delivery_v2.prepare_delivery_v2(job)` 将成片、封面、字幕、plans、QA、用户素材索引和所有必要 manifest 复制到不可变交付目录。不上传、不发布、不发消息。

**产物**：`12-delivery/final.mp4`、封面、字幕、`plans/`、`qa/`、`delivery-manifest.json`。

启用封面时交付 `opening-manifest.json`，SRT 与最终视频同一时钟；原透明字幕 WebM 改存 `plans/body-subtitles.webm`，明确仍为正文时钟。完成审计核对封面清单、最终字幕绑定、总时长和音轨，不因文件存在就认定偏移正确。

启用音乐时原样交付预览登记的音乐清单、音乐审计音频、许可原件和署名文本；成片与内部批准预览字节完全一致。自动响度检查和内部 QA 是交付门，用户确认的是此前完整视觉清单，不再另设成片确认。

**验收**：交付库与已批准 preview 身份一致，且引用当前视觉清单确认与宿主 QA。不得把进度要求、机器 PASS 或历史确认当成本次视觉计划批准。

### 视觉计划确认入口

报审时展示完整 `07-visual-direction/visual-routing.md`，保留入口返回的任务、revision 和完整 artifacts 身份。需要生图或生视频的镜头同时冻结独立 `07-visual-confirmation/rN-id/` 下的 director brief、treatment、routing 和 proposal；其中 `generation_plan.steps` 只描述步骤、依赖和真实渠道 action，不提前伪造生成结果。收到真实整表确认后，将这些字段与 `passed`、实际检查 `note`、`user_confirmation` 写入本次 QA JSON，格式见[阶段执行入口](stage-runner.md#宿主审阅后推进)：

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/run_stage.py --job-context <workspace>/job-context.json \
  --stage visual_direction --review-json <本次整表确认.json>
```

尖括号替换为当前任务值。入口先核对完整视觉表与实际计划，再保存 `manifests/local-qa-visual_direction-r<revision>.json`，自动记录 `reviewed_by=human` 和 `approval_scope=visual_plan_and_delivery`，并批准当前阶段。不能把新版本的文件身份套到旧确认上，也不能用裸 `state.approve` 代替这份整表确认。其他中间阶段沿用宿主 QA，不增加用户确认。

完成后重新读取状态；已批准的同一方案继续执行，不重复请求确认。确认后同一次 `visual_direction` 续做返回具体图片/视频提交与查询 actions；宿主按已确认渠道调用并回传 `generation_results`（含原 action、真实规范响应、必要 task IDs）。图片完成后，才构造引用真实图片的图生视频请求；生成完成后宿主按模板原生入口完成 binding 和实际语义 QA，回传 `realization`（director brief、treatment、可选 reviewed visual text、实际 host QA note），再进入原 V3/V2 编译、execution-mapping、canary 和交付。没有生成步骤的既有素材或完整模板直接编译，不重复生成。修订改变时间、语义、标签、模板或渠道时，更新整表后确认改变的方案；未变素材继续复用，不补写或替换历史确认。

### 宿主交付完成入口

宿主核对完整成片的画面、原声和字幕后，以同一阶段入口提交 `--stage delivery --review-json <本次交付QA.json>`。该 JSON 绑定实际任务、revision、完整 artifacts 和真实 QA note，不要求成片用户确认。入口调用 `delivery_approval.approve_plan_delivery`，复用原交付事务写入 `12-delivery/approval-receipt.json`：`approval_kind=plan_authorized`、`approved_by=host`，引用实际人工整表批准文件与当前成片/manifest 身份。整表确认原文只保留在视觉阶段，不复制成“用户已看过成片”。

相同交付请求的恢复沿用原锁、回执和 CAS；完成前先核对当前状态与身份，不重渲或伪造确认。旧 `formal_final` 人工成片确认回执保持其原有语义，不自动改签为新类型。

完成后调用 `scripts/audit_job_completion.py --workspace <workspace> --json`。当前整表批准、宿主交付回执、全部阶段、交付文件及实际媒体探测一致才返回 `formal_complete`；该状态表示已制作交付。检查只读，不补批准或修改媒体。

## 完成边界

- 维护回归必须覆盖真实十二阶段端到端以及批准后的转写返修，不能只测独立模块。`full-v2` 的素材使用回执属于正式阶段库存和返修 lineage，须连同业务文件核对身份；不得为兼容旧测试而删掉回执。正式视觉资产清单中的复用段 ID 与输入身份必须一起传递并验证，不能只更新生产端而遗漏 preview 消费端。

- `ready_for_review` 不是完成；任何机器 QA 或渲染成功不得越过人工门。
- 一个已批准阶段不因下游反复询问而重做；只在它自身的输入、绑定、字节或用户决策改变时形成 revision。
- 开始下一个新视频时必须新建独立 workspace，不复制上一 Job 的状态或 provider 连接状态。
- 终态用 `scripts/audit_job_completion.py` 做只读审计，只返回 `formal_complete` / `legacy_external_approval` / `incomplete` / `inconsistent`。新 Job 以当前十二阶段、交付媒体探测/哈希、人工整表确认及宿主交付回执闭环；旧人工成片回执仍按原语义核验。
