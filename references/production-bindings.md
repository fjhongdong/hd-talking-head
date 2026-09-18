# 正式生产绑定

本文件登记当前仓库可验证的正式视觉身份。确认样片就是正式模板，不是“风格接近即可”的参考；任何字体、文案、构图、头像、动效、模型或证据变化都不得静默修改，必须形成 revision 并重新报审。

## 当前模板与本期样片

唯一模板身份来源是 [当前模板注册表](verified-template-registry.json)，使用前按 [双输入实测资格](template-qualification.md) 校验。可验证模板数量与入口读取注册表，不从旧评审板、旧家族目录或参考仓库数量推断。

本期实际使用的模板、字体、文案、头像与动效以当前 Job 已批准的 ShotRecipe 和 canary 为准。历史五镜头样片及评审板仅属于原任务的设计证据，不是新视频的固定文案、统一时长或替代模板，不从外部 Downloads 目录回填。

自定义家族由当前路由器与 renderer 提供，但只有注册表通过验证的入口才能宣称已验证；自定义模板仍需当前内容的三态检查及人工样片确认。

## 文案与字体锁定

- 所有可见文案必须来自已批准口播稿、已批准 `visual-plan.json` 的 `exact_text` / `exact_numbers` / keywords、已绑定官方资料，或已经单独批准的 editorial payoff；不得擅自改写观点、数字、因果关系或结论。
- 当前镜头的标题、数字、结论和来源必须与本期已批准的配方逐字一致；最终上屏字符串写入 plan 和 manifest，再以哈希绑定。不把历史样片文案复制到新任务。
- 内部语义字段不得上屏，包括“主题”“结论”“关键值”“提问”“反馈”“对照”等生成器角色名，除非它本身就是用户批准的文案。
- 每个模板必须绑定字体族、字体文件或系统字体身份、字重、字号、行距、字距和回退顺序。canonical 基线使用 PingFang SC、Songti SC、SF Mono；正式模板允许已登记的 Hiragino Sans GB 与 STSong 回退。
- 缺少已绑定字体时必须 blocked，不得静默替换字体。更换字体、字重、字号或行距属于视觉 revision，必须重新生成 contact sheet 报审。
- 文本测量发生在渲染前和渲染后；任何溢出、被裁半、强制缩成不可读字号或与头像/其他文案重叠都判失败。

## 官方资料与命名人物绑定

- 官方资料的 `product_page`、`image` 和 `video` 分别冻结真实来源，使用当前语义路由、ShotRecipe 校验和 `broll_systems.validate_composition` 验证组合；媒体执行再由 `broll_media.py` 核对实际内容，不调用已退役的旧路由接口。
- 文案出现命名人物及职务时，对应事实组件绑定第一方官方视频或官方人物页图片。姓名、职务、publisher、URL、访问时间、媒体类型、路径、字节数与 SHA-256 必须写入来源记录。
- 口播明确强调 CEO、创始人、研究者等职务时，姓名和职务必须进入已批准可见文案，或由紧邻的官方视频标题卡可靠呈现；不得只有人物图而丢失身份信息。
- 官方图片和官方视频分别进入 plan、manifest 与三态 QA；存在一种媒体不能代替对另一种已批准媒体的绑定和验收。
- 完整执行次序与失败分类见 [视觉资产前置检查](visual-assets-preflight.md)。

## 条件 B-roll 依赖绑定

- 代码组件只能使用正式 VisualPlan v3 内 ShotRecipe v2 冻结的 `dependency_id / entrypoint / producer_version`。预检先调用正式计划与配方 validator；不完整字段、identity 不一致或非法 component 不进入依赖绑定。
- `code_generated` 调用现有依赖：`html-video`、`hyperframes` 与 `hd-talking-head-local-canonical` 通过 `ReferenceProcessAdapter` 使用登记模板的实际引擎，`video-shotcraft` 通过 `SkillInvocationAdapter` 调用 Remotion。模板引擎不能仅由仓库名推断。执行层把组件交给 `broll_component_executor.execute_component`，产物必须保留真实调用证据。通过绑定检查不等于 adapter 已完成两组真实渲染验证。
- `hd-talking-head-talkcraft` 通过 `ReferenceProcessAdapter` 执行项目内锁定的 Remotion 运行时。自动选卡在 `visual_direction` 上游调用 `edit.hd.tools.talkcraft_matcher.match_cards`：108 张 qualified 卡全部进入语义检索池，先按 `production_role`、必需媒体和人物要求做硬过滤，再根据口播、语义家族、目标和关键词稳定排序。`build_binding` 把选中的 `hd-talking-head/talkcraft/<card_id>` 和当前 brief 身份冻结进 ShotRecipe；adapter 与 executor 不得二次选卡。语义索引只是检索数据，真实准入仍以项目 `runtime/card-registry.json` 为准。每个新 Job 先运行项目的 `edit/hd/integrations/talkcraft/check_runtime.py`；上游共享 runtime 与正式资格 runtime 隔离，不自动升级正式版本。Workbench 只通过 `build_v4_edit_contract` / `apply_v4_overrides` 产生未批准 draft bundle，修改后重新走 canary 与人工门。
- 五类来源同级；仅在已经批准 `code_generated` 的组件内，验证器输出按 `verified_third_party` → `verified_local_canonical` → `custom_fallback` 排序。当前 8 条正式记录位于 `references/verified-template-registry.json`，执行前必须通过 `scripts/verify_broll_template.py`，再由 `candidate_from_verified_template_record` 添加当前文案分数。
- `html-video/frame-data-rollup` 的原生接口见 [DataRollup 执行合同](data-rollup-execution.md)。`scripts/data_rollup_adapter.py` 创建正式 ReferenceProcessAdapter 与真实媒体探测器；`scripts/render_data_rollup.cjs` 消费当前 brief，保留原始第三方动画。其他 family 不因该接口存在就被认定已经执行验证。
- `hyperframes/notification-cascade` 的原生接口见 [Notification Cascade 执行合同](hyperframes-notification-execution.md)。`scripts/hyperframes_notification_adapter.py` 创建正式 ReferenceProcessAdapter 与真实媒体探测器；`scripts/render_hyperframes_notification.cjs` 使用固定四节点原生时间轴并调用真实 HyperFrames CLI。
- `hyperframes/chatgpt-exchange` 的原生接口见 [ChatGPT Exchange 执行合同](hyperframes-chatgpt-exchange-execution.md)。`scripts/hyperframes_chatgpt_exchange_adapter.py` 创建正式 ReferenceProcessAdapter 与真实媒体探测器；`scripts/render_hyperframes_chatgpt_exchange.cjs` 消费 22 个显式内容字段，使用固定四行问答对照时间轴并调用真实 HyperFrames CLI。
- `hd-talking-head-local-canonical` 的入口为 `scripts/local_canonical_adapter.py`，执行 `scripts/local_canonical_renderer.cjs`。它提供 `process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword` 五个原生 9:16 构图；每个入口都必须匹配 registry 的源码哈希、版本、双输入回执和当前运行时固定。
- 每个代码组件必须冻结 `template_origin / template_id / template_version / verification_id / adaptation_level / source_entrypoint / source_sha256 / sample_sha256 / semantic_families / capacity`。`structural` 改造不得沿用第三方验证身份；实际填充后必须重新做当前文案三态 QA，不能拿历史样片直接交付。
- 只发现 Skill 名称或参考项目目录不代表已经绑定。当前配方选中 `html-video`、`hyperframes`、`hd-talking-head-local-canonical` 或 `video-shotcraft` 后，manifest 中必须存在精确匹配 entrypoint 与 producer version 的可执行 binding probe；probe 返回的 `dependency_id / entrypoint / producer_version / adapter_identity` 必须与批准配方及登记逐字一致，才能返回 `selected + callable + bound`。HyperFrames 及其支撑的本地 canonical probe 还复核固定运行时提交、CLI 版本、渲染入口与模板包装器。
- Node.js 与 npm 静态 `required: false`，只要当前批准配方包含任一 `code_generated` 组件，就提升为 `selected + callable`。
- Pexels 与 Pixabay 静态 `required: false`。`visual_direction` 草案按语义选中对应 `external_stock.provider` 后，必须在首次搜索前复核当前 Job 的 `selected + connected`；实际素材冻结后，再用完整 ShotRecipe v2 复核 binding。
- `external_stock` 还必须保留 provider 素材 ID、作者、素材页与许可记录。这些状态只说明已选配方能否执行，不改变五类来源的语义选择，也不触发跨类替换。完整字段和命令见 [依赖预检、确认与安装合同](dependency-preflight.md)。

## 头像、音画和安全区

- 头像统一采用 `head-shoulders`：脸宽占头像 0.38–0.52，肩宽至少 0.68，头顶留白 0.06–0.11；完整保留下巴、颈部和肩线，不能只剩头部。
- 头像使用同一时间轴 A-roll 的独立裁切分支，不对全屏主画面做二次缩放。共享合成器读取 `composition.avatar`，不使用历史固定裁切；字段、测量与验证入口见 [头肩头像合同](avatar-profile.md)。进入后、稳定段和退出前各抽一帧验证上述比例，移动与转头区间需要额外检查。
- A-roll、头像与口播音频的最大音画误差为 2 帧；每个剪点抽查前后至少各两帧。不得用复制末帧掩盖同步或跳动问题。
- `soft-safe 边界为 y=1700`：critical text 和头像必须在其上方结束。`hard-safe 边界为 y=1800`：非 AI 主视觉和装饰不得越过。
- 220px 不是固定底部留白，而是从 y=1700 到画布底部的 soft 风险区；媒体背景可延伸。底部 120px 是 hard 风险区，不放关键文字、头像或必须阅读的结论。

## 封面合同

- `gbro-cover-design 只负责构图提示词`、风格和标题决策；`cover runner 负责实际生成`、A-roll 人物合成、本地中文排版与 QA。不能因为子 Skill 只输出提示词就停止交付。
- 参考图必须存在并绑定 SHA-256。图1固定为当前讲师清晰人脸/人物参考；涉及产品、UI 或道具时，图2起绑定批准素材。缺参考图必须 blocked，不得仅凭文字猜脸。
- 人脸不得被文字、道具或裁切遮挡；五官身份要与参考图一致。人物动作、道具和环境必须符合当前主题，而不是套用固定惊讶姿势或无关科技背景。
- 标题使用本地中文排版，逐字检查；图片模型生成的中文不作为最终文字层。关键元素距四边至少10%安全边距，同时服从脸部避让。
- 封面只输出当前 Job 在 `cover_direction` 已批准的比例；子 Skill 的 3:4 默认值不改写该选择。

## AI B-roll provider 合同

- 本项目现有 Grok adapter 固定模型为 `grok-imagine-video`，不是通用 Skill 对所有 Job 的强制模型。用户选该 adapter 时，先检查模型可用性，优先使用项目的 `model_is_available()`；直接探测时调用 `/v1/models`，只有响应返回精确 ID 才可生成，不能误用 `/models`，也不能用相似名称或 preview 名静默替代。选择内置或其他第三方模型时必须使用本 Job 已确认、已验证的对应 adapter；工具缺失或只支持生图时不能宣称可生视频，更不能悄悄切回 Grok。
- 默认生成无声 9:16 视频，主口播音频继续使用 A-roll 时间轴。生成画面不承载官方事实、精确数据、Logo 或需要可靠识别的文字。
- plan 选择图生视频时，批准参考图及哈希必须存在并传给支持该输入的 endpoint；缺图时 blocked。plan 明确批准文生视频时才可无参考图执行，不能自动改写图生视频配方。
- 同一 generation 只允许一次外部生成请求。领取前先完成全部本地路由与绑定检查；本地失败的外部请求数和 AI attempts 必须为 0。失败、429、模型不存在或媒体验证失败后立即 blocked，只展示 `retry_same_strategy` 和 `replan_visual_direction`；不自动重试，也不把占位素材当最终资产。
- 累计 ledger 与当前 generation 必须分开统计。`asset-manifest.json` 以 `type` 判别资产，不得读取 `asset_type`；当前生成资产数不得用全局 `ai_attempts` 代替。

## 低内存与 Agent 运行

- 默认只允许 1 个主 Agent 内联执行，不得为了提速新增子智能体。用户明确要求多 Agent 才能改变这一点，且仍需避免多个 Agent 同时渲染。
- 浏览器、Remotion、FFmpeg 和外部生成均串行；重型并发为1。每个镜头完成后关闭页面、释放帧缓存，再处理下一个。
- provider 连接只用于当前已批准 generation；运行报告仅保存连接状态与标识字段。

## 参考项目登记

以下本地克隆仅作为设计与工程来源；实际产物仍须符合本 Skill 的9:16、批准、来源和 QA 合同：

- `参考项目/B-roll开源方案/html-video`
- `参考项目/B-roll开源方案/video-shotcraft`
- `参考项目/B-roll开源方案/erduo-broll-loop-engineering`
- `参考项目/B-roll开源方案/video-use`
- `参考项目/B-roll开源方案/video-autopilot-kit`
- `参考项目/B-roll开源方案/hyperframes`
- `参考项目/B-roll开源方案/remotion`
- `参考项目/B-roll开源方案/OpenMontage`
- `参考项目/B-roll开源方案/Generative-Media-Skills`
- `参考项目/B-roll开源方案/Open-Generative-AI`

`参考项目/B-roll开源方案/OpenChatCut` 是用户明确要求外部编辑时才启用的额外适配，不属于核心 B-roll 能力路由。

各项目的唯一职责、延迟加载、统一 VisualIntent / ShotRecipe v2、五类同级语义选择、主渲染器和多样性约束以 [B-roll 语义能力路由](broll-capability-router.md) 为准。复用真实页面/素材获取、分层动效、镜头配方和质量循环；不绕过逐阶段批准，也不输出横屏后裁切的假竖屏。

精确文件级入口与不得调用的整仓库边界见 [B-roll 开源能力适配矩阵](open-source-adapter-matrix.md)。当正式 v2 渲染时，用户/官方媒体由 `edit/hd/tools/broll_media.py` 核对路径、大小与 SHA-256；代码海报不得代替丢失的真实媒体。
