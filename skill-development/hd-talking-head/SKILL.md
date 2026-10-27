---
name: hd-talking-head
description: Use when 用户提供原始口播视频和文案，希望完成封面、内容提炼、剪辑、A-roll、B-roll、字幕、预览与交付；在封面方向/实际封面和整片视觉清单处确认一次，确认后直接完成交付。
---

# HD 口播全流程

本 Skill 是现有口播后期工作流的执行合同。每条视频建立一个独立 Job，以批准状态、文件哈希和宿主内部检查推进。它只支持 `full-v2` 十二阶段流程和 VisualPlan schema v3 / ShotRecipe v2，不兼容旧 visual Job；正式冻结的主计划为 schema v3，TalkCraft 工作台另消费派生的 span-aware v4 计划（同一 validator 校验，不改主计划格式）。旧 visual Job 重新执行 `visual_direction`，不读取或转换旧视觉计划。

本包不限定 Agent 品牌；需要能读取文件、运行脚本及尊重用户确认的宿主。整个 Skill 文件夹包含剪辑引擎、字幕与贴片运行代码、模板、原始资源及子 Skill。本文命令中的 `<project>` 指最外层 `hd-talking-head/` 包根，`<skill>` 指其内部 `skill-development/hd-talking-head/` 实现目录；用户素材和 Job 输出另放独立工作目录。优先使用最外层 `run.py`，无需原开发项目或全局 Skill。首次运行准备全流程基础依赖，并由用户选择图片、视频生成渠道；选中模板的环境在整表确认前按需准备。完整包发布见 [发布与调用合同](references/release-contract.md)。

本 Skill 的职责是编排和验收，不重新实现已有 Skill 的媒体能力。每个阶段先按依赖清单确定能力提供方，再读取该 Skill 的原始说明并实际调用其入口，最后核对本次输入身份、调用记录、真实产物及阶段质量门。`发现/安装`、`configured`、`connected`、`callable`、`bound` 是[依赖预检合同](references/dependency-preflight.md)定义的五个递进状态，产物另经阶段质量门验收，不得混用；不得用阅读说明、借用参数或运行无关 helper 冒充该阶段由第三方 Skill 完成。现有 Skill 覆盖不了的 Job 状态、素材绑定及项目专属 QA，才由本包和 `edit/hd` 执行；新制作不得新增动效算法、关键帧、曲线或替代时间线。能力未接通时在批准前换原生候选或保留 A-roll，批准后失败停当前 route 进入 revision，不能悄悄切回自写实现。

所有新来源都完整接入其原生 Skill 或原生组件，统一按“渠道→模板→标签”管理；第三方文件保持原样，不提取源码重写引擎。已接通的 [OpenFilm](references/openfilm-motion-graphics.md)、[Lemo Opuscar](references/lemo-opuscar.md) 和 [Lemo Wake](references/lemo-wake-integration.md) 在同一候选池中选择。Lemo Wake 只有一个完整原生模板身份 `lemo-wake/wake`，不把其内部风格、图层或重置目录拆成多个模板。选中后完整执行该 Skill 的原生流程，调用其制作入口：有原生渲染器的使用原生渲染器，通过生成服务制作的使用本 Job 已批准的图片、视频渠道；不因上游默认模型自动更换服务或增加费用。主题场景沿用所选模板身份，不以父级自写动效替代原生能力；来源和适配资格如实记录，历史停用入口不因此恢复。

## 统一执行与语义规划

渠道是完整创作流程，既可直接渲染，也可先设计再调用本 Job 已批准的生图、生视频服务。GBRO、Flat 共用底层服务仍各算渠道；依赖调用不额外计渠道。原生风格、配方和已登记的完整工作流模板同等参与优化，内部 design/native 调度分类不改变计数。内容和模型变化不新增模板。生成、完成绑定和素材复用读取同一已批准 assignment，不能由 provider 反推创作身份，见[创作身份与复用](references/visual-quality-contract.md#创作身份与生成结果复用)。

仅规划请求按[仅规划任务](references/visual-quality-contract.md#仅规划任务)执行；使用只读规划检查，不创建或修订制作 Job。

正式阶段统一通过 `scripts/run_stage.py` 调用现有十二阶段运行时。入口从当前未完成阶段继续；已批准产物核验后复用，待审产物先审查，明确修订才重做。参数、宿主内部批准和恢复方式见[阶段执行入口](references/stage-runner.md)。

1. **剪后语义理解**：完成 `speech_cleanup` 与 `edit_structure` 后，以实际剪后词级转写、时间轴和已批准内容项为唯一输入，逐段列出主体、动作、关系、变化、真实词锚和语义。原 `content_analysis` 仍服务封面与事实原文，不代替剪后语义分析。
   先按[确认前的逐句盘点](references/visual-quality-contract.md#确认前的逐句盘点)填写当前 treatment 的 `beat_sheet`，再决定镜头合并与模板；该合同还规定时间、身份连续性、候选槽位和规划／媒体验收边界。确认入口检查剪后词引用完整、处置与组件时窗一致；共用组件须说明各句如何得到不同动作或关系的表达。字段和时长合格不证明语义、美观或数量充分，一个长镜头里多张标签出现也不能代替逐句设计。
2. **先列两份语义列表，再匹配能力**：字段与命令见[语义列表、匹配缓存与确认字段](references/visual-quality-contract.md#语义列表匹配缓存与确认字段)。两类初始数量分别由语义行决定；每行一次全库匹配并保留全部候选，再联合分配渠道与模板，最后校验时间。确认表列编号、类型、时间、内容、渠道、模板，并分别统计两类数量。
   在现有语义行的 `semantic/visual_task` 或 `beat_sheet.visual` 写明必须看见的对象、动作/关系、状态变化、允许结果和不能提前出现的后文结果，不另建平行字段。标签命中只负责召回；候选须再核对原生内容槽、动作、真实输入和输出容量。仅换标签、颜色或相同小卡不算状态变化。
3. **一次整表确认**：`visual_direction` 先根据草稿实际 bindings 准备并检查所选模板的执行入口，成功后才输出完整 `visual-routing.md` 与确认前方案清单，列全每个视觉组件及其匹配模板，并从 1 起编号。编号绑定本期冻结清单中的 `row_id`；局部返修继续用原编号，不按修改后的稿件重新排序。用户只在这里确认整张表；确认前保持待审，不能自动批准或生成正式视觉资产。确认后由宿主生成并绑定视觉资产，再编译正式计划，随后内部完成 canary、字幕、预览 QA 和交付，不再请求用户确认样片、字幕、预览或成片。

所有动效在整表确认前先按[实际文字检查](references/motion-text-readability.md)冻结文字目标；正式制作通过共享检查器读取最终像素。仅看手机缩略图、源字号或某一张好帧不够，识别不确定时也由宿主主动逐项量框处理。

语义与设计可实现性共同决定候选准入；具体淘汰依据、单一渠道复核及 `design_plan` 交接见[候选与设计合同](references/visual-quality-contract.md#语义列表匹配缓存与确认字段)。所选设计随 assignment 冻结并传到制作，OpenFilm 沿用原 brief 字段。新proposal使用 `visual-review-v2`，实际画面还须在原阶段回执中通过构图、字级、完成度和动作焦点观察；文字合格不代替美观。没有具体依据时先补评审，不以提前限定表现方案换取单一渠道，也不为渠道数降低质量。

成片在每项动效的实际时窗内，于右下角显示对应的小编号，避开字幕和人物小窗；封面和没有动效的空档不显示。编号只在最终合成层加入，不重做原生动效。清单和画面共用已确认 proposal 的冻结行序与 `row_id` 映射，沿用正文帧窗并加正式封面偏移；检查编号、时间和可读性后直接交付。
4. **先检查再发布**：新草稿写入独立目录，保留旧资料和 `confirmed-content.json`。正式发布前检查词锚、整帧时窗、绑定、重点、保留内容和密度；通过后由现有发布事务提交。失败不覆盖原计划，不清空用户确认。
5. **最后校验密度标准**：机器规则只读取[默认制作配置](references/production-defaults.json)的 `visual_coverage`。B-roll 目标约 60%、默认下限 55%，首条不晚于 15 秒等仅用于分配完成后的覆盖检查，不用于决定初始条数。贴片不计入 B-roll 时长，必须单独列出两类数量、覆盖重点和保留真人原因；若覆盖不足，回对应语义列表补项，不通过拆段凑数。比例达标仍须检查实际语义、动作、字幕和画质；题材不能满足时报告具体缺口。

头像进出在清单确认前、所选依赖准备前安排。正式入口先按完整B-roll组补齐首入、末出和组内延续；不足1秒且无贴片的纯真人空档返回内部准备动作，宿主按明确的新时窗延续原生末态，重新绑定输入、口播引用、阅读窗及真实头像测量后重入。动作未完成不准备依赖、不冻结清单。新清单另有独立完整性门，漏填字段也不能跳过；片首片尾不虚构相邻真人。详见[头像连续性合同](references/avatar-profile.md#先连组再安排进出)。

完整新方案在 treatment 显式填写新的 `numbering_scope_id`，活动项目从 1 编号；局部返修沿用该标识和同一画面的 `row_id`，只继承本套方案的批准编号。proposal 内保存全部已分配编号，删除不回收，新增只取更大的新号；换素材或模板不改号。清单和成片共用明确编号，同屏角标在底部安全区分行，空间不足先调整。制作后按[实际画面复核](references/visual-quality-contract.md#实际媒体复核)完成逐组件观察，合并到已有宿主阶段回执；实际媒体改变后原观察失效。现有已批准Job、成片与确认记录不追溯改写，显示编号变化不重签生成授权或重发请求。

**保留当前成果**：阶段目录和已绑定草稿不得手动删除；修订使用 `state.revise` 和原有发布入口。未变镜头保持原绑定、文件和修订号，按现有复用判据继续使用。只清理本次产生且确认未被正式计划或恢复事务引用的失败草稿。

**失败渲染可重试**：执行器对 crashed/failed 状态的事务直接重渲，不再被旧日志阻塞。

## 已验收默认规格

每个新 Job 先读取 [默认制作配置](references/production-defaults.json)，将其作为本项目后续口播的默认起点：1080×1920／24fps、新 Job 首镜固定使用 `lemo-wake:wake` 并从第 0 帧开始、无背景音乐，以及浅暖色／深墨字／清晰大主字的 A-roll 贴片。已批准封面 PNG 另作平台封面；首镜隐藏 presenter，不传 avatar。现有成片保持不变。统一的是配色、字体层级与可读性，不是卡片形状。`card_family` 只供实际卡片组件参考，不覆盖所有原生组件的尺寸、圆角、背景或构图；主字 64px 是阅读起点，不把说明文字和图形全部改成同一字号与字重。默认值不从旧 Job 的 HTML、文案或人物坐标反推。用户本次明确提出不同要求时才覆盖相应选项；新任务的授权、封面和制作完成核查仍须绑定本次实际记录。

这是宿主编排输入，不是新的动效模板或第三方 props。主控读取配置后，按现成组件公开槽位和自有静态版式传入贴片样式；按[封面入场合同](references/cover-opening-bgm.md#正式封面入场接口)把 Wake 编排为正文首镜，预览显式传 `opening=None`。新 Job 的 Wake 首镜从第 0 帧开始，原声、字幕和编号 1 保持同一时钟；不叠加旧的 6 帧静态封面前贴。不迁移或重签旧 Job。不将整个配置塞进 provider、ShotRecipe 或上游 brief 的未知字段，不修改第三方，不新增渲染器。首次预览漏传既定开场策略是编排缺项。

字幕继续使用[唯一字幕样式](references/subtitle-style-contract.md)，B-roll 保持圆形人物小窗、语义优先的动态画面与多样性，按[视觉质量合同](references/visual-quality-contract.md)安排密度；首次清理即处理自然停顿。`speech_cleanup` 自动检查实际保留的长间隔及中断重说；宿主消费返回的 `cleanup_checks`，核听并剪除口误，必要强调或呼吸按当前候选逐项记录保留理由，再继续成片，不新增用户确认门。默认值一并放入本 Job 的常规配置说明，不逐项新增确认门；不复制历史批准或为采用默认值重做已验收视频。

只优化 A-roll 贴片时，不替换或挪动既有 B-roll。代表样片按[贴片选段检查](references/aroll-overlay-contract.md)先对照原已批准计划，确认窗口本来就是 A-roll；不能因为底层仍有原片，就把 B-roll 时段重新导出成人物贴片。已验收整片保持原样，样片另存。

启动 Job 时只完整阅读：

- [依赖预检、确认与安装合同](references/dependency-preflight.md)
- [十二阶段执行合同](references/stage-contracts.md)
- [每任务工作区与用户资料合同](references/job-workspace-contract.md)

其他参考只在对应阶段加载：

- [9:16 视觉质量合同](references/visual-quality-contract.md)
- [动效文字实际字号与可读性](references/motion-text-readability.md)（所有渠道的贴片和B-roll；整表确认前冻结文字位置和阅读时窗，制作时逐项自动检查，失败先内部修正）
- [统一头肩头像参数与校验](references/avatar-profile.md)（从 `visual_direction` 起，任何 B-roll 使用小头像时）
- [B-roll 语义能力路由](references/broll-capability-router.md)
- [统一动效能力库：理解、标签、检索与编排](references/motion-capability-library.md)（所有贴片与 B-roll 选型前；统一能力描述，不合并执行资格）
- [CutCod / Riso 原生信息动画](references/cutcod-riso.md)（数字、数值对比、归类、集合关系、选项、步骤、资料与结论；只改公开 DATA 内容槽）
- [语义动效规划接口与执行边界](references/semantic-motion.md)（关系图或五类状态动效进入候选时）
- [B-roll 开源能力适配矩阵](references/open-source-adapter-matrix.md)
- [上游场景 Skill 与本地渲染合同](references/upstream-scene-skills.md)
- [Lemo 原生 Skill 的 59 种风格模板](references/lemo-opuscar.md)（选中 Lemo 后读取，按具体 STYLE 制作当前主题）
- [OpenFilm 原生 motion-graphics 创作与验收](references/openfilm-motion-graphics.md)（选择主题专属主体动作、物件操作或信息探索场景时）
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
- [Overlay Studio 原生要点钉板](references/overlay-studio-pinboard.md)（语义适合逐项落板的短要点时）
- [Motion Graphics Native 自写纪律动效贴片](references/motion-graphics-native.md)（下横栏、标注引导或品牌贴片进入候选时；每期现写 HTML，非现成模板）
- [Huashu 原生数值贴片](references/huashu-stat-overlay.md)（口播包含一个确切数值、适合计数强调时；不是同名 Huashu Art B-roll）
- [权威素材使用回执与变更事务](references/material-usage-contract.md)（新增、替换或撤回用户资料时）

默认封面入场与可选 BGM 使用正式 `preview_v2.prepare_preview_v2(job, opening=..., music=...)`，参数、统一时间偏移、许可和审计附件以封面入场合同为准。每个新 Job 均加载该合同；只有用户本次明确取消封面入场，才省略 `opening`。默认无 BGM；启用时仍需本次选择和真实试听批准。其他机器缺少运行时时读取 [运行时部署](references/runtime-deployment.md)，先导出、校验、安装兼容代码，再执行依赖预检；不复制多个活动 Skill，不迁移旧 Job。

## 1. 新 Job 的连接检查与唯一目录

每个新视频都必须重新执行一次：

完整包使用随附固定版本的来源，首次准备恢复包内来源身份。上游升级属于维护和重新发布，按[包内来源与更新](references/dependency-preflight.md#包内来源与更新)执行；普通 Job 不自动更换已冻结来源。

先选定一个 Python，用唯一准备入口 `<python> <skill>/scripts/project_python.py --project-root <project> --prepare`：先校验完整 Skill 包，再按依赖清单准备缺失的基础环境；本次选型后只准备并检查所选组件。主环境必需 Pillow、requests、NumPy、OpenCV；缺包按清单兼容版本装入本项目 `skill-development/runtime/talking-head-python<major><minor>`，已有可用包不重装或升级。第三方专用环境调用已有准备入口，并清除主包路径的注入。安装或复检失败即停止，不循环修复。随后项目主流程统一使用 `<python> <skill>/scripts/project_python.py --project-root <project> -- <正式脚本及参数>`，保持同一解释器及调用者工作目录。不另写临时复检脚本，不改全局 Python 或 shell。

准备入口直接编排 `ensure_punk_cover.py`、`ensure_visual_broll_skills.py` 和已有原生运行时准备函数。唯一清单的 `preparation` 登记可执行准备，条目的 `dependency_ids` 关联实际所选组件；没有该字段的必需条目用于基础准备。`runtime_checks` 只检查本次所选组件；不遍历研究目录，不把账号或生成服务当作安装项。没有准备入口的缺失环境明确停止，不现场另造安装器。运行时探针通过只证明可调用；具体镜头仍在选型后检查实际配方绑定。

原生入口需要固定工具版本时，由清单 `preparation.node_tool` 在项目 runtime 准备，并通过统一入口传给子进程，不降级全局工具。Hypit 的 pnpm 与源码声明保持一致；失败记录包含命令和安全错误原因，保留旧记录后停止，不自动重跑。

GBRO 启动检查只核对固定源码和说明；本 Job 的图片与视频渠道由用户在启动配置中分别确定，选中后按该配置执行静帧与动态生成。不得把内置生图、Lovart 或任一 provider 写成全 Skill 默认；约束见[GBRO 编排](references/generated-broll-skills.md#gbro-调用约束与拼贴验收)。不因环境准备自动替换已批准 B-roll。

Lemo、OneTake、Wise、Huashu、Adu、Hypit 等可选能力只在本次选中后准备；缺失时调用已登记的原生准备能力，并检查实际配方绑定；准备成功不是出片验收。详见[上游场景 Skill 与本地渲染合同](references/upstream-scene-skills.md)。Skill 源码更新按上述更新规则执行；不得全局安装、顺带升级 Python/Node 等环境，或运行自动 reset/setup。

OpenFilm 同样在选中后纳入唯一准备入口和运行检查：补齐项目内缺失包及其原生浏览器，不改系统环境；检查真实 `motion-graphics/SKILL.md`、手册及运行时身份。准备和预检不打开生成服务、不读取服务密钥、不调用 `get` 或生成素材。现有版本不符时停止，由宿主按更新规则检查接法，不能在渲染中下载或切换版本。

选择 Huashu 原生动效时，先读[Huashu 原生动效接入](references/huashu-native-motion.md)：由我们的 adapter 实际调用固定 vendor 的 `render.py --spec`，不修改第三方源码、模板、字体或动效。三条已登记路线、容量、输入版式与避让、启动器与子进程环境边界以该页和[正式生产绑定](references/production-bindings.md)为准；普通 Job 只消费已登记能力，不重复资格实验，未接通或验收失败时暂停对应路线，不自动修改第三方、重试、切换或加入自写 fallback。

Adu 准备只涉及本地渲染环境，不调用人物提取、配音或 mix。选中后必须通过其独立 binding probe。

新的 Adu 仅调用公开 `TPL.compare` 对比组件，人物、普通字幕与品牌通过原生配置关闭；Playwright 放在我们的项目 runtime，不改第三方锁文件。它的固定横版画板只可整板等比放置，不当作原生竖屏整屏模板。选中“对话改变计划”语义时，执行同一脚本的 `--skill hypit-native-chat`，读取其原生 Skill 和 chat-scene 指引，以原生消息入场/滚动场景出片；仅静态竖屏排版由父级完成，不另写动作。两条入口、容量、精确帧写法和使用限制见[上游场景合同](references/upstream-scene-skills.md)。TalkCraft 原生适配入口继续可选；108 张生产资格卡保留原始资格和素材，但当前包缺少对应生产适配器，统一标为 `needs_adapter`，不进入新计划确认。

已有 Adu/Hypit 制品需复用时，按[原生制品复用接口](references/upstream-scene-skills.md#已完成原生制品复用)调用 `create_existing_adapter`，不调用普通生成入口；复用失败直接停止，不自动重做动效。两条已通过公共执行与圆窗、原声、唯一口播字幕的合成检查，但仍是受限组件，不代表本期语义或用户效果批准。

1. 取得视频绝对路径、文案文件绝对路径或聊天中的完整文案，以及用户提供的图片、视频、音频和文档。
2. 用已选 Python 执行上述唯一准备入口。包校验失败、异常目录、版本不一致或安装失败时保留现场并停止，不重签发布清单掩盖缺失。项目内官方视频下载 Skill 及固定提交仍按[官方视频下载合同](references/official-video-acquisition.md)核对；只有实际选择在线素材时才获取媒体。TalkCraft 生产运行时由正式预检的 `check_runtime.py` 检查，它必须确认精确依赖、运行时闭包、渲染器、卡片索引、上游基线和字幕入口。生产运行时属于 108 张资格身份，不得用上游共享 runtime 自动覆盖或升级。
3. 运行 `scripts/initialize_video_job.py`，创建 Job isolation 所需的独立 workspace、去重后用户资料、`full-v2` workflow 和唯一输出树。`--script` 接受 DOCX 或 UTF-8 文案；DOCX 自动保留原件，并将按顺序提取的正文绑定为纯文字主文案。格式错误或正文为空时，在创建目录前停止，不把 Word 二进制文件直接绑定到剪辑入口：

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/initialize_video_job.py \
  --project-root <project> \
  --jobs-root <project>/video-jobs \
  --title "<本期标题>" \
  --video <absolute-video> \
  --script <absolute-script> \
  --user-file <optional-material>
```

4. 将上次 provider 配置作为待确认草稿写入本 Job 的 `manifests/provider-config.json`，格式见依赖预检合同；同时在本次常规配置说明中列出已读取的默认制作规格，不给 provider 文件添加未知字段。不复制上次批准记录，不保存密钥。没有历史 provider 配置时根据本次实际能力填写，不虚构内置视频模型；制作规格仍从本包默认配置取得。
5. 经 `project_python.py` 用同一个已选 Python 直接运行 `scripts/dependency_preflight.py --manifest <skill>/references/dependency-manifest.json --project-root <project> --job-context <workspace>/job-context.json --output <job>/manifests/dependency-preflight.json --summary-only`。检查全流程基础必需依赖；可选模板在本次选型后、整表确认前准备检查；本地缺失环境按预检合同安装，随后只复检一次。失败报告由正式入口保存，不用临时包装或手工覆盖。TalkCraft 运行时健康检查是必需项，须在这里重新执行并通过，不能仅凭步骤 2 的人工运行记录放行。区分发现/安装、`configured`、`connected`、`callable`、`bound`；安装失败、目录冲突或账号缺授权时停止。预检不执行媒体生成。
6. 一次展示本 Job 实际选择的生成用途及渠道、精确模型、endpoint 标识、参考图能力、原生 9:16、无声输出、连接证据、额度、并发，以及实际 Python、项目路径和合成器版本，询问是否修改。允许只选图片、只选视频、两者都选，或明确不生成；图片渠道用于封面、生成图片和模板内部图片步骤，视频渠道用于直接生成 B-roll 和模板内部视频步骤。仅使用官方素材和本地动效不要求开启视频生成。只有已选用途需要完整模型与输入绑定；后续路线需要未选用途时先说明具体缺口并取得对应配置授权，不自动补渠道。用户确认后调用 `scripts/confirm_job_setup.py --job-context <workspace>/job-context.json --user-confirmation "<本次确认原文>"`，记录 `manifests/setup-approval.json`；成功才进入 `inspect`。不得用测试文本或过去的“确认”代替本次批准。
7. 渠道不绑定固定品牌或工具；用户选择的精确模型 ID 必须逐字保存并在每次请求前复核。后续 provider 请求前仍复核真实连接与额度，预检成功不等于付费生成授权。

`job-context.json` 还记录 `skill_release` 及真实 `runtime` 身份。初始化在创建目录前验证发布包及模块来源；`state.require_runnable` 对 Skill 管理的 Job 强制检查当前包、运行时、Job 绑定预检和配置批准。恢复同 Job 时复用未变化的批准；报告超过 24 小时需刷新，配置不变不重复询问。项目/解释器/源码/Skill 身份变化必须先做明确迁移，不能静默重写上下文或重做已批准素材。裸状态引擎测试不走此门，不能作为 Skill 的启动捷径。

输入缺视频或文案时，只询问缺失项，不猜路径。内联文案通过初始化器的 `--script-stdin` 或 `--script-text` 代替 `--script`：初始化器直接在新 workspace 内保存 UTF-8 原文并建立索引，不要求先存在 Job，不把输入写入 Skill 目录。长文案优先通过 stdin 传入，使用宿主参数数组/输入流，不将原文拼接进 shell。

初始化发布 workspace 时已写入 `initialization.json`。若后续初始化中断，使用同一 Python 执行 `scripts/initialize_video_job.py --resume-workspace <workspace>`，不再次使用新建参数。它只复用导入字节和同一 workflow，原件移走也不重新复制；运行时/发布身份变化、损坏文件或非空事务残留会停止并保留现场。已完成 Job 不自动补造丢失 workflow；没有恢复记录的历史 Job 不适用这个入口。具体边界见工作区合同。`workflow.json` 是唯一状态事实，不得手工修改。

## 2. 十二阶段与确认策略

产品顺序固定为：

`inspect` → `content_analysis` → `cover_direction` → `cover` → `speech_cleanup` → `edit_structure` → `visual_direction` → `visual_canary` → `visual_assets` → `subtitles` → `preview` → `delivery`

一次只运行一个正式 runner。主控先统一文案、时码和镜头风格分配，再允许最多 3 个子任务并行准备不同镜头的方案、素材与只读检查；子任务不得修改 workflow、正式清单或批准记录。图片和视频生成共用当前 Job 的 2 个名额，具体领取、响应保存和恢复见[有界生成编排](references/production-bindings.md#有界生成编排)。每次正式动作前重新 `load_job`，按产品顺序找到最早未完成阶段；它必须是唯一候选，且依赖全部 `approved`。候选缺失、不唯一或状态不一致时记录当前状态并明确停止。每个 runner 仍必须先发布到 `ready_for_review`，再由确认策略完成内部校验和推进。

默认采用“结果确认”模式：用户确认 Job 配置、付费/外部账号动作、不可逆素材变更、封面方向/实际封面，以及剪后完整视觉清单；视觉清单确认后，canary、资产、字幕、预览和交付只要确定性校验、绑定校验和本地 QA 全部通过，就由宿主自动批准并继续，不逐阶段打断用户。若用户明确要求查看某一阶段，或 QA 出现歧义、视觉明显偏离、素材/模型/费用选择发生变化，才暂停等待确认。自动推进不等于跳过 runner、哈希、回执、事务恢复或交付审计。

同一视觉清单只报审一次：记录已展示的 routing 身份及用户反馈。后续只变更执行记录、时码校验、编码或其他不改变整表选择的技术证据时，内部验收并继续，不再次发送同一视频或索取确认；用户主动要求重看除外。开发样片的认可不得冒充正式 Job 的整表确认。

内部检查不是新的用户审批门。对已经定位、只影响本地登记且不改变图片、文案、时码、来源、费用、授权或校验规则的输入格式问题，宿主保留原始输入和失败记录，在现有授权内规范输入并继续；例如封面提示词文件末尾的 CR/LF。不得为这类问题反复索取“允许修正”，也不重跑已完成的生成。原因不明、会改变成片或需修改代码/环境/外部请求时仍先分析并按实际范围处理，不借格式修正放宽规则或自动重试收费请求。

视觉清单只确认一次：宿主在 `visual_direction` 输出完整 `visual-routing.md` 后展示整表，收到用户确认后才执行已冻结的视觉计划。之后宿主完成 canary、资产、字幕、预览和交付的实际 QA，直接交付；不再向用户请求样片、字幕、预览或成片确认。不得把整表确认伪称为用户看过成片，也不得将旧版本的认可绑定到修订后的视觉清单。

封面分别记录 `cover_direction` 的内容与设计方向批准，以及 `cover` 的实际图片批准，不能用“只确认方向”冒充图片批准。用户已明确认可本 Job 唯一可追溯的完整图片时，记录该次原话和图片身份，完成内部发布检查后推进，不因正式文件登记较晚就要求再确认同一张图；无需用户重复发送审批口令。内部检查只证明复用的是同一张图，不重新征求样式意见。文案理解、重点和关键词只在 `content_analysis` 决策一次；下游不得重新提炼或询问同一问题。
用户反馈“关键词、A-roll 贴片或 B-roll 太少”时，先从正式预览按内容章节量出高亮分布、贴片/B-roll 位置与累计时长，再逐句找未被可视化的语义机会。关键词源头漏项修订 `content_analysis`；镜头稀疏修订 `visual_direction`，并遵循状态级联，不能只在最终预览上叠几个临时元素或以固定数量代替语义判断。执行与验收分别遵守[字幕样式合同](references/subtitle-style-contract.md)和[9:16 视觉质量合同](references/visual-quality-contract.md)。
用户同时指出样式同质化时，扩展的是本期可实际调用的原生组件候选，不是把已接通的两张图重复插入。按[画面多样性](references/visual-quality-contract.md#画面多样性)比较全片及最近两个增强窗口的主体、构图和动作；充分表达台词、实际质量相当的候选优先选不同家族。已明确否决的本期效果不自动复用，但不因此禁用整个上游 Skill。现成组件只缺竖屏、透明输出或文本槽交接时先做薄适配，不能把“还没有 adapter”误判为上游没有能力。
用 `scripts/audit_visual_coverage.py --visual-plan <当前visual-plan.json> --subtitle-plan <当前subtitle-plan.json>` 输出每 20 秒的实际口播、高亮、贴片和 B-roll 分布及贴片时窗里的真实台词；逐项核对后才决定修订范围。该报告只定位缺口，不用数字代替语义审片。贴片时机、美观度或字幕碰撞被用户指出时，旧预览直接判未通过；先用带原声的代表样段验证词锚、真人避让和入／中／出画面，再重渲全片，不重复报审未发生观感变化的旧视频。
本期要求 A-roll 贴片时，上述命令必须加 `--require-overlays --content-analysis <当前content-analysis.json>`，并与正式 `preview`／`delivery` 入口置于同一条成功后继续的调用链；零贴片时失败，不启动导出。字幕高亮不算贴片。报告中的 `needs_review_items` 是重点内容的人工取舍清单，不是每项必加动画：逐项决定补充现成组件或写明保留真人的具体表达理由，记录在现有本地 QA 中。组件尚未完成、入口没接好或素材未取得是制作缺口，不能改写为已完成的纯口播选择；无法补齐时说明缺口，未经用户同意不缩减交付。这个检查约束宿主编排入口，不宣称所有直接调用运行时的路径都已自动受保护。
本项目默认采用较密、均匀分布的 B-roll 节奏，具体安排遵守[视觉质量合同的密度规划](references/visual-quality-contract.md#b-roll-密度规划)。盘点时同时检查首个 B-roll 时间、累计占比和最长无 B-roll 区间；A-roll 贴片不能截断这项空白统计。用户要求重新安排时先保存本 Job 的逐镜时间、对应原声、画面动作及上游调用方案；未完成来源绑定的安排明确标为待制作，不冒充已编译或已渲染的 VisualPlan。
新一期封面须从本 Job 已批准的内容重点生成新的画面创意：重新设计人物动作、主题隐喻、道具和场景，只继承已通过样例的标题层级、对比度与视觉完成度。样例是风格参考，不是可替换标题和人物的底图模板；生成候选前按[封面标题视觉样式合同](references/cover-title-style.md)绑定本期人物来源、逐字标题与主题动作，并用实际新图验证，不能把复制旧图或本地套版当成自动生成通过。
用户认可的是完整带字封面时，锁定那张 PNG 的 SHA-256，正式 `cover` 直接原样复用，不生成或要求无字底图，也不让模型重画、本地叠字；封面不制作或展示缩略图，只展示正式尺寸成图。已认可成图的文案与旧方向记录不一致时，先把方向修订为成图中的逐字文案，再发布同一张图，不生成“相似版”。只有用户认可的仅是构图方向、尚未认可实际成图时，才可选择无字底图加本地排字的候选流程。

到达 `cover_direction` 和 `cover` 时完整阅读封面输出与质量合同。

封面生成前必须依次完成三个用户确认门,缺一不可:
1. **文案确认**:向用户展示封面主标题(4-8 汉字,必须能追溯到已批准内容分析)、副标题和视觉概念摘要,问"这个标题和方向对吗?"——用户确认后才进入下一步。
2. **画面确认**:向用户描述画面将包含的元素(人物动作、核心道具、背景场景、色彩方案),问"画面这样安排行不行?"——用户认可后才进入下一步。
3. **生成授权**:明确告知将调用的生成服务、精确模型和大致费用,问"是否授权这次生成?"——用户授权后才发起付费请求。
预检中无已配置图片生成 provider 时,在文案确认前就停下来询问用户使用哪个服务;不得自行切换到 Job provider 体系之外的工具。封面提示词必须包含丰富的视觉元素:核心道具(与标题语义有物理隐喻关系)、有层次感的背景(非纯色留白)、人物叙事动作(让观众第一眼看出标题含义)、至少两次图文穿插换层(标题字与道具/人物在空间中前后交错,不是字体贴在照片上)。9:16 真人知识封面优先读取项目内 `skill-development/vendor/Punk-Skill/skills/punk-cover/SKILL.md`，按其单一 `interleaved-title-editorial-poster` 风格编排本期文案、人物参考、主题动作和完整候选图；保存实际提示词、候选图及来源，不把手写提示词冒充子 Skill 调用。已批准的比例和文案优先于子 Skill 默认值，人物可与标题发生不影响识别的发丝穿插，五官和叙事手部必须清楚。原 `gbro-cover-design` 仅用于无字底图加本地排字的候选链路；Punk 完整带字成图经正式 runner 原样发布、像素核对和 `cover` 人工门通过后才称为正式封面，不为发布补造无字底图。
Punk 实际方向候选须存入本 Job 独立的 `punk-assets` 目录，并调用 `prepare_cover_direction(..., direction_preview=...)` 原样发布；不得用旧主题固定示意图代替本期语义。

`speech_cleanup` 的字级转写能力归属 `video-use`：先读其 `SKILL.md`，经本次音频上传与额度许可、凭据就绪后，从本 Job 预检绑定的 `video-use-runtime.resolved_path` 实际调用 `helpers/transcribe.py <源视频> --edit-dir <本Job工作区/edit>`。以预检发现的 `video-use-skill.resolved_path` 为进程工作目录，使上游 helper 读取该已安装 Skill 的私有 `.env`；若凭据来自安全注入的进程环境，也可直接使用，不复制密钥到项目。调用前确认输出路径未被其他源素材的缓存占用；记录入口绝对路径、退出码、源视频 SHA-256 和原始 JSON SHA-256。再将原始 JSON 路径与这四项调用证据传给 `transcribe.transcribe_job(job, video_use_result=..., invocation=...)`，由项目适配器校验时码、保留原始响应、对照文案并制作清理提案。没有许可、凭据、真实调用或可验证输出时停在此阶段；本地 Whisper 不能替代 `video-use` 的正式转写。

转写错字默认以本期原稿为校对依据，由宿主自动纠正，不询问用户逐字选择。使用[转写文字校对接口](references/stage-contracts.md#转写文字校对)，保留原始 ASR、词数量和时间点；不把原稿未实际念出的整句补进字幕，也不靠改字掩盖原声口误。

本地二次复核已有真实原始结果时，先按[辅助转写按句复用](references/stage-contracts.md#辅助转写按句复用)读取，不为缓存读入失败重新识别。句段结果明确标为 `segment`，只用于找疑点；不伪造词时码，不自动删除重复，剪切位置仍须回原声核对。没有保留原始结果时说明缺口，不自动重试。

默认在首次 `speech_cleanup` 就完成[句间停顿与自然衔接](references/stage-contracts.md#句间停顿与自然衔接)，再安排贴片和 B-roll，不等用户指出长空白。常规口播保留自然换气，适当收紧拖长的句间等待；不整体加速、不机械清除所有静音，也不把单条视频的剪点套到下一条。已出片后的停顿返修按[停顿返修后的时钟对齐](references/visual-revision-reuse.md#停顿返修后的时钟对齐)保留当前封面、贴片和 B-roll，再调用原有剪辑与合成入口。

## 3. 批准、修改和 blocked

每个 runner 先发布到 `ready_for_review`。配置、封面与 `visual_direction` 的整表确认由用户决定；其余阶段由宿主实际审查后内部批准。剪后报审只展示完整表和需要用户判断的问题，后续制作不逐阶段播报或索取确认；发生阻碍时简要说明影响及必要选择。

暂停阶段需要用户确认时，才执行：重新加载 → 验证唯一 `ready_for_review` → 只 `approve` 该阶段 → 再加载并验证提交 → 有下游时只运行一个下一阶段。结果确认模式的自动批准必须记录本地 QA、产物哈希和自动批准原因，不得把自动批准写成用户确认。`visual_direction` 的整表确认回执覆盖后续 `delivery`。

`visual_direction` 使用视觉计划批准入口保存当前 revision、完整 `visual-routing.md` 身份、`approval_scope=visual_plan_and_delivery` 和本次整表确认原文；具体参数及中断恢复见十二阶段合同的“视觉计划确认入口”。后续 `delivery` 只保存宿主 QA 与实际交付身份，不能把它写成用户成片确认。

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

选型前先查询[自有动效能力库](references/motion-capability-library.md)，同时理解贴片、B-roll、组件及设计／原生创作入口。能力以当前生产入口的真实动作和实际可改字段为准，不以原 demo、Skill 名或静态人物素材推断。先理解整篇口播，再检索动作／关系短语；标签只召回候选，不裁决语义。宿主在既有 treatment 的 `semantic_assessments` 引用完整当前台词、必要已说上文和实际绑定内容，说明直接表达、摘要或隐喻是否成立；不靠选择理由、创作要求或关键词自证通过。OpenFilm 引用本条冻结场景，不套用通用能力描述。B-roll 的 `discover.capability` 是当前能力描述；来源摘要变化即复核受影响档案，不因 adapter 版本号未变而沿用旧标签。正式视觉发布前，同一离线检查验证引用并调用各已登记接法的原生输入校验，区分明确失败、缺证据待审和离线通过；未通过在冻结和发布前停止。检索不命中不是错配，原生输入通过也不证明语义或画面通过。库中未接通或已停用条目不能直接执行；原有选型、词锚、透明输出、来源资格与实播验收全部保留。不修改第三方、不授权重写动效，不迁移、补写或重新验收已通过视频。

B-roll 默认追求高有效信息密度，区别于全片的插入频率和时长占比。调用上游制作前，把本句的关键对象、核心动作、关系变化及必要上下文拆成可见语义拍，随真实词锚交给子 Skill；不能只给关键词和画风。按[单镜信息密度](references/visual-quality-contract.md#单镜信息密度)规划和检查，既不漏掉关键动作，也不靠堆文字、装饰或重复字幕凑信息。已认可的交接表达可作为动作设计参考，不把其道具和构图固定成所有 B-roll 的模板。

痛点句还要表现问题给人带来的实际困扰，按[痛点场景与人物感受](references/visual-quality-contract.md#痛点场景与人物感受)把受影响的人、反复操作及负担变化交给所选上游。美观、语义和主体动作须同时成立；只让资料卡片飞入或让人物静坐在旁边不算表达困扰。此要求适用于所有候选 Skill，不把本次桌面、人物插画或扶额动作设成固定模板。

制作上游接入样片时也遵守这项交接：先核对真实内容槽、原生动作、用途和时长，再形成 binding；不能手工指定一个易执行的组件后，把原意图削成泛化状态。检索排名只是候选，须核对否定、因果及未覆盖要求。局部组件、整屏场景和生成服务的边界，以及调用测试与视觉验收的区别，见[上游场景 Skill 合同](references/upstream-scene-skills.md#候选能力与内容交接)。

遇到概念拆解、分类和层级关系时，也匹配[思维导图与分支关系动效](references/generated-broll-skills.md#思维导图与分支关系动效)：优先核对 HyperFrames 现成决策树/中心关系入口，手绘方向调用 Doudou 真实组件。静态导图和交互网页不是动态 B-roll；候选登记不等于已出片或正式接通。

选择 Doudou 后，先按[原生手绘制作交接](references/generated-broll-skills.md#doudou-项目内调用)执行上游场景制作：把主体对象、构图、绘制动作与当前词锚交给制作阶段，实际使用其画布、笔刷或绘图算法，而不是先拼普通 CSS 框图再加箭头。本项目手绘默认使用原生 `RealHandFollower` 与已冻结的透明握笔图，不能把孤立铅笔当作真实手部。随后使用 `scripts/doudou_adapter.py` 冻结本期场景和手图并交给统一组件执行器；不另造白板模板或动画引擎。父级仍统一合成圆形人物小窗与唯一字幕轨。批准过的视觉方向不重复报审；改变语义、来源或配方时才进入相应修订流程。

新计划充分使用现成 B-roll 能力：父 Skill 只做语义导演、镜头编排、批准门和最终合成验收；制作前完整读取并实际调用所选上游 Skill。先筛出语义、质量和执行条件合格的候选，再按[画面多样性](references/visual-quality-contract.md#画面多样性)在全片尽可能组合不同来源渠道、不同模板及不同构图和动作；不必等到机械分数完全相等。优先组合现成能力；只有记录真实能力缺口后才允许最小新增实现。使用依赖时如实写 `producer_type=dependency` 与 `dependency_id`，另记复用能力与新增实现；`custom_fallback / structural` 是适配资格，不等于自研，也不冒充第三方整屏模板。Lemo-Opuscar、OneTake 使用项目内固定提交。HyperFrames 透明贴片/轻组件、TalkCraft 精确数据、Doudou 白板/思维导图、Paper 分层拼贴及本 Job 已确认的视频生成渠道保留各自边界；prompt 库不是制作依赖。入口与验收见[上游场景 Skill 合同](references/upstream-scene-skills.md)与[生成型 B-roll 编排](references/generated-broll-skills.md)。

调用前区分现成模板、创作工具包与生成服务。Lemo 是原生风格创作工具包，不是填词导出模板：父级交付语义、真实词锚、时长、圆窗/字幕避让和相邻镜头外观，不先锁定“三卡片＋箭头＋圆点”。按其 DIRECTOR → 本期 treatment → STYLE/DEMO 技术学习 → 原生制作流程，让上游设计主要视觉动作；本期场景代码如实记为结构改编。美术质量看真实原尺寸画面与全速动作，多样性看实际构图和运动，不能用不同 Skill 名、函数引用或渲染成功代替。具体交接与审阅见[上游场景 Skill 合同](references/upstream-scene-skills.md)。

五类来源（`local_material` / `official_material` / `code_generated` / `external_stock` / `ai_generated`）同级：无优先级、无配额、禁跨类替换，`external_stock` 与 `ai_generated` 是主动语义选择而非替代项。权威策略块与字段定义唯一维护在 [B-roll 语义能力路由](references/broll-capability-router.md#唯一选型入口与记录)，此处与各合同不再复制正文。

选型前先读完整语义段落，解清人物指代、动作、否定、对比和前后因果，再限定当前时窗实际说到哪一步。交给子 Skill 的画面任务必须同时包含上下文、当前口播和不能提前出现的后续结果；不只抽“小调研”等关键词配图。先验收画面是否准确表达当前这一步，再看画风和动画；黑白变彩色等显现效果不等于叙事动作已经成立。用户指出语义不符后撤回该片段的语义通过状态，保留技术证据，修订后重新看实际成片；美观认可不代替语义认可。

抽象结论不强求 B-roll。候选在正常播放速度下须让人从可见对象、动作和必要的简短标签看出本句的具体变化；若必须听创作者解释“这个道具象征什么”，就先判语义不成立，选择 `mode=none` 保留真人 A-roll，等后文讲到可直观表现的具体动作再切 B-roll。不能为了保留已生成素材，把后文的动作或成果提前塞进当前时窗；静帧美观、视频确实在动、媒体参数通过都不能覆盖这项判断。冻结计划前沿全片口播逐段核对已批准的具体论点、可视化动作及对应时窗，不能只为中间几个现成素材留 B-roll。列出开头、中段、结尾实际 B-roll 时窗及最长连续纯 A-roll 时长；若某个完整语义章节一直没有 B-roll，先找能直观呈现的原声动作句，确实没有再记具体理由。预览验收以真实画面的全片分布为准，片段存在、计数通过不等于观众能感知到 B-roll；不设脱离语义的片段配额。

本项目要求动态 B-roll：主体须有与本句相关、可辨认的动作或状态变化。仅静图推拉、擦除、上色、淡入淡出或粒子装饰不满足要求，即使文件是 MP4。选型先核对现成 Skill 的具体入口能否完成所需动作；只能生成插画或显现效果的入口可用于准备素材，但不得单独作为动态成品。优先编排能完成动作的现成能力，按[生成型 B-roll 编排](references/generated-broll-skills.md)验收动作前、中、后；图生视频模型及费用变化仍须确认，不能因尚未授权而静默交付静图动效。

检索前先读当前 Job 已索引的用户资料，避免重复下载或生成相同内容；这是检索去重，不改变五类来源的语义平等地位。

- `local_material` 从当前 Job 的 `00-user-provided/material-index.json` 绑定少量用户图片、视频或文档。
- `official_material` 绑定第一方图片、视频或页面记录，保留来源、人物职务和内容真实性检查。选中在线视频时先读官方视频下载合同，实际调用项目内 `video-download` Skill；只取得页面、字幕或下载命令不算已获取视频，必须核对本地视频的画面、声音、时码、哈希及适用清晰度。
- `code_generated` 调用现有依赖 Skill，按 ShotRecipe 执行，并保留 Skill 调用证据、`dependency_id`、`entrypoint` 和 `producer_version`。
- `external_stock` 根据语义检索经批准 provider，保留许可记录、作者、来源 URL 和下载身份。
- `ai_generated` 是主动语义选择；它绑定 provider、精确模型、参考图和 generation identity。复用 Lovart 已完成视频时，按[生成型 B-roll 编排](references/generated-broll-skills.md)先调用 `prepare_existing_binding` 核验并准备绑定，再编译、正常批准和执行；不手改配方、不重新生成、不改标为本地资料。竖屏无声 AI 动态 B-roll 源视频可为原生 720×1280/24fps，配方按实测源尺寸编译，合成后仍须达到 1080×1920/24fps；不把放大后的结果称为原生 1080p。其他尺寸的单条补边例外须绑定原视频、派生视频和已确认预览的摘要，不扩展到其他素材。

AI 动态 B-roll、封面及模板内部生成统一使用本 Job 启动时确认的图片/视频渠道；具体模型按本 Job 的能力、费用和批准配置确认。Flat/GBRO 等上游只提供视觉方案和入口约束，不得覆盖已确认渠道，也不得把某个服务写成默认备用路线；渠道不可用时停止并回到原方案修订。

需要生成型画面时，按[生成型 B-roll 编排](references/generated-broll-skills.md)在 Whiteboard、Paper Collage、Flat Animation、GBRO Collage 等现成 Skill 中按语义选型，再检查实际可执行入口与适配缺口；不因单次样片失败排除整个 Skill，也不因已接通某条路线就统一选它。优先调用上游已有配置与能力，缺口才做最小适配，并实际出片验收。Paper 分层入口与 Whiteboard 原生 SVG 分组入口已分别通过该页的 `paper_collage_adapter`、`whiteboard_adapter` 接入公共组件执行器。Flat/GBRO 仅负责其视觉方案和静帧阶段，视频统一由本 Job 已确认的视频渠道生成并由匹配适配器验收，不能把视频产物记作这两套上游的原生视频调用，也不把某个服务写成默认路线。原生 720p AI 视频不因分辨率被排除，但本次实际出片及当前片段语义/画质仍须真实验收。已接入入口也不是通用已验证模板，每段仍须检查语义与美观。图片生成与动画来源分别绑定，子 Skill 只产出无声整屏镜头，圆窗、原声和全片唯一字幕轨仍由父级统一处理；不跨已批准来源类型替换，不绕过执行与确认门。

冻结前必须先完成跨 Skill 的两轮规划。第一轮从当前原声的对象、动作、关系、变化和禁项出发，使用 `scripts/select_broll_skills.py discover --project-root <project>` 查看用途符合的真实入口，评审各 Skill 的具体候选；缺适配与语义不适用分开记录。语义与美观相当时保留同档候选，不因熟悉某个 Skill 就提前设为唯一首选。第二轮把新增及复用镜头放回整片，参考相邻镜头及最近两条成片，按真实主体、构图和动作减少重复，再创建所选绑定。候选准入、同档选择与 `visual_pattern` 的统一口径见 [B-roll 语义能力路由](references/broll-capability-router.md#唯一选型入口与记录)。不设来源配额，不随机轮换，也不要求机械分数完全相等。原生组件保留自身版式与动作，父级只负责协调配色、静态放置、圆窗、字幕及安全区，不统一改成“大标题＋卡片”。具体入口和分工确定后才制作；费用授权仍按原门禁处理。

OpenFilm 在同一候选池中表示“按本句语义创作”的一种能力，不默认优先，也不将获认可的手机、放大镜、信封、色板或构图固定为模板。先确定主体和实际变化，再选择适合本句的视觉语言；与相邻镜头风格协调不等于全片同形。当前只接整屏无声 B-roll，不接 A-roll 透明贴片、配音、音乐或收费素材生成。

选型记录保存在当前 Job 已有 treatment JSON 的 `skill_selection`，不放进仅供资料候选使用的 `candidate_snapshots`。主控先提供语义与质量评审，再调用 `select_broll_skills.py assign --project-root <project> --treatment <当前treatment>` 形成整片分配；不要手填最终选择。按此分配构造现有 brief/bindings，完成 `check --project-root <project> --treatment <当前treatment> --director-brief <当前director brief>`。以上命令均通过已准备的 `project_python.py` 运行，不触发渲染或外部调用。正式 `prepare_visual_direction(..., treatment_path=<绝对路径>)` 必须显式接收同一 treatment(以 Job 内绝对路径传入;项目根相对串会在对齐校验处拼错根)，复算分配并检查完整输入绑定；缺记录、入口或参数漂移时，在发布前停止。理由随同一次发布写入现有 `visual-routing.md`，不增加用户确认阶段。旧产物保持原样，不迁移或补造历史选型。

既有 `code_generated` 编译器的模板内部排序仍为 `semantic_match_score` → `quality_score` → `template_origin` → `reuse_gap`；这不是跨 Skill 选型入口，也不能覆盖已确定的整片分工。引用验证模板前仍须运行 `verify_broll_template.py` 核对真实登记；`structural` 或自由新场景不能继承第三方身份。填充本期内容后做三态 QA，冻结真实 `producer_type`、`dependency_id`、入口、当前请求、制作与调用证据；历史样片不能代替当前验收。

TalkCraft 108 张卡使用独立生产注册表，当前仅保留资格检索，不能由资格状态推断实际入口已接通。以下匹配与冻结合同留供接通后使用，不进入当前新计划：当段落已选 `code_generated` 且适合 TalkCraft 时，必须先调用 `edit.hd.tools.talkcraft_matcher.match_cards`，把当前口播原文、语义目标、关键词、信息单元、组件角色、已有媒体和人物需求作为输入；再用 `build_binding` 冻结首选卡片。匹配器只读锁定的 `runtime/card-semantic-index.json`，运行时仍以 `runtime/card-registry.json` 的 qualified 身份为唯一准入依据；缺必需图像/视频/人物、角色不符或索引身份变化时显式停止，不在 adapter 或执行阶段重新选卡。这个自动选卡结果仍需要当前 Job 的 brief 参数化、三态 QA 和 canary 本地 QA 与内部批准。

需要工作台微调时，先用 `edit.hd.tools.talkcraft_workbench.build_v4_edit_contract` 从当前 VisualPlan v4 和 draft brief bundles 生成稳定目标及可编辑字段，再用 `apply_v4_overrides` 生成新的 draft bundles。工作台只允许改合同公开的语境参数，当前只开放显示文案与深浅主题；未知目标、未知字段、非法值或计划身份变化都停止。回写结果保持 `editable_draft_only`，不得覆盖已批准 bundle，也不得跳过 canary 与本地 QA/内部批准。上游 Workbench 的 `overrides.json`、共享 React 19 / Remotion 4.0.519 只服务上游编辑与冒烟；正式渲染继续使用项目已资格的 React 18 / Remotion 4.0.520 运行时。

Fish Audio 仅是无成品配音时的可选输入方式，不改变默认“使用用户成品口播”的原则。只有用户明确选择合成配音、当前 Job 已确认精确模型/声音/费用且存在 `FISH_AUDIO_API_KEY` 时，才调用 `edit/hd/integrations/talkcraft/upstream/scripts/tts_fishaudio.py`；不得把密钥写入 Job 或 Skill，不得自动发起试音或付费请求。其输出音频和时间戳仍按用户提供音频同样进入 Job、校验并报审。

注册表同时保留原生入口和历史资格。新计划不选择本地 canonical、RelationMotion、SemanticState、Lemo 或 OneTake 的旧自定义场景；历史登记仅用于追溯既有产物，不能据此恢复已排除的制作方式。当前候选以真实发现结果、对应原生入口限制及本期评审为准，不靠旧模板总数推断可用性。

`visual_direction` 冻结 `source_bindings`，并编译 `ShotRecipe v2`。`visual_canary` 只执行已批准配方，不做语义重选。`visual_assets` 严格复用 canary 字节和剩余已冻结配方，不重新做来源判断。

纯 A-roll 的语义贴片先按当前句子的关系查询现成原生组件，再按 [A-roll 透明贴片合同](references/aroll-overlay-contract.md)核对真实接通状态。当前使用 HyperFrames 的卡片、通知、开关、对照擦入和专用三步流程；真实三步操作才选 `hw-pipeline`，不能把并列材料画成先后链。每处在现有 treatment 写明 `overlay_selection`，同形重复写 `repeat_review`；正式入口检查声明、绑定、词锚和可见结构。仅需关键词强调不冒充关系贴片。核对中文容量、透明输出、真人和字幕避让，保留原生构图与动作，不统一套横条。正式流程仍为 `aroll_with_overlay / mode=none`，执行器和 `render_arroll_segment(artifacts=...)` 合成原 A-roll 并保留普通字幕。Wise、TalkCraft、Doudou 的整屏入口或透明参数不等于透明贴片已接通；只有真实独立组件、内容槽和时钟接法具备时才补最小输出适配。历史 `talkcraft_overlay` 仅保留已确认产物，不进入新选型。检索、绑定或开发样片都不等于正式交付。

A-roll 贴片先判断能否增加理解：有对应资料 B-roll 的人物/机构介绍不重复贴标签；抽象观点若只能把口播原句放大重述，就保留真人画面。比较、结构、因果或状态变化优先找能直接表达关系的现成图形组件，不把 `caption-*`、乱码揭示或大字标题当作语义贴片。贴片可见区间须绑定口播语义句，进入下一主题前退场；带贴片的 A-roll 仍须显示普通字幕，不能因使用视觉组件就误判为 B-roll；A-roll 与 B-roll 都由同一条字幕轨覆盖。正式接入须同时贯通视觉计划、canary、A-roll 字幕识别和最终合成，开发期本地字幕排版试验不得代替正式 Scribe 词级转写。候选先在原尺寸真人画面上检查稳定帧：图形关系不成立、临时字符尚可见、文案不可读、遮挡人物或与字幕重复时立即淘汰，不继续渲视频或冻结正式计划。实际导出后再量透明区域与贴片主体的 alpha，并核对真人合成后的进入、中段和退出画面确实发生预期变化；流参数、单张静帧或能播放的视频都不能单独证明动态贴片通过。现成组件只能提供部分图形时，明确记录复用部分与新增实现部分，按新实现验收；不得声称整张贴片由上游 Skill 原生完成。

同一条 A-roll 样片的画面、主音轨、Scribe 词级时码、字幕和贴片必须绑定同一个源文件哈希及明确的源时间区间；合成前后与透明 alpha 的完整核验清单以[A-roll 透明贴片合同](references/aroll-overlay-contract.md#必须验收)为准。任一绑定或复核失败，样片标记为失败并停在当前阶段，不得进入人工确认或正式 Job。

全片 A-roll 与 B-roll 统一使用已确认的 TalkCraft 卡片式口播字幕；先读上游 `video-talkcraft` Skill，再由正式 `subtitles_v2` 实际调用项目内 `talkcraft/subtitles/render.mjs` 的版本化组件适配，绑定本 Job 的 Scribe 时码、批准文案及唯一透明字幕轨。字幕适配器从兼容运行时所在项目根调用上游，复用项目已准备的浏览器缓存，不因宿主位于 Job 或临时目录而重复下载。B-roll 字幕避让同步圆形小窗，由父级在视觉轨完成后统一叠加，子 Skill 不自行烧录。具体样式、调用证据和验收边界见 [全片字幕样式与上游调用](references/subtitle-style-contract.md)。启动时的 TalkCraft 依赖检查必须包含字幕适配入口；缺组件、词时码或身份不符时停止，不得回退旧 PIL 字幕，也不得把开发样片当作正式 Job 批准。

扩展第三方模板时，先按资格合同筛查完整文案可编辑范围、长度与中文字体、分词及语义动效；原生竖屏或换标题成功不等于可以直接用于本期内容。保留版本化的排除记录，不重复测试未变化的同一缺陷。

选中 `html-video/frame-data-rollup` 时，加载 [原生 DataRollup 执行接口](references/data-rollup-execution.md)；选中 `hyperframes/notification-cascade` 时，加载 [原生 Notification Cascade 执行接口](references/hyperframes-notification-execution.md)。两者通过包内 adapter 工厂接入正式执行器，不手工重画或停留在文字登记。新版 `hyperframes/chatgpt-exchange` 因正文和表格裁字已从活动资格移除，保留历史接口与失败证据，不进入新选型；这不影响另一条原生 `chat-message` 组件。新调用计划使用 `status=planned / exit_code=null`；实际成功以执行器输出证据为准，不能为了通过校验提前填写成功。其他模板没有这一执行验证时不得套用其结论。

正式片段、成片和 B-roll 合成画布保持 1080×1920；仅无透明通道的竖屏 AI 动态 B-roll 源视频允许原生 720×1280/24fps，合成时放大，须按[生成型 B-roll 编排](references/generated-broll-skills.md)检查实播画质。其他素材仍按原有规格或单条已批准补边许可绑定验收，不能伪称原生达标。当前 full-v2 计划与成片固定为 24fps；输入素材可有其他原始帧率，但正式阶段先按运行时合同规格化，不接受其他输出帧率的计划，也不做横屏后裁切。B-roll 必须让资料/主题视觉占据整个竖屏版式，口播人物只作为同时间轴的小窗或头肩头像；禁止在全屏 A-roll 上贴一块资料小窗来冒充 B-roll。B-roll 保留与原声逐词对应的唯一普通字幕，放在圆形小窗上方并与画面内标题、关键标签错开；小头像使用 head-shoulders 裁切。实际媒体由已冻结记录和 SHA-256 解析；不用空海报代替。切入切出用 8–12 帧 alpha 回到同时间轴 A-roll。本地重渲染一次只运行一个；云端生成在材料准备阶段使用统一名额，不提前执行尚未解锁的正式 canary、字幕或交付。

开发期可用估计时窗制作纯视觉草稿；但带原声、供用户判断声画对应的 B-roll 样片必须先用同源 `video-use`/Scribe 词级时码锁定目标句，在 24fps 整帧边界保留 30–200ms 起止余量。校正时窗后重渲子 Skill 镜头及父级原声、小窗合成，核对首尾未夹入相邻句且最终音轨来自同一原片。缺少真实转写时只标为视觉草稿，旧草稿的视觉认可不等于新时窗的声画验收。

到达 `visual_direction` 时必须完整阅读 9:16 视觉质量合同、B-roll 语义能力路由和开源能力适配矩阵。到达 `visual_assets` 时必须完整阅读正式生产绑定与视觉资产前置检查。本地绑定、字体、哈希、路由或 `safe_zone` 不合格时，先停止当前执行，不发出供应商请求。

## 5. 完成边界

当前 full-v2 不生成或交付缩略图、联系表或 `contact-sheet.png`，字幕、预览与交付库存均不依赖它们。内部 QA 仍从实际视频抽取原尺寸关键帧，不缩小或拼图；向用户展示可播放视频和正式尺寸封面。历史模板资格证据保留原样，不用本次规则重签旧记录。

Preview 使用剪辑后 A-roll 的口播音频主时钟，默认不加背景音乐。机器 QA PASS 只是 `ready_for_review`；`delivery` 仍需宿主 QA、视觉清单确认、正式回执及完成审计。仅有 `delivery approved` 状态不足以宣称正式完成。

交付后用 `scripts/audit_job_completion.py --workspace <workspace> --json` 做只读审计。它只能返回 `formal_complete`、`legacy_external_approval`、`incomplete` 或 `inconsistent` 四态，并展示已验证/未证明边界；不修改 workflow、回执或文件。新 Job 只有当前十二阶段、交付媒体与 manifest、人工整表确认来源及宿主 `plan_authorized` 交付回执一致，才能返回 `formal_complete`，表示已制作交付。历史人工成片确认仍按原语义核验，不重签为新类型。

新制作的首镜固定为已批准封面经完整 Lemo Wake 制作的正文片段，随后按原话衔接真人和语义画面。原声、字幕、编号从第 0 帧开始，不再前贴 6 帧静态封面。首镜与正文候选均按[Wake 交接合同](references/lemo-wake-integration.md)调用和验收。

未明确要求时不上传 ChatCut 或其他外部编辑器，不自动发布或发消息。保持 1 个主控，最多 3 路独立准备；生成名额不能由子 Skill 各自领取一套。本地重渲染、正式组装、回执和批准仍串行；并发不增加获准的生成次数，不重做已验收成片。
