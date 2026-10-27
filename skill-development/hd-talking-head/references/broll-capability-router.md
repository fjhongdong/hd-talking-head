# B-roll 语义能力路由

本合同把 B-roll 定义为逐段语义决策：先判断这段口播需要什么视觉作用，再选择一种或多种来源完成该作用。它不把来源当成优先级或备用链。9 个参考项目的精确入口见 [B-roll 开源能力适配矩阵](open-source-adapter-matrix.md)。

## 1. 五类同级来源

候选统一记录为“渠道→模板→标签”。渠道优先、模板次之；适配资格字段只描述执行边界，不把原生 Skill 排除在模板选择之外。

本项目新计划默认排除自研 local-canonical、RelationMotion 和 SemanticState 候选，先充分匹配现成 Skill 的配方及真实组件；具体顺序与缺口处理见[生成型 B-roll 编排](generated-broll-skills.md)。下文登记优先级是资格比较，不要求把未选中的历史记录全部加入候选池，也不改变已批准镜头的来源。新制作不因缺口新增动效实现；批准前换语义合适的原生候选或保留 A-roll，批准后失败停当前 route 进入 revision。历史来源不追认、不迁移。

OpenFilm、Lemo 等已完整接入的原生创作 Skill 按各自接入合同进入同一选型池；仅选中具体模板时，读取并执行对应原生 Skill 制作本句专属页面。历史排除项不因此恢复；当前只输出整屏无声 B-roll，不进入 A-roll 贴片候选。

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

每段 mode 只能是 `none`、`single` 或 `hybrid`，即 `mode: none | single | hybrid`。五类同级；不设来源优先级，不设来源配额，不做跨类替换，也不因某类执行暂停就改写为另一类。`external_stock` 和 `ai_generated` 都是主动语义选择，与本地、官方和代码来源之间不是降级关系。

语义角色与素材来源分离：`semantic_role` 说明组件在画面中负责证明、解释、对比、过渡或氛围；`kind` 只说明素材如何取得与执行。同一 `semantic_role` 可由不同 kind 完成，但必须在 `visual_direction` 人工批准时已冻结，下游不得自行换类。

## 2. 运行边界

- 画布从设计阶段就是 1080×1920，当前 full-v2 的批准计划固定为 24fps；不先做横屏再裁切。
- 浏览器、Remotion、FFmpeg、生成服务和页面渲染串行，重型并发为 1。
- 参考项目按已批准 ShotRecipe 延迟加载；每个组件只有一个 executor，每个镜头只有一个最终 compositor。
- 所有素材先写入当前 Job 记录，再由 plan 引用；不把 Job 外会变化的路径当成正式资产。
- 内容真实性、官方来源、许可记录、账号连接和产物一致性依然由当前 Job 记录。

## 3. 从 VisualIntent 到 ShotRecipe v2

VisualIntent 只表达内容意图，不预设来源。正式字段以 `validate_visual_intent`、`validate_visual_strategy` 和 `validate_shot_recipe_v2` 为准，不使用旧版 `claim_type / creative / technical` 结构。

[完整 schema 示例](examples/schema-v2-example.json) 包含匹配的 intent、strategy、ShotRecipe 和头肩头像字段。该文件通过正式 schema 及头像参数校验，但其中的机构、网址、全零哈希和头像坐标只是结构测试数据，不是检测结果，不能直接渲染、报审或作为事实证据。生产时必须绑定当前 Job 的真实文件、来源、哈希和人物测量值。

常见对应关系：

- `composition.family`：单源为 `single_full_frame`，混合证据层为 `evidence_with_data_overlay`，无 B-roll 为 `no_broll`。
- `presenter_mode`：使用 `bottom_window / hidden / full_frame`，不写 `avatar`。
- `layer_role`：使用 `base / overlay / inset / annotation`，不写 `primary`。
- 代码组件的 `media_type` 为 `animation`；`overlay` 是层级或布局，不是媒体类型。
- `executor` 由编译器根据实际绑定产生，不能写笼统的 `dependency-skill`。
- renderer 名称须与实际已登记依赖一致；除 `Remotion` / `HyperFrames` 外，已有 `RelationMotion`、`SemanticState`，Paper 分层引擎使用 `PaperCollage`，Whiteboard 原生 SVG 分组入口使用 `Whiteboard`。后两者的调用边界见[生成型 B-roll 编排](generated-broll-skills.md)，不自动取得已验证模板身份，不能为通过校验借用别的引擎名称。

每个 component 的 `kind`、`semantic_role`、`layer_role`、`render_window`、`safe_zone`、执行程序和来源绑定都是显式字段。`mode=none` 没有 component，`mode=single` 恰好一个，`mode=hybrid` 至少两个，且组件通过 composition 明确空间、层级和时间关系。

## 4. 五类来源的绑定

| kind | 何时选择 | 必须写入 ShotRecipe 的记录 |
| --- | --- | --- |
| `local_material` | 用户已提供的图片、视频或文档与当前语义匹配 | `material_id`, `job_path`, `sha256` |
| `official_material` | 第一方图片、视频或页面记录能直接支持人物、机构或事实 | `source_id`, `publisher`, `source_url`, `snapshot_path`, `fetched_at`, `sha256` |
| `code_generated` | 数据、比较、时间线、流程、层级、关系图、界面演示或技术解释适合程序化表达 | `dependency_id`, `entrypoint`, `producer_version`, `brief_sha256`, `invocation_record`, renderer 字段 |
| `external_stock` | 真实场景、行为、地点或氛围由外部素材库更准确表达 | `provider`, `provider_asset_id`, `author`, `asset_page`, `job_path`, `license_snapshot`, `downloaded_at`, `sha256` |
| `ai_generated` | 当前语义本身适合生成式隐喻、氛围或无法直拍的概念画面 | `provider`, `model`, `endpoint_id`, `prompt_sha256`, `generation_id`, `sha256` |

`code_generated` 调用现有依赖 Skill。执行层按冻结的 `dependency_id / entrypoint / producer_version` 调用，并在 `invocation_record` 保留 Skill 调用证据。`external_stock` 必须保留许可记录；`ai_generated` 是主动语义选择，不是其他来源无法执行后的替代项。

复用已完成 Lovart 视频时，先由 `lovart_existing_video_adapter.prepare_existing_binding` 核验真实记录和媒体，再将返回值放入该组件的 `bindings`。编译器消费 `execution_mode=reuse_completed_lovart_video` 与实测 `source_dimensions`，产生固定复用入口和实际 720p/1080p 源尺寸，两项控制字段不进入 ShotRecipe；其他来源和无此模式的 AI 绑定不变。编译器不读 Job、不生成视频，也不接受手填 `executor / artifact_contract`。正常批准及执行时仍重新检查文件身份与媒体，完整顺序见[生成型 B-roll 编排](generated-broll-skills.md#lovart-已完成结果的原字节复用)。

## 5. 候选评估与记录

先按[统一动效能力库](motion-capability-library.md)理解具体入口并检索，不提前指定熟悉的 Skill。`discover` 的 `capability` 是我们自己的语义／动作／视觉档案，带证据与已审阅版本；它不改变原有 `status` 或模板资格。贴片与 B-roll 可在同一库中比较表现方式，但最终仍分流到各自用途和校验，不因关键词、画风或标签命中就放行。相关未接通项保留为缺口，不假装可执行。

五类候选可并行准备，但最终只由语义决策。每个候选记录 `asset_id`、`kind`、`semantic_match_score`、`quality_score` 和内容真实性、原生竖屏、画质可读性、来源记录等检查结果。缺少必需字段时返回明确停止状态，不由脚本补猜。

未选候选保留中性原因，例如：语义不匹配、人物或事实记录不完整、可读性不足、尺寸不合适或邻近镜头已重复。这些原因只说明本次语义决策，不形成来源排名。

## 6. `code_generated` 内部的模板验证与优先级

五类来源同级不变：下面的顺序只在 `visual_direction` 已经批准 `kind=code_generated` 后生效，不能据此让代码海报替代本地资料、官方资料、外部素材或 AI 画面。

进入模板候选池前，先运行 `scripts/verify_broll_template.py` 验证 `references/verified-template-registry.json`。只有源码、样片、1080×1920 媒体参数、哈希和进入/稳定/退出三帧视觉记录全部通过的项目，才具有 `template_origin=verified_third_party` 或 `verified_local_canonical`。路由器先按 `semantic_match_score`、再按 `quality_score` 排序，同分才比较 `template_origin`，最后比较 `reuse_gap`；不得直接相信来源仓库自己的“支持 9:16”声明。

登记还强制包含 `execution_qa`：两组不同内容的原始 brief、冻结配方、真实执行回执、MP4 和三态 PNG。验证器核对完整输入/来源身份、真实媒体参数、PNG 与 MP4 对应帧的 RGB 像素，以及两组稳定画面的差异。新增或维护模板时必须阅读 [双输入实测资格](template-qualification.md)，不得只靠一份旧样片或自填成功字段。资格实验可复用未变化的真实证据，不要求新 Job 重复测试；当前文案的 canary 仍保留。

整屏资格及数量读取当前 `verified-template-registry.json`，不在文档维护另一份活动清单。登记覆盖 DataRollup、Notification Cascade、Huashu 三种原生场景，以及保留证据的本地 canonical、RelationMotion 与 SemanticState；历史登记不等于新制作候选。新计划仍排除自研入口。ChatGPT Exchange 因正文和表格裁字已退出活动资格，历史合同和样片不使它重新入选，也不影响独立的 `chat-message` 原生组件。

Huashu 功能卡只匹配 `product_features` 的恰好三项，不泛化为截图、数字或教学步骤。Notification Cascade 只匹配恰好四个顺序节点并收束为结论的通知语义；它与 A-roll 的 `notification-stack` 是不同入口，不能一起排除。本地 `evidence-source` 保留真实图片与真实视频证据；关系图、时间线与语义动效的历史动作顺序和批准内容约束仍保留。不能因 renderer 名称相同而扩大到任意流程图、对比海报或官方资料卡。

五类 SemanticState 的语义边界固定：`replacement` 表达对象替换且保留上下文，`threshold` 表达阈值被跨越或标准上移，`delay` 表达触发到显现之间的时滞，`hierarchy` 表达两到四层层级展开，`feedback` 表达输出返回并改变后续状态。只能按已批准内容的真实关系选择，不得为了使用新模板把普通并列、泛化观点或无因果文案改写成这些结构。

声明输入 schema 不等于实际参数绑定：源码或登记 adapter 必须真实消费当前文案、数据、颜色和时长变量，并由两组不同测试输入证明输出随输入变化。只有能在 1080×1920 中独立完成整屏构图、信息层级和三态动效的入口才具有整屏模板资格；单个横向 UI 卡片、图表或动效 primitive 即使响应式可渲染，也只是可组合组件。组件可复用不等于 `verified_third_party`；把它重新排成竖屏海报属于 `structural` 组合，必须记为 `custom_fallback`。

通过语义家族、容量及结构合同硬门后，先比较 `semantic_match_score`，再比较 `quality_score`；两分相同时，资格顺序才是：

1. `verified_third_party`
2. `verified_local_canonical`
3. `custom_fallback`

资格不能覆盖语义或美观质量，资格相同才比较 `reuse_gap`。`verified_third_party` 的 `adaptation_level=structural` 修改立即失去验证身份，只能作为 `custom_fallback` 重新走样片和批准门；`verified_local_canonical` 可按已登记的自有结构合同使用 `structural`。固定结构内替换已批准文案/数据可使用 `tokens_only` 或 `content_reflow`。ShotRecipe 必须冻结 `template_origin`、`template_id`、`template_version`、`verification_id`、`adaptation_level`、`source_entrypoint`、源码/样片 SHA-256、`semantic_families` 和 `capacity`。

容量是已验证模板的硬门：不得为当前文案临时降低 `capacity`，也不得用无意义数字、空卡片或重复文案凑数。在 ShotRecipe 批准前的候选验证中，容量不匹配或当前文案三态 QA 失败时，排除该模板并在 `code_generated` 候选池内继续排名；不跨来源类别。

模板历史验证不能代替当前文案三态 QA。每次实际填充后仍检查进入完成帧、稳定帧和退出前帧的文字越界、元素重叠、空占位、装饰依附、信息密度与末帧跳动。ShotRecipe 一旦批准，任一失败就停在当前模板并进入 revision，不在执行阶段静默换模板或换来源类别。

### 当前内容必须跟随冻结绑定

每个代码绑定的 `invocation_record` 必须包含以下 `template_request`，与实际送给 renderer 的 brief 同时冻结。这里是字段示例，不是本期视频文案：

```json
{"semantic_family":"bar_chart","information_units":3,"numeric_values":[2,5,9],"numeric_scale":"linear"}
```

- `semantic_family` 必须在冻结模板的 `semantic_families` 中。
- `information_units` 是真实内容单元数量，必须在原模板 `capacity` 内；不能临时改容量或补空节点。候选请求与冻结请求不一致会失败。
- `numeric_values` 按实际输入顺序保留原值，无数字则为 `[]`；拒绝布尔值、NaN 和无穷大。`numeric_scale` 只能为 `linear / log / not_applicable`，有数字不能填 `not_applicable`。
- 当前登记的 `html-video/frame-data-rollup` 原源码会取整，并在正数最大/最小值达到 50 倍时自动改为对数高度。此版本只允许非负、安全整数、线性比例，数字数量等于单元数量；小数、负数或触发自动对数的数据直接拒绝，不替用户改数字。带“超过”“约”等限定语仍必须在实际画面原样表达；当前数值门不证明这些措辞已正确渲染。
- `compile_strategy` 与正式 `execute_component` 使用同一主包检查。缺 `template_request` 的旧绑定明确报错，需受控修订；不沿用旧批准自动补字段。
- 这些检查验证声明的内容与模板资格，不能替代“renderer 实际消费这些参数”的双输入渲染证明，以及当前文案的人工语义审核。

### 历史样片与当前输出分开验收

`verify_broll_template.py` 对历史样片设置 20 秒 FFprobe 超时，并检查 1080×1920、SAR 1:1、DAR 9:16、零显示旋转、有限正帧率与视频轨时长。不能只按编码宽高判断竖屏；旋转矩阵或旧式 rotate 标签非零同样拒绝。三态时间必须满足 `entry < stable < exit < 视频轨结束`；有视频轨时长时不采用容器的音频尾部 padding。

历史 30fps 样片可作为历史验证记录，但本次输出必须另跑：

```bash
<python> <skill>/scripts/verify_broll_template.py \
  --production-video <当前渲染文件绝对路径> --expected-frames <本段批准帧数> --json
```

当前输出必须为 24fps，真实帧数与批准 render window 一致；其他输出帧率不进入当前 full-v2 计划。此命令只证明媒体参数，不证明文案、美观、动效顺序或当前三态 QA 已通过，也不能代替正式 executor 的执行证据。

## 7. 能力注册表

| 项目 | 注册角色 | 直接使用方式 |
| --- | --- | --- |
| `html-video` | 内容图与 HTML 视频编排 | 把结构化信息和时间片转为可组合场景 |
| `erduo-broll-loop-engineering` | 内容真实性/创意分流与 canary 闭环 | 复用事实/创意分流、代表样片和迭代门 |
| `video-use` | 音频主时钟、FFmpeg 合成与边界 QA | 负责帧级时长、无缝出入、音画同步和媒体验证 |
| `video-autopilot-kit` | 素材评分、疲劳控制与语义 QA | 对候选素材、重复度和信息密度评分 |
| `HyperFrames` | HTML/GSAP/D3/Three 动态信息视觉 | 透明贴片、图表、关系图、时间线和轻量 3D |
| `Remotion` | React 帧级组合与 2.5D/UI 动画 | 多层海报、界面演示、程序化排版和可重复渲染 |
| `OpenMontage` | provider/renderer 能力路由与 Atelier | 复用 capability registry、决策日志和英雄镜头 Atelier |
| `Generative-Media-Skills` | 生图/生视频提示词与 provider 适配 | 在已批准生成路线内编译提示词和调用服务 |
| `Open-Generative-AI` | 多模型能力目录与异步生成 DAG | 查询模型输入能力、生成约束和任务状态 |

## 8. 构图、动效和样片

需要显式规划动作依赖时读取 [语义动效规划接口](semantic-motion.md)。已登记的 `hd-talking-head/relation-motion` 和五类 SemanticState 会消费已冻结的 `semantic_motion`，并以独立 adapter、正式 executor、真实双输入执行证据、逐态像素、动作顺序记录与人工批准样片证明登记资格。普通 Job 仍必须 fail closed：模板身份、family、容量、当前批准内容、当前实际填充三态 QA 或 canary 任一不通过，就不得选用或声称已执行。

先分别完成贴片语义列表和 B-roll 语义列表，再对每项做一次完整候选匹配；所有合格候选保留到统一分配阶段。每项统一记录渠道、渠道内模板和标签。整片联合分配先精确最大化真实来源渠道数量，再在该前提下最大化具体模板数量；同一来源的不同 adapter 或别名只算一个渠道，临时内容沿用所选模板身份。`preferred` 只记录局部优势，不能删除合格 `equivalent`；缺素材、待准备或待授权是执行状态，不是语义 `unsuitable`。时间覆盖和可读性放到分配完成后校验，不能先按时长定条数；整片分工冻结后才生成 ShotRecipe。

冻结全片计划前，先在当前 Job 保存逐镜分配表：时窗、当前原声所表达的变化、第一轮列出的上游 Skill/具体入口候选、第二轮确定的整片分工、画面家族、主体动作，以及可执行/待适配/待费用授权状态。同时盘点将复用的旧镜头；不能只比较本轮重做镜头，忽略它们与前后已批准素材的重复。分配表在整片协调完成前是制作草案；协调结果冻结后才生成已执行的 ShotRecipe。

### 唯一选型入口与记录

通过项目已准备的 `project_python.py` 调用 `<skill>/scripts/select_broll_skills.py`：`discover --project-root <project>` 读取现有 adapter 的原生入口及 qualified 卡片；`assign --project-root <project> --treatment <Job内treatment.json>` 完成两轮分配；`check --project-root <project> --treatment <同一文件> --director-brief <草案>` 检查实际接法。发现不安装、不渲染、不调用生成服务；实际执行仍服从原预检、配方及费用门。

三个命令使用同一候选池。依赖整屏资格登记的入口须仍在活动 registry 中；原生组合组件按自身接法与用途进入，不冒认整屏资格。HyperFrames 通用适配器只将 `macos-notification`、`chat-message`、`screen-flow-carousel`、`beat-timeline` 列为完整 B-roll 场景。A-roll 的五种透明贴片仍走独立合同，不因技术渲染器支持就进入 B-roll；只有参数常量或未完成时间轴的入口也不入选。这是当前接法边界，不是永久否定上游组件。发现结果只证明候选入口存在，不证明本句语义、美观、运行环境或费用已通过。

在现有 treatment JSON 中维护 `skill_selection`，不另建审批文件或扩展最终计划 schema：

- `schema_version: 1`；`history_note` 如实说明最近两条成片可查到什么，缺历史时不得填成“没有重复”。
- `beats` 每条对应一个代码/AI B-roll 的 `segment_id/component_id/start/end`，包含 `transcript`、`semantic_goal`、`required_change`。新增与复用镜头均在同一表。
- 每条 `skill_reviews` 按 `discover` 的全部 `skill_id` 记录 `fit/reason`。`fit` 为 `preferred/equivalent/unsuitable/needs_adapter`。先看完整能力池，不逐个复制所有卡片，也不拿“没有适配器”冒充语义不合适。
- 每条 `candidates` 只列相关的具体 `candidate_id/fit/reason/visual_pattern`。主控先审阅语义、中文容量、原生动作、画幅、时长与美观；只有确实相当的方案才放入同档组。`visual_pattern` 使用主控统一的主体组织、构图和动作标签，例如“资料分组后汇聚”，不能以 Skill 名、色板或模板编号命名；换道具、换色或换 Skill 而动作相同，仍用同一标签，不能靠不同字符串假装不同画面。
- `preferred` 表示有明确理由优先的一档，但不能裁剪合格 `equivalent`。`assign` 必须在完整候选池中统一协调，先最大化真实渠道，再最大化具体模板；没有合格替代时才保留唯一候选。别名去重，自创场景不冒充新增模板；语义和质量合格才进入比较，不强求不适用来源出现。
- `recent_context` 保存最近两条成片的 `video_id/source_ref/skill_id/visual_pattern/start/end`；依据实际制作记录和画面填写，不凭旧 Job 名称猜测。`fixed_context` 用同样的模式信息记录本期已选资料类 B-roll，另含 `segment_id/component_id`，让这些画面也参与整片协调。资料来源的 `skill_id` 可记实际资料类型，不伪称动画 Skill。
- `assignments` 是命令输出，不手填。按结果实际调用所选 factory 构造原有 binding，随后将每条最终的 `intent_statement`、`component_brief` 与完整 `binding_snapshot` 写回对应 beat。文案、字号、布局或 brief 字节变更后，先调用同一 factory 重建 binding，再同步 director 与该 beat 的完整快照并重新运行选型；不能只改 brief 路径或单个哈希。launcher、reference sample 与 template_request 均取真实 factory 返回值，不从另一模板或旧样片手拼。后续生成才产生的结果仍按既有资产机制绑定；选型记录不能冒充已经实际调用。

正式 `prepare_visual_direction(..., treatment_path=...)` 在任何冻结器和发布动作之前重新发现、复算、核对当前草案；编译后继续检查冻结绑定和实际配方没有偏离。记录与结果一起写入已有 `visual-routing.md`，下游仍只执行冻结配方。A-roll 贴片仍走自身合同，不混算为 B-roll；已完成产物不读取新选型记录、不迁移旧 Job。

Flat/GBRO 的完整创作流程各自是渠道，已有工作流入口各自是模板；设计、静帧、动画生成和 QA 按原生流程完成。Lovart 等实际生成服务保留在底层执行绑定中，不替代创作渠道，也不额外计渠道，不将生成结果冒充本地代码渲染。Paper 的通用 HyperFrames 文档路线没有可直接调用的完整原生场景时，标为待适配，不能借 renderer 自写动效后声称原生接通。

充分利用是按适用场景展开候选池，而不是每个 Skill 强制用一次：数值变化匹配数字/图表卡，时间跨度匹配时间线，对照匹配分屏或状态切换，真实操作匹配资料或界面演示，具体对象的组装/替换匹配 Paper 或拼贴，分类/层级才匹配导图，人物行为匹配真实视频或获批 Lovart 动态。Flat、GBRO 的静帧方案与实际动画生成分别记账；不能用显现动效代替人物动作。

复核相邻 B-roll 的主体、构图和动作，而不是只看 dependency_id：换颜色、换字或换 Skill 但仍是一排方框连线，按同一种画面处理。连续重复时先在语义合格的候选中调整；确实需要同一结构时记录理由，不为了轮换编造数字或改变论点。Doudou 不作全部抽象句的默认入口。质量相近时优先尚未使用或间隔较长的合格能力；没有本句所需容量/动作/时长的入口标出具体缺口，不假装全部接通。

关系图类 B-roll 的进入顺序由语义方向决定：来源节点先出现，全部来源节点稳定后输入关系随后建立；汇聚节点只在输入完成后出现，并且最多做一次轻微回弹；独立输出关系完成后才展示结论，底部总结最后出现。ShotRecipe 必须分别绑定 `sources`、`hub`、`target` 和 `payoff`，结论或底部总结不得回填成来源节点；字段已声明但为空表示该角色不渲染，不得再从旧文案回填，连线仅在起点和终点都存在时创建。不足预设节点数时只画真实节点和连线，不生成空占位。SVG 路径的显隐、进度和输出阶段必须由渲染主时钟显式驱动，不只依赖 CSS `animation-delay`；代表样片至少抽查“节点全显但尚无线”、“输入线绘制中”、“汇聚出现”、“输出线绘制中”和“结论已显示”五个时态。

`visual_canary` 使用真实长片段落与正式 executor，总时长不超过 30 秒。它只执行已批准 ShotRecipe v2，不重新决定 kind、semantic_role、binding 或 composition。批准 canary 在 `visual_assets` 以相同 SHA-256 字节复用；其余段落执行各自已冻结配方。

正式合成和后续 revision 都必须让替换素材覆盖整个已批准语义区间，或者覆盖 ShotRecipe 中明确声明并经批准的完整 phase。不得只覆盖动画镜头的前半段，再让已经完成入场动画的底层末态重新露出。素材时长与 `render_window` 不一致时，先在配方层重新计时、循环内部可循环动作或重做素材，并重新做三态 QA；禁止依靠 `repeatlast`、临时缩短 overlay 或中途揭回底层画面补足时长。revision 不得绕过已批准 ShotRecipe 直接拼接。

每个 B-roll 都检查进入、稳定、退出三态的文字溢出、元素重叠、头肩裁切、信息密度、`safe_zone` 和最后 8–12 帧连续性。最终 manifest 保存 VisualIntent、ShotRecipe v2、来源绑定、执行记录、素材哈希、选择原因、批准 revision 和 QA 结果。
