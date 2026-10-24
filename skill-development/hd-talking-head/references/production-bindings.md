# 正式生产绑定

本文件登记当前仓库可验证的正式视觉身份。确认样片就是正式模板，不是“风格接近即可”的参考；任何字体、文案、构图、头像、动效、模型或证据变化都不得静默修改，必须形成 revision 并重新报审。

## 当前模板与本期样片

整屏模板资格的唯一来源是 [当前模板注册表](verified-template-registry.json)，使用前按 [双输入实测资格](template-qualification.md) 校验。可验证模板数量与入口读取注册表，不从旧评审板、旧家族目录或参考仓库数量推断。原生组合组件、设计来源及实际执行器的接通范围按 [统一候选入口](broll-capability-router.md#唯一选型入口与记录) 判断，不把这些角色都计为已验证整屏模板。

本期实际使用的模板、字体、文案、头像与动效以当前 Job 已批准的 ShotRecipe 和 canary 为准。历史五镜头样片及评审板仅属于原任务的设计证据，不是新视频的固定文案、统一时长或替代模板，不从外部 Downloads 目录回填。

OpenFilm 按 [原生创作合同](openfilm-motion-graphics.md)绑定本期页面、素材、动作拍及原生指令版本；它使用 `ReferenceProcessAdapter / OpenFilm`，不是已验证模板。已认可样片只供质量参照，不形成固定构图；后续仍按本期语义创作、验收。原声、圆窗与唯一字幕由父级合成，已验收成片不回填、不迁移。

自定义家族由当前路由器与 renderer 提供，但只有注册表通过验证的入口才能宣称已验证；自定义模板仍需当前内容的三态检查及人工样片确认。

## 文案与字体锁定

- 所有可见文案必须来自已批准口播稿、已批准 `visual-plan.json` 的 `exact_text` / `exact_numbers` / keywords、已绑定官方资料，或已经单独批准的 editorial payoff；不得擅自改写观点、数字、因果关系或结论。
- 当前镜头的标题、数字、结论和来源必须与本期已批准的配方逐字一致；最终上屏字符串写入 plan 和 manifest，再以哈希绑定。不把历史样片文案复制到新任务。
- 内部语义字段不得上屏，包括“主题”“结论”“关键值”“提问”“反馈”“对照”等生成器角色名，除非它本身就是用户批准的文案。
- 每个模板必须绑定字体族、字体文件或系统字体身份、字重、字号、行距、字距和回退顺序。canonical 基线使用 PingFang SC、Songti SC、SF Mono；正式模板允许已登记的 Hiragino Sans GB 与 STSong 回退。
- 缺少已绑定字体时必须 blocked，不得静默替换字体。更换字体、字重、字号或行距属于视觉 revision，必须检查新版实际视频与原尺寸关键帧后报审，不生成缩略拼图。
- 文本测量发生在渲染前和渲染后；任何溢出、被裁半、强制缩成不可读字号或与头像/其他文案重叠都判失败。

## 官方资料与命名人物绑定

- 官方资料的 `product_page`、`image` 和 `video` 分别冻结真实来源，使用当前语义路由、ShotRecipe 校验和 `broll_systems.validate_composition` 验证组合；媒体执行再由 `broll_media.py` 核对实际内容，不调用已退役的旧路由接口。
- 文案出现命名人物及职务时，对应事实组件绑定第一方官方视频或官方人物页图片。姓名、职务、publisher、URL、访问时间、媒体类型、路径、字节数与 SHA-256 必须写入来源记录。
- 口播明确强调 CEO、创始人、研究者等职务时，姓名和职务必须进入已批准可见文案，或由紧邻的官方视频标题卡可靠呈现；不得只有人物图而丢失身份信息。
- 官方图片和官方视频分别进入 plan、manifest 与三态 QA；存在一种媒体不能代替对另一种已批准媒体的绑定和验收。
- 完整执行次序与失败分类见 [视觉资产前置检查](visual-assets-preflight.md)。

## 条件 B-roll 依赖绑定

A-roll 透明注释使用独立 `aroll_with_overlay / mode=none` 家族，正式组件调用、源片/时钟绑定和验收见 [A-roll 透明贴片合同](aroll-overlay-contract.md)。它保留全屏真人和普通字幕，不进入 B-roll 的资料底图规则；不透明 TalkCraft 整屏卡的资格边界保持不变。

- 代码组件只能使用正式 VisualPlan v3 内 ShotRecipe v2 冻结的 `dependency_id / entrypoint / producer_version`。预检先调用正式计划与配方 validator；不完整字段、identity 不一致或非法 component 不进入依赖绑定。
- `code_generated` 调用现有依赖：`html-video`、`hyperframes` 与 `hd-talking-head-local-canonical` 通过 `ReferenceProcessAdapter` 使用登记模板的实际引擎。模板引擎不能仅由仓库名推断。执行层把组件交给 `broll_component_executor.execute_component`，产物必须保留真实调用证据。通过绑定检查不等于 adapter 已完成两组真实渲染验证。
- `hd-talking-head-talkcraft` 通过 `ReferenceProcessAdapter` 执行项目内锁定的 Remotion 运行时。自动选卡在 `visual_direction` 上游调用 `edit.hd.tools.talkcraft_matcher.match_cards`：108 张 qualified 卡全部进入语义检索池，先按 `production_role`、必需媒体和人物要求做硬过滤，再根据口播、语义家族、目标和关键词稳定排序。`build_binding` 把选中的 `hd-talking-head/talkcraft/<card_id>` 和当前 brief 身份冻结进 ShotRecipe；adapter 与 executor 不得二次选卡。语义索引只是检索数据，真实准入仍以项目 `runtime/card-registry.json` 为准。每个新 Job 先运行项目的 `edit/hd/integrations/talkcraft/check_runtime.py`；上游共享 runtime 与正式资格 runtime 隔离，不自动升级正式版本。Workbench 只通过 `build_v4_edit_contract` / `apply_v4_overrides` 产生未批准 draft bundle，修改后重新走 canary 与人工门。
- 五类来源同级；仅在已经批准 `code_generated` 的组件内，候选先按 `semantic_match_score`、再按 `quality_score` 排序，同分才比较 `template_origin`，最后比较 `reuse_gap`。该顺序仅说明单段底层候选排序；全片选材按[画面多样性](visual-quality-contract.md#画面多样性)在语义与质量合格的候选中优先扩大真实渠道和模板覆盖，不受机械同分限制。正式记录以 `references/verified-template-registry.json` 为准，执行前必须通过 `scripts/verify_broll_template.py`，再由 `candidate_from_verified_template_record` 添加当前文案分数。
- `html-video/frame-data-rollup` 的原生接口见 [DataRollup 执行合同](data-rollup-execution.md)。`scripts/data_rollup_adapter.py` 创建正式 ReferenceProcessAdapter 与真实媒体探测器；`scripts/render_data_rollup.cjs` 消费当前 brief，保留原始第三方动画。其他 family 不因该接口存在就被认定已经执行验证。
- `hyperframes/notification-cascade` 的原生接口见 [Notification Cascade 执行合同](hyperframes-notification-execution.md)。`scripts/hyperframes_notification_adapter.py` 创建正式 ReferenceProcessAdapter 与真实媒体探测器；`scripts/render_hyperframes_notification.cjs` 使用固定四节点原生时间轴并调用真实 HyperFrames CLI。
- `hyperframes/chatgpt-exchange` 已因正文和表格裁字退出活动资格，不进入新选型。[历史执行合同](hyperframes-chatgpt-exchange-execution.md)、适配器和失败证据仅用于追溯；它们存在不代表当前可选。独立的原生 `chat-message` 组件不受此排除影响。
- A-roll 三节点流程调用 HyperFrames Registry 的 `hw-pipeline`，接口与限制见 [A-roll 透明贴片合同](aroll-overlay-contract.md)。`scripts/hyperframes_hw_pipeline_adapter.py` 绑定批准段落和真人源片，`scripts/render_hyperframes_hw_pipeline.cjs` 调用真实 HyperFrames CLI 并输出透明 MOV；不是 TalkCraft 自制样式，也不等于该样片已完成正式 Job 的全片验收。
- `hd-talking-head-local-canonical` 的入口为 `scripts/local_canonical_adapter.py`，执行 `scripts/local_canonical_renderer.cjs`。它提供 `process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword` 五个原生 9:16 构图；每个入口都必须匹配 registry 的源码哈希、版本、双输入回执和当前运行时固定。
- Huashu 的生产入口为 `scripts/huashu_motion_adapter.py`，实际调用固定 vendor 的 `render.py --spec`，第三方源码保持原样。已登记 `huashu-art-motion/y1_kurzgesagt` 三节点机制流程，容量恰好为 3，语义为 `process_flow` / `mechanism_system`，保留原生 `title` / `point` / `flow` 及信号；不含 hierarchy、`highlight` / `enter`。另已登记 `huashu-art-motion/y2_vox`，容量恰好为 1，语义为 `evidence_source`，限单张横向真实来源图及整行高亮；须执行该页的输入版式与高亮全过程避让检查。已登记 `huashu-art-motion/t2_keynote_ui`，仅 `product_features` 的恰好三张原生功能卡，不扩大到未测的截图、数字或教学步骤。三条路线共用 `1.1.0` 启动器，仅在独立子进程设置连接等待容量为 64，不改 vendor 文件。准确边界、项目 Python 环境及失败处理见[Huashu 原生动效接入](huashu-native-motion.md)。
- 每个代码组件必须冻结 `template_origin / template_id / template_version / verification_id / adaptation_level / source_entrypoint / source_sha256 / sample_sha256 / semantic_families / capacity`。`structural` 改造不得沿用第三方验证身份；实际填充后必须重新做当前文案三态 QA，不能拿历史样片直接交付。
- 只发现 Skill 名称或参考项目目录不代表已经绑定。当前配方选中 `html-video`、`hyperframes` 或 `hd-talking-head-local-canonical` 后，manifest 中必须存在精确匹配 entrypoint 与 producer version 的可执行 binding probe；probe 返回的 `dependency_id / entrypoint / producer_version / adapter_identity` 必须与批准配方及登记逐字一致，才能返回 `selected + callable + bound`。HyperFrames 及其支撑的本地 canonical probe 还复核固定运行时提交、CLI 版本、渲染入口与模板包装器。
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

- 项目内 `punk-cover` 优先负责 9:16 图文穿插候选的内容转译、标题/人物关系和完整成图；保存其实际提示词与输出，不能仅口头声称调用。现有 `gbro-cover-design` 保留为正式 runner 的 brief/无字底图接口；`cover runner` 仍负责正式发布、哈希和 QA，Punk 候选不自动等于已批准封面。
- 参考图必须存在并绑定 SHA-256。图1固定为当前讲师清晰人脸/人物参考；涉及产品、UI 或道具时，图2起绑定批准素材。缺参考图必须 blocked，不得仅凭文字猜脸。
- 五官和脸部轮廓不得被文字、道具或裁切遮挡；五官身份要与参考图一致。经本 Job 认可的少量发丝与字穿插允许保留，叙事手部仍须清楚。人物动作、道具和环境必须符合当前主题，而不是套用固定惊讶姿势或无关科技背景。
- 完整成图路线逐字检查图片模型生成的中文，批准后原样复用该图，不再本地叠字；无字底图路线才使用本地中文排版。关键元素仍服从本 Job 已批准的边距与脸部避让。
- 封面只输出当前 Job 在 `cover_direction` 已批准的比例；子 Skill 的 3:4 默认值不改写该选择。

## AI B-roll provider 合同

- 本项目现有 Grok adapter 固定模型为 `grok-imagine-video`，不是通用 Skill 对所有 Job 的强制模型。用户选该 adapter 时，先检查模型可用性，优先使用项目的 `model_is_available()`；直接探测时调用 `/v1/models`，只有响应返回精确 ID 才可生成，不能误用 `/models`，也不能用相似名称或 preview 名静默替代。选择内置或其他第三方模型时必须使用本 Job 已确认、已验证的对应 adapter；工具缺失或只支持生图时不能宣称可生视频，更不能悄悄切回 Grok。
- 默认生成无声 9:16 视频，主口播音频继续使用 A-roll 时间轴。生成画面不承载官方事实、精确数据、Logo 或需要可靠识别的文字。图片和视频 provider 均来自本 Job 启动时确认的渠道配置，可相同或不同；不设固定 Lovart、Grok 或内置图片工具。
- plan 选择图生视频时，批准参考图及哈希必须存在并传给支持该输入的 endpoint；缺图时 blocked。plan 明确批准文生视频时才可无参考图执行，不能自动改写图生视频配方。
- 同一 generation 只允许一次外部生成请求。领取前先完成全部本地路由与绑定检查；本地失败的外部请求数和 AI attempts 必须为 0。失败、429、模型不存在或媒体验证失败后立即 blocked，只展示 `retry_same_strategy` 和 `replan_visual_direction`；不自动重试，也不把占位素材当最终资产。
- 累计 ledger 与当前 generation 必须分开统计。`asset-manifest.json` 以 `type` 判别资产，不得读取 `asset_type`；当前生成资产数不得用全局 `ai_attempts` 代替。

## 低内存与 Agent 运行

- 保持 1 个主控，可委派最多 3 个互不依赖的轻量准备任务；先分配语义、时码、风格与各自输入目录，子任务不写正式清单、workflow 或批准记录。
- 浏览器、Remotion 和 FFmpeg 重任务一次只运行一个。单 renderer 内部帧并行须先以同输入真实对照验证，再仅对已验证入口启用；不得将其当作同时开多个 renderer 的许可。每个镜头完成后关闭页面、释放帧缓存，再处理下一个。
- 图片和视频生成共用当前 Job 的上限 2，云端等待期间继续准备其他镜头。正式计划仍要求已完成媒体与完整绑定，不能在云端 pending 时跳过批准阶段提前制作正式 canary 或字幕。
- provider 连接只用于当前已批准 generation；运行报告仅保存连接状态与标识字段。

## 有界生成编排

所有新 Job 的图片和视频生成必须先经过项目内 `edit.hd.tools.generation_queue`，不能由各子 Skill 绕过它各自提交。它是宿主现有工具的本地准入入口，不生成媒体、不替代子 Skill 的设计、不增加付费次数；正式阶段、资产验收和最终合成仍由原 runner 串行处理。队列只返回真实宿主 `action`，不声称 Python 可以直接调用 MCP 或其他宿主工具。

1. 主控先冻结各项具体内容、模型、次数、输入与真实上传范围，取得对这批内容的真实授权。配置确认和本次“实施并发”的同意不能代替付费生成授权。已授权的同一具体请求不重复询问；新增或实质变更请求重新确认。按当前视频 provider 的真实模型说明检查参数；若图片或视频由宿主工具提供，保存其真实 action 和响应，不把本地函数名当作工具调用。使用同一个真实 `project_id`（若该 provider 要求），上传、生成、查询与展示全部传该 ID。
2. 视觉确认前不提交生成请求。`visual_direction` 先在独立 `07-visual-confirmation/rN-id/` 冻结 director brief、treatment、routing 和完整 proposal；treatment 的 `generation_plan.steps`（冻结后为 proposal 的 `generation_steps`） 可引用尚未生成的图片步骤，视频步骤通过 `{"$step":"image-step","output":0}` 引用其未来输出，不伪造未来 hash。用户确认整表后，才把已授权步骤转换为可执行请求并加入 plan。顶层请求仍只有 `id / purpose / tool / arguments / input_files`；工具 action 必须来自已确认渠道的真实 `generation_channels`，不得写死 `image_gen.imagegen` 或 Lovart。每份本地输入登记 Job 相对 `path / sha256 / bytes`，并发任务不使用会变化的“最近几张图”。每个 purpose 的渠道配置还必须有 `model_binding`：`argument` 模式把选定型号注入参数并拒绝不符请求，`fixed` 模式不注入 `model`；`reference_mode=upload` 必须先按配置执行上传、保存原始响应及回执，再替换冻结本地路径提交逻辑请求。
3. 主控用 `contract_artifacts.sha256_json(plan)` 计算已审阅 plan 身份，调用 `add(job, plan, user_confirmation, expected_plan_sha256)` 保存具体授权。宿主通过 `generation_channels.next_action` 取得公开的 `upload / submit / query` action；`queue.claim` 只作为内部领取和占位，不是宿主生成入口。Lovart 视频的 `account_limit` 必须来自当前 `get_credits.concurrency_limit`，不是剩余空闲名额；其他真实渠道使用其自己的实时额度来源。图片和视频总数以本 Job 已确认的 1 或 2 为限，`submitting / pending / unknown` 都占位。
4. `next_action` 返回 upload 时，宿主执行真实上传并立即通过现有 `record` / `generation_results` 入口回传原 action 与原上传响应；上传待回传期间再次调用 `next` 返回 `blocked/input_upload_pending`，不得重复上传。回传后再取得 submit/query action。Python 入口只回传真实 action、参数和必要 token，不直接调用 MCP；不要并行开本地重渲染或写正式批准记录。
5. 每个 provider 保存真实结构化返回，队列分别保留首次 `submission_response` 和最终 `completion_response`，不会被轮询状态覆盖；图片和视频都只提取工具真实返回的媒体引用，保存实际路径或真实 URL，不得杜撰文件、任务 ID 或保存 base64、密钥。完成仅释放生成名额，不代表资产验收通过；原有动态、语义、字幕、安全区等检查仍执行。
6. `next_action` 仅在等待时间到达后返回 `query`，其中的真实查询工具和参数来自已确认渠道的 `query` 配置。宿主执行后回传原 action 与规范结果，入口使用该 action 的精确任务 IDs；不能按返回顺序、文件名或总数量猜归属。批量返回无法逐项对应时，查询该请求的准确 IDs，不将聚合结果当作单项成功。结果完成后才可补下一项，不反复向用户确认同一视频。
7. 重启先用 `status(job)` 恢复已有记录。已领取、结果不明或失败的 ID 一律不会自动重提；有 task IDs 时只查询已有任务，没有 IDs 时保留占位并查实际项目记录，不能为腾名额把它标成失败。`CONCURRENCY_LIMIT` 暂停后续领取，其他任务完成也不解除暂停；仅真实获准继续时调用 `resume(job, user_confirmation)`，它只恢复尚未领取项，不重试旧失败或未知任务。`record / poll / status` 不依赖新配置批准，因此配置变更后仍可收回已发出任务的结果。

### 受控失败重试

受控重试不是普通 `add`，也不是自动恢复。只有明确 `failed` 且证据来自该请求的精确提交回执或单任务查询时，才可先调用只读的 `prepare_retry(job, request_id)`。它返回冻结计划、`plan_sha256`、原请求和确定性的 `plan_request_id`；计划至少包含 `job_id`、`from_id`、`failure_response_sha256`、`request_fingerprint`、`config_sha256`、完整 `input_files` 与 `count=1`。`from_id` 必须是指定失败项，不能自动改成最新子项；`submitting`、`pending`、`unknown`、`not_found`、`moderated`、已完成但 QA 不通过或未逐项核实的聚合失败均拒绝。

用户针对这份冻结计划作出一次实际授权后，调用 `retry(job, plan, user_confirmation, expected_plan_sha256)`。它在同一文件锁内验证父项仍不可变、配置和输入身份未变，且父项至多一个后继，然后原子追加唯一 `ready` 子项并消费本次授权。重复相同计划、哈希和父项只返回原子创建的同一子项；不能借此为子项再次失败自动续试。新项带 `retry_of` 与 `plan_request_id`，领取时仍返回队列项 ID 和原始分镜 ID；只有 `next_action` 返回 `action=submit` 后才能调用生成供应商，供应商 task ID 仍以真实回执为准。旧 nonce、旧 task ID 或迟到回执不能覆盖新项。供应商没有 client idempotency 参数，因此这里只保证本地唯一领用，不声称供应商端严格仅一次。

`not_found` 必须保存原始响应，本地状态为占位的 `unknown` 并继续占用并发名额；停止对该最终 not-found 查询自动轮询，须回查已保存的任务或项目记录，不能据此推断未扣费。聚合接口只返回总 `failed`，或同一请求有多个 task ID 但不能逐项证明全部失败时，禁止创建重试，改为逐项查询或停在 blocked。`resume` 只清除暂停状态并放行 `ready` 项；一次用户回复可以同时覆盖恢复和一项具体重试，但不重复追问，也不复活失败或未知项。

完成后的唯一交接不新建 runner：封面核对实际带字图后用 `cover.prepare_cover(job, approved_preview=实际PNG, approved_preview_sha256=实际摘要, approved_preview_prompt=实际prompt)` 原样发布，见[封面标题合同](cover-title-style.md)。新生成结果按[本次所选图片/视频渠道的完成结果](generated-broll-skills.md#本次所选图片视频渠道的完成结果)，用 `generated_media.record_from_queue` 登记；模型身份来自该次实际提交，原片和规范片来源随记录保留。已有 Lovart 完成素材继续使用其原适配器，不改身份或重新生成。然后依次准备匹配的 binding → 将返回值放入当前组件 `compile_context.bindings` 并正常编译批准配方 → 创建对应 adapter 与 artifact probe → 既有公共组件执行器。每份 record 绑定当前 segment/component 和原声时窗，最终仍由原 `visual_canary / visual_assets_v2` runner 验收、组装；不把两项队列回执直接当作一份全片 adapter，也不补造事实或绕过正式批准。

现有 CLI 与上述接口等价，使用预检的同一个解释器和明确项目根目录，不从别的工作区导入。示例中的占位符必须先替换；不要把示例确认文字当作真实批准：

```bash
<python> <skill>/scripts/run_generation.py --project-root "<project>" --job "<job>" add \
  --plan-json "<已冻结 plan.json>" --user-confirmation "<用户原文>" --plan-sha256 "<实际 plan hash>"
<python> <skill>/scripts/run_generation.py --project-root "<project>" --job "<job>" next \
  --request-id "<实际请求 id>" --account-limit <Lovart 当前账号上限>
<python> <skill>/scripts/run_generation.py --project-root "<project>" --job "<job>" record \
  --action-json "<原 action.json>" --response-json "<实际响应.json>"
# 异步生成继续调用 next，只有返回 query 时执行查询工具；其他渠道无此额度参数要求时省略 account-limit。
PYTHONPATH="<project>" <python> -m edit.hd.tools.generation_queue --job "<job>" prepare-retry --id "<明确失败的请求 id>"
PYTHONPATH="<project>" <python> -m edit.hd.tools.generation_queue --job "<job>" retry \
  --plan "<冻结的 retry plan.json>" --user-confirmation "<针对该计划的一次用户授权>" \
  --expected-plan-sha256 "<实际 plan hash>"
```

领取记录位于同一 Job 的 `manifests/generation-queue.json`，短文件锁只保护读取、领取与原子保存，不覆盖云端等待。不要为旧 Job 改配置、重签批准或重做已验收成片来启用本入口。本地字幕 Remotion 入口的已验证帧并发见 [字幕合同](subtitle-style-contract.md)；其收益不代表其他动画入口或整片制作已完成并发实测。

## 参考项目登记

以下本地克隆仅作为设计与工程来源；实际产物仍须符合本 Skill 的9:16、批准、来源和 QA 合同：

- `参考项目/B-roll开源方案/html-video`
- `参考项目/B-roll开源方案/erduo-broll-loop-engineering`
- `参考项目/B-roll开源方案/video-use`
- `参考项目/B-roll开源方案/video-autopilot-kit`
- `参考项目/B-roll开源方案/hyperframes`
- `参考项目/B-roll开源方案/remotion`
- `参考项目/B-roll开源方案/OpenMontage`
- `参考项目/B-roll开源方案/Generative-Media-Skills`
- `参考项目/B-roll开源方案/Open-Generative-AI`
- `参考项目/B-roll开源方案/baocut`(方法论参考,不参与运行时;钉定提交 `754737d2`)

`参考项目/B-roll开源方案/OpenChatCut` 是用户明确要求外部编辑时才启用的额外适配，不属于核心 B-roll 能力路由。

各项目的唯一职责、延迟加载、统一 VisualIntent / ShotRecipe v2、五类同级语义选择、主渲染器和多样性约束以 [B-roll 语义能力路由](broll-capability-router.md) 为准。复用真实页面/素材获取、分层动效、镜头配方和质量循环；不绕过逐阶段批准，也不输出横屏后裁切的假竖屏。

精确文件级入口与不得调用的整仓库边界见 [B-roll 开源能力适配矩阵](open-source-adapter-matrix.md)。当正式 v2 渲染时，用户/官方媒体由 `edit/hd/tools/broll_media.py` 核对路径、大小与 SHA-256；代码海报不得代替丢失的真实媒体。

供应商视频的原始文件和原始响应必须先保存。需要格式处理时另存 24fps、静音、H.264、yuv420p 且保持同宽高比的规范文件；不覆盖原件、不变速、不乱裁切。规范文件写入 `artifacts.path`，来源记录的 `artifact.source` 标明原始文件和处理链；原始供应商响应不与规范响应混称。已合格原件直接使用，生成记录只引用队列真实结果。

规范响应中的处理后文件使用 `{"type":"video","path":"artifacts/normalized.mp4","source":{"path":"artifacts/provider-original.mp4"},"processing":"24fps silent H.264 yuv420p; aspect ratio preserved"}`；`record` 分别留存原片与规范片，并将 `source` 补为 `{path,sha256,bytes}`，completed record 保留 `generation.source_media/processing`。`provider_response`（如有）只放真实供应商返回，原始响应另存。上传 action 发出后，`next` 返回 `blocked/input_upload_pending`，宿主回传原 action 与原上传 response 后再继续，避免重复上传。

Adu `native-compare` brief 显式提供 `typography: {title_px, body_px}`，单位为最终 1080×1920 画面像素。四字短标签可采用64/56px；字体覆盖只在自有静态 host 中完成，不改上游 TPL.compare 动画。入口检查实际可用宽度及原生行距，容量不符先缩短文案或换合适模板，不能用缩到难读的字号过关。
