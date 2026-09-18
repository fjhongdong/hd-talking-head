# B-roll 语义能力路由

本合同把 B-roll 定义为逐段语义决策：先判断这段口播需要什么视觉作用，再选择一种或多种来源完成该作用。它不把来源当成优先级或备用链。10 个参考项目的精确入口见 [B-roll 开源能力适配矩阵](open-source-adapter-matrix.md)。

## 1. 五类同级来源

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

- 画布从设计阶段就是 1080×1920/24fps，不先做横屏再裁切。
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
- renderer 名称严格使用 `Remotion` 或 `HyperFrames`，并与登记模板的实际引擎一致。

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

## 5. 候选评估与记录

五类候选可并行准备，但最终只由语义决策。每个候选记录 `asset_id`、`kind`、`semantic_match_score`、`quality_score` 和内容真实性、原生竖屏、画质可读性、来源记录等检查结果。缺少必需字段时返回明确停止状态，不由脚本补猜。

未选候选保留中性原因，例如：语义不匹配、人物或事实记录不完整、可读性不足、尺寸不合适或邻近镜头已重复。这些原因只说明本次语义决策，不形成来源排名。

## 6. `code_generated` 内部的模板验证与优先级

五类来源同级不变：下面的顺序只在 `visual_direction` 已经批准 `kind=code_generated` 后生效，不能据此让代码海报替代本地资料、官方资料、外部素材或 AI 画面。

进入模板候选池前，先运行 `scripts/verify_broll_template.py` 验证 `references/verified-template-registry.json`。只有源码、样片、1080×1920 媒体参数、哈希和进入/稳定/退出三帧视觉记录全部通过的项目，才具有 `template_origin=verified_third_party` 或 `verified_local_canonical`。路由器使用 `candidate_from_verified_template_record` 把已验证记录与当前文案的 `semantic_match_score`、`quality_score`、`reuse_gap` 结合；不得直接相信来源仓库自己的“支持 9:16”声明。

登记还强制包含 `execution_qa`：两组不同内容的原始 brief、冻结配方、真实执行回执、MP4 和三态 PNG。验证器核对完整输入/来源身份、真实媒体参数、PNG 与 MP4 对应帧的 RGB 像素，以及两组稳定画面的差异。新增或维护模板时必须阅读 [双输入实测资格](template-qualification.md)，不得只靠一份旧样片或自填成功字段。资格实验可复用未变化的真实证据，不要求新 Job 重复测试；当前文案的 canary 仍保留。

当前已验证整屏记录共 14 条：`html-video/frame-data-rollup`、`hyperframes/notification-cascade`、`hyperframes/chatgpt-exchange`，本地 canonical 的 `process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword`，`hd-talking-head/relation-motion`，以及五套 SemanticState：`semantic-state-replacement`、`semantic-state-threshold`、`semantic-state-delay`、`semantic-state-hierarchy`、`semantic-state-feedback`。`evidence-source` 支持真实图片或真实视频；关系图、时间线和六类原生语义动效记录携带对应 `action_sequence_qa`。RelationMotion 与 SemanticState 还必须绑定当前批准内容和完整 `semantic_motion`。Notification Cascade 只匹配恰好四个顺序节点并收束为结论的通知语义；ChatGPT Exchange 只匹配 `ai_dialogue_comparison`、`four_factor_comparison`、`prompt_to_table`，要求恰好四项、无数值序列，并保留固定聊天界面。不能因 renderer 名称相同而扩大到任意流程图、对比海报或官方资料卡。

五类 SemanticState 的语义边界固定：`replacement` 表达对象替换且保留上下文，`threshold` 表达阈值被跨越或标准上移，`delay` 表达触发到显现之间的时滞，`hierarchy` 表达两到四层层级展开，`feedback` 表达输出返回并改变后续状态。只能按已批准内容的真实关系选择，不得为了使用新模板把普通并列、泛化观点或无因果文案改写成这些结构。

声明输入 schema 不等于实际参数绑定：源码或登记 adapter 必须真实消费当前文案、数据、颜色和时长变量，并由两组不同测试输入证明输出随输入变化。只有能在 1080×1920 中独立完成整屏构图、信息层级和三态动效的入口才具有整屏模板资格；单个横向 UI 卡片、图表或动效 primitive 即使响应式可渲染，也只是可组合组件。组件可复用不等于 `verified_third_party`；把它重新排成竖屏海报属于 `structural` 组合，必须记为 `custom_fallback`。

通过当前语义家族、信息容量及相应来源的已登记结构合同后，固定顺序为：

1. `verified_third_party`
2. `verified_local_canonical`
3. `custom_fallback`

存在合格 `verified_third_party` 时不得选择后两级。`verified_third_party` 的 `adaptation_level=structural` 修改立即失去验证身份，只能作为 `custom_fallback` 重新走样片和人工批准；`verified_local_canonical` 可按已登记的自有结构合同使用 `structural`。固定结构内替换已批准文案/数据可使用 `tokens_only` 或 `content_reflow`。ShotRecipe 必须冻结 `template_origin`、`template_id`、`template_version`、`verification_id`、`adaptation_level`、`source_entrypoint`、源码/样片 SHA-256、`semantic_families` 和 `capacity`。

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

当前输出必须为 24fps，真实帧数与批准 render window 一致。此命令只证明媒体参数，不证明文案、美观、动效顺序或当前三态 QA 已通过，也不能代替正式 executor 的执行证据。

## 7. 能力注册表

| 项目 | 注册角色 | 直接使用方式 |
| --- | --- | --- |
| `html-video` | 内容图与 HTML 视频编排 | 把结构化信息和时间片转为可组合场景 |
| `video-shotcraft` | 镜头配方与 2.5D 动效语法 | 执行 shot recipe、页面截图、镜头推进和节奏组织 |
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

多样性来自语义关系、构图家族、进入方式和节奏，不是随机换模板。相邻镜头避免机械复用同一构图家族；来源组合始终由当前语义决定，不设窗口数量或类型占比要求。只有信息结构匹配时才选 poster family，不为轮换牺牲语义准确性。

关系图类 B-roll 的进入顺序由语义方向决定：来源节点先出现，全部来源节点稳定后输入关系随后建立；汇聚节点只在输入完成后出现，并且最多做一次轻微回弹；独立输出关系完成后才展示结论，底部总结最后出现。ShotRecipe 必须分别绑定 `sources`、`hub`、`target` 和 `payoff`，结论或底部总结不得回填成来源节点；字段已声明但为空表示该角色不渲染，不得再从旧文案回填，连线仅在起点和终点都存在时创建。不足预设节点数时只画真实节点和连线，不生成空占位。SVG 路径的显隐、进度和输出阶段必须由渲染主时钟显式驱动，不只依赖 CSS `animation-delay`；代表样片至少抽查“节点全显但尚无线”、“输入线绘制中”、“汇聚出现”、“输出线绘制中”和“结论已显示”五个时态。

`visual_canary` 使用真实长片段落与正式 executor，总时长不超过 30 秒。它只执行已批准 ShotRecipe v2，不重新决定 kind、semantic_role、binding 或 composition。批准 canary 在 `visual_assets` 以相同 SHA-256 字节复用；其余段落执行各自已冻结配方。

正式合成和后续 revision 都必须让替换素材覆盖整个已批准语义区间，或者覆盖 ShotRecipe 中明确声明并经批准的完整 phase。不得只覆盖动画镜头的前半段，再让已经完成入场动画的底层末态重新露出。素材时长与 `render_window` 不一致时，先在配方层重新计时、循环内部可循环动作或重做素材，并重新做三态 QA；禁止依靠 `repeatlast`、临时缩短 overlay 或中途揭回底层画面补足时长。revision 不得绕过已批准 ShotRecipe 直接拼接。

每个 B-roll 都检查进入、稳定、退出三态的文字溢出、元素重叠、头肩裁切、信息密度、`safe_zone` 和最后 8–12 帧连续性。最终 manifest 保存 VisualIntent、ShotRecipe v2、来源绑定、执行记录、素材哈希、选择原因、批准 revision 和 QA 结果。
