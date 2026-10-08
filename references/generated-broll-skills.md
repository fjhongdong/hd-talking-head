# 生成型 B-roll：选型、调用、验收

Paper 的原生 HyperFrames 路线通过 `scripts/paper_hyperframes_adapter.py`（`dependency_id=paper-collage-hyperframes`）执行；HyperFrames Registry 的竖屏结构适配继续使用 `scripts/hyperframes_native_adapter.py`。两者冻结 Job HTML 及实际图片资产，调用同一上游 CLI 0.8.19，不在预览末尾临时覆盖旧视频；每段来源分别标为 Paper 的文档路线或 Registry 原组件。Paper 专用入口只增加实际运动检查，不改变其他已确认组件的入口身份。图片和时间轴均进入正式配方，结构重排仍是 `custom_fallback`，不是已验证整屏模板。TalkCraft 原生计数器允许真实有限数值，必须绑定 `numeric_values` 与 `linear`，不得把含数字内容伪装为无数字图解。

主 Skill 负责理解当前口播、选择视觉作用、安排时码、调用现成 Skill、验收并合成。子 Skill 负责它已经实现的绘制或动画能力。Lemo-Opuscar 与 OneTake 负责本期 HTMLCanvas source 的真实制作与原生 runner；选择后先读取完整上游 Skill 及 composition/motion/look 指引。不要把“读取说明”“沿用风格词”“自己写一套动画”描述成实际调用。固定提交、brief、workflow、探针和无 smoke 不宣称完成的边界见[上游场景 Skill 与本地渲染合同](upstream-scene-skills.md)。

TalkCraft 原始卡片需要竖屏重排、去掉演示人物或按当前词锚改变时序时，使用独立的 `talkcraft-native-adaptation` 适配器和 Job 内冻结源码；保留上游真实动画实现，只调整当前镜头内容、布局与时间。绑定标为 `custom_fallback / structural`，不能借用 `hd-talking-head-talkcraft` 的已合格整屏配方身份。每段经实际渲染与当前口播验收后才能作为正式资产；单独草稿不是正式接入通过。

本页命令中的“批准帧率”在当前 full-v2 中只能是 24fps；输入素材的原始帧率不改变正式计划或成片的输出帧率。

先选择语义，再选择能力：事实、人物、产品操作需要真实资料时继续走对应资料来源，不能为使用动画而改成想象场景。抽象概念、因果或隐喻才考虑本页候选。它们不是所有 B-roll 的统一模板，也不形成五类来源之间的优先级。

隐喻先过“观众能否看懂”这一关：只看候选画面及必要的简短对象标签，能否在当前时窗辨出对象、动作和变化，而不依赖作者另行解释道具寓意。若不能，先不进入图片/视频生成；已生成的候选也标记为语义失败。保留该句 A-roll，并从后续具体动作重新选段，不用更多标签、终点帧或同一隐喻的付费重试强行挽救。此判断针对当前画面，不排除该子 Skill 在其他句子中使用。

## 当前候选与边界

| 候选 | 适合 | 已验证能力与待适配项 |
| --- | --- | --- |
| Adu Motion Video | 三项真实支点分解后归纳为方法 | 固定原生编舞与 renderer 已准备；首批仅 `classic-performance@1.0.0/decompose-and-consolidate` 的纯视觉竖屏结构适配，不照搬人物和字幕，不自动开放十七组。实际执行及时间约束见[上游场景合同](upstream-scene-skills.md)。 |
| Doudou Remotion Whiteboard | 手绘箭头、流程展开、划圈强调、铅笔跟随与纸质动效 | 已获取锁定源码；有真实 React 组件及 3 套原生配方，使用项目渲染桥直接调用。新增独立组件适配器与绑定探针；不是所有说明里的能力都有独立组件，原生配方中有固定英文标签。每段仍须正式编译、执行和当前语义验收，不能借用旧 Whiteboard 的依赖身份。 |
| Codex Whiteboard Video | 逐步讲解、结构、流程与关系展开 | 原生 SVG 分组入口已接入公共组件执行器，实测提问与回应展开及配准粗线；“移动门槛”样片仍未通过语义验收。照片神经线稿路径未测试，当前能力样片不等于精美样式批准。 |
| Paper Collage Ad | 可用纸片动作讲清的隐喻、组装、汇聚、门槛变化 | 单镜头分层动画已接入公共组件执行器并实测；不用完整广告改稿、配音、音乐或 CTA。真纸感图层及每段动作、构图仍须验收，不是通用已验证模板。 |
| Flat Animation | 知识图解、分类、对比、连接与状态变化 | 当前核对的是 `muyang-flat-animation`，使用前确认它是否为用户所指仓库。只编排其动画方案、画风和完成静帧；动态视频交给 Lovart，不能说 Flat 原生视频入口已执行。当前片段仍须真实验收。 |
| GBRO Collage B-roll | 口播概念的视觉隐喻、半调纸片逐件组装 | 用户指定的 `pyang5166/gbro-collage-broll` 已纳入启动源码检查；实际编排其隐喻方案和拼贴静帧，内置生图后交 Lovart Kling O1 制作动态视频。不是本地分层动画器，也不宣称 GBRO 原生 Gemini 视频入口已执行；当前片段仍须真实验收。 |
| Huashu 原生动效 | 三节点机制流程、单张横向来源图整行高亮、三张原生功能卡 | 固定 vendor 不改源码；`y1_kurzgesagt`、`y2_vox` 与 `t2_keynote_ui` 已完成统一启动器的双输入真实执行及对应父级检查并登记；Vox 须按实际高亮过程检查正文和来源避让。功能卡仅限 `product_features` 与恰好三张卡，不扩写成未测变体；子进程统一设置连接等待容量 64，原生动效保持不变。 |

除 Huashu 已登记的精确范围外，以上其他候选不自动登记成 `verified_third_party`。Paper 分层引擎与 Whiteboard SVG 分组入口已有下述组件接口，但每段自定义画面仍是 `custom_fallback`，不是已验证模板。其他候选没有兼容的正式来源绑定时停在候选测试，不伪造 renderer 名称，也不把生成物改叫 `local_material` 绕过原来源门。

Huashu 的 brief、能力边界与实际调用见[Huashu 原生动效接入](huashu-native-motion.md)。当前仅三节点机制流程、单张横向来源图整行高亮和三张功能卡取得资格，三条路线共用未改第三方文件的原生启动器。35 个场景不是模板数量，启动准备、候选快照和源码存在不能写成 `verified`。

## 选型与适配顺序

### 思维导图与分支关系动效

当前新增显式候选路由，而不是另造本地导图模板。用于本句明确讲述的概念拆解、分类、经验组成或多层关系；时间先后、因果流程和并列清单不能仅为使用导图而改写成树。先从口播提取真实根节点、分支和层级，节点显现与关系建立对齐该句词时码，不补空节点，也不提前显示后文结果。

- **现代图形路线：HyperFrames。** 完整读取项目内 `参考项目/B-roll开源方案/hyperframes/skills/hyperframes-registry/SKILL.md` 与 `hyperframes-animation/SKILL.md`。先执行英文语义查询 `hyperframes catalog --query "mind map branching hierarchy nodes growing connectors" --json`，再核对命中的真实源码。现成 `flowchart-vertical` 是竖屏三层决策树，具有 SVG 连线绘制和便签节点动画，但固定为 1 根、2 分支、4 叶子及英文纠错剧情；它不是任意导图的参数化入口。当前内容不满足该结构时排除，不填无意义节点。`constellation-hub` 蓝图适合中心与卫星关系，不冒充多层树；只有真实关系匹配才使用。用原生代码/配方做最小中文、时码及安全区适配，并如实记录结构调整，不沿用未经验证的通用模板身份。
- **手绘路线：Doudou。** 按下节原生制作交接组织主体笔画和绘制顺序，使用上游现有画布、路径、笔刷与必要的排线能力；箭头和圈注是关系表达的组成部分，不把普通框图加几个组件当作手绘场景。使用上述项目渲染桥，不重写绘制算法。开发出片与正式组件执行器绑定分开记录，缺绑定不能进入正式资产。
- **不采用为视频入口：** 本轮检索的 `markdown-viewer/skills@mindmap` 是 PlantUML 静态导图；`galiacheng/mindmap-skills` 是交互 Markmap HTML。它们可整理结构，但不直接产出本项目要求的动态视频，不因安装量或“交互”字样标成已接通 B-roll。

美观验收看实际竖屏成片：根节点形成焦点、分支有稳定的颜色编码与充足间距；中文至少在手机播放时可读，连线不穿文字、箭头不遮节点，展开过程不乱跳。主关系在正常播放速度下能读懂，并避开父级统一字幕与圆形小窗。来源热度不代替美观；新路线先做一条真实口播样段，不重复全片或另建资格框架。

上述 HyperFrames 入口在本项目有源码与官方演示，但本轮未完成其中文当前内容出片及正式绑定，仍是候选；不能报告“成熟导图动效已经全部接通”。

新计划默认只从现成能力及其最小组合中选择，不再主动使用本包自研的 local-canonical、RelationMotion、SemanticState。先匹配具体语义、动作、中文容量和时长，而非只匹配“白板”“流程”等风格词；没有原生整屏配方时，允许调用上游真实组件编排镜头，不重写其笔刷、箭头、手绘或动画算法。现成能力确实缺失时记录入口与缺口，才考虑最小新增实现；既有批准镜头保留，不借此自动重做或再次付费。

### Doudou 项目内调用

新 Job 依赖检查前执行 `python3 <skill>/scripts/ensure_visual_broll_skills.py --project-root <project> --skill doudou-remotion-whiteboard`，缺失时仅安装到项目 vendor，已有版本不覆盖。固定仓库 `https://github.com/undsky/doudou-remotion-whiteboard-skill.git`，提交 `d41f61c889c315b2a590fee61db3a62cf003adc9`；启动清单检查真实组件与配方文件存在，不将文件检查标成出片通过。

完整读取该目录的 `SKILL.md`，再读选中的组件或配方源码。先执行上游场景制作，再调用渲染桥；Doudou 是制作指导及绘制能力，不是自动接收关键词的成片 API。主 Skill 交付当前口播、语义关系、对象与状态变化、绘制顺序、画布安全区及源词锚；制作阶段据此生成本期场景，不从历史配方或旧 notes 复制布局和帧数。

制作交接沿用 Job 的场景记录，明确以下实际输入与使用方式，不另建模板系统：

- **主图与笔迹：**根据本句选择对象、留白、线宽、笔型和底色。使用真实导出的 `HandDrawnCanvas`、`HandDrawnArrow`、`CircleHighlight`，以及 `doudou-remotion-whiteboard/math` 中的路径切线、笔迹扰动和排线算法；只组合本镜需要的能力。需要画布时，`onDraw` 用当前帧逐步绘制，复用上游现有方法。主体轮廓、关系和必要状态要在绘制过程中成立，不以普通 CSS 边框、胶囊卡片或逐字显现替代手绘主图；CSS 可用于标签和排版。
- **真实手部与笔刷：**本项目的手绘白板默认调用原生 `RealHandFollower`，明确要求有手时不能用孤立 `PencilFollower` 代替。先将包内 `assets/doudou/hand-pencil-01.png` 和对应 JSON 的真实尺寸、笔尖标定复制并绑定到当前 Job；用户另给握笔图或本句需要不同笔型时，再按上游说明用内置生图准备透明素材并重新标定。`RealHandFollower` 没有内置图片，缺 `handImageUrl` 会显示空容器；不得把导入组件当作手已出现。
- **手笔同步：**笔尖消费正在显现的同一路径及同一进度，使用上游 `getSampledTangent` 或 `getCircleTangent`。`imageWidth/Height` 和 `tipOriginalX/Y` 均为原图像素，整体仅等比缩放一次；由 Remotion `Img` 等待同一张冻结手图加载，再让原生手部组件显示。先核对素材的自然握笔姿态：本包手图中性角为 0°，手腕朝右下；不能为避让文字把整只手转 90°、翻面或镜像。手腕只在自然姿态附近作少量微迎角，使用一小段路径的平均方向平滑转弯，不随每个扰动点或完整切线旋转；换笔画时抬笔、隐藏并移动到下一起点，不能横扫、拉伸或高频抖动。同一平面内手部尺寸保持一致，标签改到手腕不会经过的位置，连线同时保持依附主体；不靠转错手或挪迟口播词锚避让。主要描线都要能看见手，读字与结果停留时隐藏。按整张手图相对笔尖的实际范围避让标签、字幕和圆窗，不只检查笔尖；当前圆窗从 y=1360 开始时，手部下沿宜留在 y=1320 以上。只有用户明确要求无手或所选风格确实只需笔刷时才采用无手方式，并如实记录。
- **真实接口边界：**当前 `HandwrittenText` 是字符显现，不提供中文笔画路径，也未触发声明的 `onPositionUpdate`；标签保持清晰，不伪称逐笔书写。没有名为 `WhiteboardCanvas` 或 `CrossHatchFill` 的独立导出，不调用不存在的接口。现有排线来自 math；原生三套配方中的花瓣、齿轮、桥和固定英文内容仅在语义确实匹配时使用，不硬套当前内容。
- **口播驱动：**在场景制作记录中保存当前 A-roll 身份、区间、有效词索引及映射后的局部帧；制作阶段将这些参数真实写入冻结 TSX。开始绘制、对象变化、关系建立、提醒和收束分别跟随本句，不能只在报告中附词锚而仍执行旧时序。关系图须正确表达任一条件、共同观察或先后关系；需要状态变化时不能只画完一张静态图。
- **短镜头时序：**场景拆短后重新从本段词锚计算局部帧，不能只缩短 Composition 而沿用长场景的动作表。逐项核对本句必需图形与关系的开始、完成和可读停留均落在实际 `[0, frames)`；删除属于下一段、当前永远不会执行的笔画和标签，不把它们整体加速塞入本句。手在画线不是信息完整的证明：追踪对象和连线须相互依附，实际短视频不能只剩孤立曲线。来源节点可以作中性上下文预置，焦点按词锚切换，后文事件或结果不得提前。
- **制作责任：**整屏构图及本期场景装配属于执行上游 Skill 的制作阶段；原生动画算法仍来自上游。父级只做语义交接、来源绑定、调用和合成，不开发可复用的本地白板模板，不修改 vendor 或复制另一套绘制算法。必要的本期几何、标签和时序组合如实记为 `custom_fallback / structural`，不冒充完整原生配方。

项目内 `scripts/render_doudou.mjs` 直接加载上游源码，复用现有锁定 Remotion runtime；它只提供 bundling 与串行无声渲染，不另造视觉模板。每段入口在 Job 内建立 Composition，明确 1080×1920/24fps 和精确帧数，直接 import 上述上游能力或确实匹配的配方并传入当前参数。运行：

```bash
node <skill>/scripts/render_doudou.mjs --project-root <project> --entry <Job内entry.tsx绝对路径> --composition <CompositionID> --output <本段MP4绝对路径>
```

不调用上游建议的音效，不添加口播字幕或人物小窗。箭头建立、节点先后和状态变化须表达当前语义；只显字、画圈或装饰性齿轮转动不能代替实际动作。原配方中的花瓣、桥梁、品牌词和固定统计不能作为任意口播的占位内容。主体必须避开父级圆窗与字幕区。

保存实际入口、组件引用、提交、参数、输出和退出码，按当前片段检查语义与美观，再通过正式组件执行器交接。渲染桥的能力检查不授予通用模板资格，不将 Doudou 记成旧 Codex Whiteboard、SemanticState 或其他未调用能力。

`scripts/doudou_adapter.py` 提供 `create_adapter(project_root, node_executable, brief_loader)`、`create_binding(adapter, brief_bytes, reference_sample)` 与现有无声竖屏媒体探针。绑定为 `dependency_id=doudou-remotion-whiteboard / primary_renderer=Remotion / template_origin=custom_fallback / adaptation_level=structural`；节点编排不是上游原生整屏模板。预检清单按这项真实绑定调用只读探针，不能仅凭源码目录存在放行。

正式手绘入口的 Job brief 使用 `schema_version=2`：保留 `source_binding={aroll_sha256,segment_id,start,end}`、`template_request`、`entry={job_path,sha256}`、`composition={id,width:1080,height:1920,fps:24,frames}`，并绑定必填 `hand={job_path,sha256,width,height,tip_x,tip_y}`。手图是当前 Job 内已看过、可解码且有透明通道的 PNG，尺寸与笔尖均按原图核对。新执行不隐式兼容旧 brief；旧产物保留原发布身份，需要新制作时正常修订和迁移。

适配器放入 `component_adapters["code_generated"]["doudou-remotion-whiteboard"]`，交给现有 canary / visual-assets 组件执行器。执行器冻结 TSX 和手图两项字节；渲染桥从继承描述符校验长度与 SHA，再将手图写入本次临时 `public/hand.png`，显式传入 bundler 的 `publicDir`。TSX 只可引用字面量 `staticFile('hand.png')`，传给原生 `RealHandFollower` 并由同源 Remotion `Img` 等待加载；仍禁止其他静态文件、远程 URL、base64、额外音轨或 Job 外素材旁路。渲染桥核对真实 PNG 与选中 Composition 的尺寸、24fps 和帧数，串行生成无声 MP4；正常运行不发出外部请求。父级继续统一叠加同源圆窗、原声及唯一字幕轨。读取批准计划与时钟的 guard、失败停止和正常 revision 门不变。

2026-09-30 已通过该桥真实调用上游未修改的 `PencilSketchRecipe`，输出 180 帧、7.5 秒、1080×1920/24fps 无声视频，开发产物位于 `<project>/edit/verify/doudou-upstream-smoke/`。这只证明源码与现有运行时可直接出片，不证明本期任意口播语义、中文排版或正式 Job 组件绑定已通过。

同日使用已批准的“隐形经验”中文分支镜头，真实跑通统一 `execute_component`、冻结 TSX、Doudou 上游组件、Remotion 渲染与实际媒体探针，输出 144 帧、6 秒、1080×1920/24fps、yuv420p、SAR 1:1、单一无声视频流，位于 `<project>/edit/verify/doudou-mindmap-real-line/08-visual-assets/components/seg-016/code-r14.mp4`。该集成 Smoke 仅以测试上下文替代批准计划读取，真实渲染与验收未替代；不等于原长片 Job 已重新批准、绑定或合成。绑定探针亦通过；源时窗与帧数不符会拒绝。修复了执行器工作目录导致浏览器误寻址、输出描述符不带扩展名、JPEG 全范围颜色以及 PNG 缺 SAR 的实际接入问题。渲染桥使用项目已安装浏览器，不自动下载。

先判断当前句子需要呈现的对象、关系和变化，再在对应来源类型内选择合适的上游能力；“内容适合”与“已可正式执行”分别判断。不能仅因 Paper 已接通就把所有句子改成纸片隐喻，也不能把默认参数、尚未适配或单次样片失败写成整个 Skill 不适用。

判断对象前先读完整语义段落，而非只读被截出的短句。至少解清“他/这/随后”的指代、谁对谁做了什么、肯定或否定、比较双方、数量限定及前后因果；再写一句当前时窗的画面目的，区分“交代场景”“提出问题”“展示动作/结果”。上下文用于防止误解，不意味着可以把后文结论提前画出来。短句只交代场景时用中性开场；本句承担对比或因果时，必须让画面呈现那个关系，不能用相关物件或同主题背景代替。

例如原稿先介绍讲座中的“小调研”，随后问 AGI 是否已经到来（几乎无人举手），再问顶尖 AI 的综合能力是否超过多数普通人（多数点头）。介绍时窗只画成人讲者和听众准备互动，不画举手、赞同或调查统计；后续若制作两问，则保持同一组人，分别对齐不同问题和不同回应，不把两次都画成举手。不得从示意人物数量推导真实样本数或百分比。这是本段的语义示例，不是所有 B-roll 的固定模板。

选中候选后完整读取其原始 Skill 及本次入口说明，优先使用已有的画幅、无声、字幕和时长配置；确有缺口时才做最小适配，不重写它已有的绘制或动画能力。图像服务与视频服务分别检查：内置图片生成可用不代表视频生成也无需其他服务；更换模型或引入新费用不能静默执行。无透明通道的 AI 动态 B-roll 源视频允许原生 720×1280/24fps，必须保留原生尺寸记录；父级合成后仍验收 1080×1920/24fps，检查文字、线条、人物和动作在手机尺寸播放时是否清晰，不把放大结果称为原生 1080p。其他来源和透明贴片不因此放宽。

在现有授权与阶段边界内，用能代表所选能力的短片实测，记录上游版本、真实入口和输入，并按下述标准验收。失败结论只约束该输入与入口：例如逐笔关系图不适合表现物体位移，但仍可用于逐步结构讲解。没有改变输入或运行条件时不反复重试；已批准路线需要改选时仍遵守主流程的修订与确认门，不借候选测试跨来源替换。只有实际接入、实测并通过当前片段验收，才能称为可用。

## 项目内依赖

保留用户指定的开发位置，当前仅使用 `<project>/skill-development/vendor/`，不写全局或共享 Skill 库。已选依赖缺失且本次授权允许准备时，获取原始仓库到对应目录，记录实际提交；已有目录先验证来源和完整性，不覆盖、不自动更新。包与环境分开，白板环境只安装在其项目 vendor 目录。

2026-09-26 实测源码基线：

- Whiteboard Skill：`https://github.com/gnipbao/codex-whiteboard-video-skill`，`e0a1d184cfea07ae99958a1b4c0922054d1e46ce`。
- Whiteboard engine：`https://github.com/gnipbao/whiteboard-video-engine`，`86848ea27077c1902950bf4e7e37e02d4bfbd1a3`；独立 Python ≥3.11 环境安装该 engine，实际 wrapper 使用同一解释器。
- Paper Collage：`https://github.com/Jane-xiaoer/paper-collage-ad-codex`，`a69c9f56eec57ca19d1c02f6bdcffe573b4324a8`；先调用 `scripts/check-deps.sh`，要求 Node、FFmpeg、FFprobe。

另外两项只作为**视觉方案与静帧能力**接入；动态视频统一走已有的 Lovart 调用与原字节复用，仍须当前片段实测，不得把部分调用说成整套上游视频 Skill 已完成：

- [GBRO Collage B-roll](https://github.com/pyang5166/gbro-collage-broll)，源码检查提交 `a1a4ee2e2abf7d44e460026b706d0c72c2cf8a91`。
- [沐阳扁平动画](https://github.com/yokel1121/muyang-flat-animation)，源码检查提交 `d864f1472866b3f724973385f40c0ddb6159dc38`，仍作为 Flat Animation 的待确认仓库候选。

两项上游仓库的原生视频脚本会请求 Gemini，但本项目**不调用这些入口，也不要求 `GEMINI_API_KEY`**。静帧可用现有图片服务，完成静帧与视觉来源分别留证；Lovart 是独立的视频生成方。原生 720×1280 的无声 AI 视频可作为源素材，父级合成放大至 1080×1920 不算原生高清，仍须看实际画质。

### Flat / GBRO 静帧 → Lovart 动态视频

选中其中一套后，先运行 `python3 <skill>/scripts/ensure_visual_broll_skills.py --project-root <project> --skill <gbro-collage-broll|muyang-flat-animation>`。它只在项目 `skill-development/vendor/` 检查或安装固定提交；已有目录不覆盖、版本不符不暗改，不安装全局 Skill、Gemini SDK 或视频模型。然后完整读取选中上游的原始 `SKILL.md`：Flat 执行动画方案与完成静帧步骤，GBRO 执行隐喻与拼贴静帧步骤。已批准的父级视觉方向对应上游方案门；完成静帧按本 Job 的结果确认策略内审，方向变化再请用户确认。父级不制作或展示上游默认的缩略图/联系表。

静帧阶段保存上游 Skill 身份、实际调用的图片工具、完整提示词、静帧原图、哈希和人工/内部 QA 结果；没有真实执行就不得标注“Flat/GBRO 已调用”。主 Agent 冻结当前 A-roll SHA、精确时窗、镜头动作及禁止提前出现的结果，再检查静帧是否适合该语义；参考图不能把人物原样贴入无关背景。

动画阶段只使用已连接的 Lovart：先检查当前可用模型的首帧/参考图、9:16、时长和分辨率能力，确定本 Job 的精确模型和费用；上传已冻结静帧后保存 Lovart 资产 URL，再把该 URL 作为真实 `generate_video` 请求的首帧或参考图。仅传入当前镜头所需图像，不上传原片或真人素材，除非本次任务另获授权。一次提交后保存 project/task ID，结果不明先查询，不自动重复付费。先前 Kling O1 样片只证明那次能力，不是本次默认模型。当前 Lovart 模型说明中，Kling O1 的首帧模式不能同时指定画幅；Seedance 2.0 的图生视频入口也不能同时指定比例，且默认生成音频，选它时须显式设 `generate_audio=false`。每次以实时模型说明为准，不能用模型标称的 9:16/1080p 代替实际像素探测。模型成片比口播时窗长时，保留原始全长文件，由父级按已批准时窗取前段；主体动作必须在实际使用的时窗内完成，不能只在未使用的尾段出现。

输出后分别记录“Flat/GBRO 静帧设计”和“Lovart 动画生成”，不把 Lovart 产物冒充上游原生视频。观察动画前、中、后主体动作、角色稳定性、文字和圆窗避让；纯推拉、擦除或显色不算通过。保留 Lovart 原始视频和真实请求/完成记录，调用下面的原字节复用适配器；若实际文件不是无声 H.264/yuv420p、SAR 1:1、24fps 的 720×1280 或 1080×1920 竖屏 MP4，先停在媒体处理与来源绑定，不靠修改记录或重命名绕过。父级合成后仍验收 1080×1920 的手机播放画质。

视觉配方编译前先调用下文的 `lovart_existing_video_adapter.prepare_existing_binding(job, record, ffprobe路径)`，把返回值放入该组件的 `compile_context.bindings`；不要手写 executor 或把 720p 源片声明成 1080p。编译器保持 `kind=ai_generated`、`provider=Lovart` 及真实任务身份，选择 `lovart_existing_video` 并写入实测源尺寸；正常批准后由 `create_adapter(job, record)` 与 `create_artifact_probe(ffprobe路径)` 接入公共执行器，再次核验实际文件。它只复用原字节，重复执行不会向 Lovart 再次付费提交。此前 1080×1916 的单条补边许可仍只适用于那一个已确认资产，不扩展到新片。离线适配测试不是 Lovart 本次出片、语义或最终成片验收。

2026-09-27 的 GBRO→Lovart Seedance 2.0 开发测试实际生成了 720×1280、24fps、无声的动态视频，红色胶带确实被揭开；但三张流程卡仍挂在旧轨道上，只表达“解除束缚”，没有完整表达当前句“从底层重构工作模式”。用户看后明确反馈“看不懂”；即使补一个卡片脱轨的终点画面，这套道具也无法直接让人理解“重构工作模式”，因此撤回同隐喻重试方案，不再次付费。实际 MP4 的像素比例字段为 `N/A`，也未满足现有探针要求的显式 `1:1`。该样片停在 `not_accepted`，不进入真人合成，不为通过门禁修改记录。当前抽象句保留 A-roll，后文具体动作再重新选 B-roll；证据保存在本项目 `skill-development/speech-test-output/full-source-20260924/video-use-test/edit/verify/broll-upstream-skills-20260926/gbro-workflow-rebuild-lovart-20260927/`。这只约束本句、本静帧与本次模型输出，不排除 GBRO 用于其他适合的隐喻。

当前已完成的媒体测试覆盖 SVG 绘制、本地纸片动画和手绘逐层显现，不代表后续只允许这三条路线。选用其他能力时按真实需要检查依赖和费用；不自动下载未选中的照片线稿模型、配音模型或启用付费视频服务。

### GBRO 调用约束与拼贴验收

实际读取 `<project>/skill-development/vendor/gbro-collage-broll/SKILL.md`，执行其中的视觉隐喻、visual spec、静帧提示词和动作规划，不只摘取“拼贴”风格词。当前固定提交为 `a1a4ee2e2abf7d44e460026b706d0c72c2cf8a91`；准备脚本检查原始说明与入口文件，已有同提交且完整时复用，缺失时项目内安装。

这是一条明确的父级约束调用：用户已选择内置图片生成和 Lovart Kling O1，故不运行上游 `scripts/check_setup.sh` 的 Gemini 环境分支、不安装 `google-genai` 或创建共享 venv，也不执行 `generate_video.py` 或旧 Veo 脚本。隐喻及静帧仍分两步验收，遵循父级结果确认策略：已批准方向不重复询问，宿主记录实际内部 QA；语义或审美方向有实质变化时才请用户裁决。付费生成仍须本次具体授权，静帧通过不自动授权视频费用。

保留上游的精致编辑风：强烈而平坦的纸面底色、黑白半调照片剪贴、少量彩色卡纸、清楚的奶油白切边、轻柔一致的投影和细纸纹。每条约 3–6 个可分离的大物件形成清晰焦点，按本句选择底色与点色，不把全部镜头统一成蓝底或散乱小纸片。不生成可读文字、数字、UI、logo 或口播字幕；标签确有必要时由父级可靠文字层负责。构图提前避开实际圆窗和统一字幕区。

GBRO 优先用于能由少量具体纸面对象直观表达的组装、替换或关系连接；精确人物行为优先真实视频或对应动态能力，官方界面及必须准确读取的数据优先资料或可靠图形组件。GBRO 是隐喻、visual spec、静帧和动作设计的 Agent 工作流，不是本地渲染器；不另造 GBRO 动效模板，也不登记为已验证代码模板。沿用现有 brief/spec/QA 记录设计来源及提交版本、内置图片工具和 Lovart 产物，三者不混称。

动画采用上游的“空色场 → 结构 → 主体/卡片 → 连接或动作 → 完成态”组装设计；逐件滑入、卡位和连接要表达当前口播的具体关系，不能只是整张图淡入或慢推拉。内置图片服务准备两张同底色、同纸纹、同 9:16 画布的图：首帧只有空纸面，尾帧是已验收的完整拼贴，不能拿完成图当首帧。按组装顺序交给已获准的 `kling/kling-video-o1`：当前模型说明支持首尾帧模式，Lovart 工具分别传 `first_frame` 和 `last_frame`（模型字段为 `image` / `image_tail`），不同时传 `aspect_ratio`、`ref_images` 或 `ref_video`；使用实际上传所得 URL。优先一次 `duration=5`、`params={"mode":"pro"}` 的完整短镜头，主体动作在实际使用区间内完成并留出可读的完成态；确需 10 秒时按本次具体授权执行。提交前重读模型说明，所需方式不支持就停止并重新规划，不静默换模型或自行补造动画。

实际验收空场/起始状态、逐件组装过程和最终落位，核对隐喻能直接看懂、纸片边缘与质感清楚、动作发生在所用原速区间、无多余声音和第二份字幕。完成静帧不等于动态视频完成；接入现有 Lovart 原字节适配器后，由父级合成同源圆形人物小窗、原声和唯一字幕轨，展示可播放视频及必要原尺寸帧，不制作缩略图或联系表。某条素材未通过只淘汰该条，不永久排除 GBRO，也不强行替换效果更好的原 B-roll。

## 调用前交接

给子 Skill 的输入包括：理解当前镜头所必需的完整上下文、当前时窗的口播原文、人物/动作/关系、镜头目的、应保持的状态及禁止提前出现的结果；再附原声与字时码身份、精确段落起止帧、最终画布 1080×1920 与允许的 AI 动态源视频 720×1280、当前批准帧率、图像/资料引用、主视觉安全区、同时间轴圆形小窗的预留位置、无声与无常规字幕要求。图中文字仅用于简短的对象和关系标签，不复述口播。复用已有 brief/提示词记录这些信息即可，不另建评分系统；主 Agent 不能把语义判断全部交给生成器。

叙事动作与画面显现分开验收：逐笔、擦除、上色、推拉只改变图像呈现，不自动代表人物举手、点头、物体移动或因果变化。当前句子需要真实状态变化而所选入口只有静态显现时，先在同一已批准来源范围内选择能表达它的现成能力，或按已绑定时码拆成明确前后状态；不能靠改口播、补标签或一次静态完成图宣称动作成立。调整镜头时窗时同步重建字幕，不能拿缺乏源片绑定的旧时码扩展当前测试。

本项目的动态要求还适用于开场镜头，不因当前句子只介绍场景就降为静态图显现。交接中写清“谁从什么姿态/状态，经什么可见动作，到达什么结果”，并让动作在当前短时窗内可读。调查开场可以是讲者转向听众并伸出邀请交流的手势、听众转向讲者；这不同于提前演出举手表决或点头赞同。不能只用眨眼、画面整体位移或循环装饰代替需要表达的主体动作。

真实拍摄视频、现成图形/分层动作和视频模型都可以满足动态要求，按本段语义及已批准来源选型，不强制全部使用 AI 视频。静态前后两张图切换也不自动等于动作成立。图生视频在授权后使用现成 Skill 或实际可用的服务入口，不自写视频模型；只调用了服务就如实记录服务，不冒充某个未执行的 Skill。手绘素材、视频模型、父级合成分别保留真实来源。若所选服务改变来源类型、模型或费用，先确认；未提交时记录待授权，不伪造任务 ID 或生成成功。

动态验收须观察实际播放及动作前、中、后的主体姿态/物件关系，且动作不能靠切镜偷偷跳到结果。像素差异和运动量仅辅助判断：上色、噪点或摄像机移动也能造成差异，不能因此自动通过主体动作检查。人物脸形、肢体、人数、手绘线条和构图须连续稳定，仍遵守当前语义和圆窗安全区。

用户已确认主流程策略后，草图和单镜头中间结果由主 Agent 验收，不重复询问文案、画风或时码。上游完整广告/故事的默认长度、配音、片尾、缩略图/联系表交付不覆盖本 Job 合同。新费用、账号操作、关键语义改写和最终成片仍按现有确认策略处理。

图像生成与确定性动画分别保留来源：程序合成的镜头可记录 `code_generated`，但其 AI 图层仍记录生成提示词、工具、原始文件身份和实际像素尺寸。真正的视频模型输出仍是 `ai_generated`，不能因为用脚本请求就改名。只有抽象概念的说明图，不得标成现场或官方证据。

## Whiteboard 原生入口

完整读项目内 Whiteboard `SKILL.md`，已有原生矢量关系图时直接执行：

```bash
<engine-venv>/bin/python <vendor>/codex-whiteboard-video-skill/scripts/whiteboard_cli.py \
  render-image <本段.svg> -o <本段.mp4> \
  --width 1080 --height 1920 --fps <批准帧率> --duration <精确秒数> \
  --animation-preset classic --line-reveal stroke --hand none --tail-color <短尾段>
```

使用本轮检查过的纯 wrapper，不使用包含旧 bundled `src` 的同名工程副本；不设 `MOCK=1`。此原生 SVG 入口不是改造脚本生成故事的 mock 路线。

实测版本只消费独立绝对坐标路径及基础形状；忽略 SVG 的 `text`、颜色、组变换和 CSS，`A` 圆弧也不是完整弧采样。不要先画彩色 SVG 再声称会保持样式。短标签可用它自己的 `--draw-text`、明确中文字体及字号。默认 `tail-color=2` 会吃掉短镜头的大部分绘制时间，按本段时长明确分配，而非照搬默认值。对象移动是核心含义时，逐笔画完的静态示意不应自动通过动作验收。

需要按对象逐组展开时，可选原生 `--animation-preset block-speedpaint --block-order source --block-overlap 0`，对象数量按本段内容设置 `--draw-blocks` / `--max-draw-blocks`。`<g>` 不会成为动画分组，源顺序也不能代替实际检查；先看提问、各个回应是否完整依次出现，不用一幅完成图推定过程正确。`render-image` 不解析那30套故事配方，不将显式配置的单镜头误称为已调用某个配方。

这个版本会把 SVG 生成为固定2像素的预览，再用于线稿贴合及回填；仅增大 `--line-thickness` 可能仍得到过细成片。需要粗线时，准备**同一几何、同一画布、相同目标线宽**的配准原图，先确认不是空白且位置完全一致，再配合 `--no-lineart-snap --source-image <配准图> --source-fit exact`。单独关闭贴合不足以保证回填后线宽不变。开发样片使用上游 `svg_to_strokes` 与 `_draw_stroke_segment` 生成配准图，绘制和分组动画仍由原始 CLI 执行；该内部函数用法绑定上述提交，不作为稳定公共接口承诺。检查绘制中、完成态及实际手机显示宽度，不能把清楚的线条等同于精美的设计。

### Whiteboard 组件调用

`scripts/whiteboard_adapter.py` 只适配已测试的单镜头 `render-image` SVG 分组路径，不执行完整故事、照片提取、TTS、字幕或那30套故事配方。用 `create_adapter(upstream_root, engine_root, python_executable, engine_python, ffmpeg_executable, ffprobe_executable, brief_loader)` 创建适配器；`upstream_root` 为上述纯 Skill 仓库，`engine_root` 为独立 engine 仓库，`engine_python` 保留其 `.venv/bin/python` 路径，不解析为失去虚拟环境的系统 Python。

当前测试环境是 Python 3.12、Pillow 12.3.0、numpy 2.5.3、pydantic 2.13.5 和 engine 0.1.0。探针核对实际解释器、模块导入位置、上游 wrapper 及引擎源码/资源树指纹；不静默升级，也不把目录存在当作可调用。引擎在原目录复核，不宣称它与执行器冻结的素材拥有相同的不可变保证；运行期间不要修改 vendor。

当前 Job 内 brief 必须包括：

- `schema_version=1`；`source_binding` 和 `template_request` 与 Paper 使用同一合同。这里只支持非定量示意，`numeric_values=[] / numeric_scale=not_applicable`。
- `render={width:1080,height:1920,fps:<批准整数帧率>,duration:<精确秒数>,line_thickness:<1..16>,tail_hold:<小于本段时长>,draw_blocks:<1..16>}`。`tail_hold` 对应上游以秒计的 `--tail-color`，不是颜色值。分组数量与信息单元分别按真实内容设置，不声称 `<g>` 就是分组。
- `assets` 为两项或三项，必须含 `svg`、`source`，可选 `context`，每项保存 `job_path/sha256`。SVG 使用1080×1920绝对画布，PNG 为同几何、同线宽的非空白不透明配准图；禁用上游会忽略的文字、变换、外部图像及不完整采样的弧命令，不靠样式属性表达关键语义。
- `provenance={record_path,record_sha256}`；该 JSON 来源记录至少保存 `tool`、实际 `method`、`canvas={width:1080,height:1920}`、适配器固定的 `ENGINE_SHA256`，以及 `assets.svg.sha256 / assets.source.sha256`。如实记录程序矢量及其派生图，不伪称图片模型生成。哈希和尺寸不能代替人工检查配准、美观和语义。

以 `create_binding(adapter, brief_bytes, reference_sample=<真实参考视频>)` 创建 `dependency_id=whiteboard-video / primary_renderer=Whiteboard / template_origin=custom_fallback` 绑定，再注册到 `component_adapters["code_generated"]["whiteboard-video"]`，交给现有 canary / visual-assets 的 `execute_approved_components`。使用 `create_artifact_probe(ffprobe_executable)` 检查不透明视频；多类素材同阶段时按合同分派 probe，不覆盖透明贴片探针。

执行器冻结所有登记素材与来源记录；可选 `context` 为同画布、不透明的当前主题 PNG，来源记录须同时绑定其 SHA-256；wrapper 只把冻结字节放入私有临时目录，以实际检查过的引擎执行原始 CLI。它固定无声、无手部、逐组展开、无重叠与配准原图，不接受任意追加命令。上游直接生成1080×1920；有 `context` 时先在 RGB 色彩空间以 multiply 合成主题底图并编码，避免 YUV 混合产生绿偏色。随后仅补写 H.264 方形像素标记，不缩放、不再次重编码，比较补写前后每帧像素和时间。最终 probe 核对 SAR 1:1、批准帧率及精确帧数。来源、时钟或配准记录错配时停止，不回读可变素材或自动换路线。

文字 QA 必须检查实际绘制中与完成态：关键标签须落在原生分组的 reveal bounds 内，否则源 PNG 中有字也可能永远不显示。通过调整同一语义对象的线条边界与标签排版解决，不把缺字转嫁给统一字幕；结论出现时机与停留须符合当前口播，不能只检查文件参数或源图。初始 `context` 只显示已说到的主题，不提前展示后续结论。

## Paper Collage 原生入口

先核对所选入口的具体动作能力。`layer-animate.mjs` 只提供各纸片的分步入场及末态停留；不能把所有主体合并为一层、完成整图入场后停住，称为动态 B-roll。需要对象展开、移动、翻折或候选关系变化时，按上游 `references/hyperframes-route.md` 的真实纸艺 PNG＋GSAP 路线制作，再调用 `paper_hyperframes_adapter.create_adapter(project_root, python_executable, brief_loader)` 与 `create_binding(adapter, brief_bytes, reference_sample)`。它沿用 native HTML schema 2 和实际来源固定值，强制 `upstream_route=paper-collage-ad/hyperframes / alpha=false`，不另建纸艺模板或动画引擎。

将动作的局部起止帧真实写进原生时间轴，对齐当前口播，而不只在报告中列词锚。入场若早于镜头开始，检查本镜仍可见的实际动作时长；手机或道具的一次短入场不能承担后续整段。提问中的候选可以提前作为中性上下文出现，但不提前演出选中、通知、监看成功或后文成果。多个纸片独立运动的姿态及相互关系必须清楚，禁止用整张成图摇摆、缩放或装饰循环冒充主体动作。

两个 Paper 本地入口都在发布成功制品前检查未合入人物、字幕的真实子视频：`paper_motion_guard.py` 用 FFmpeg 检测连续至少 3 秒的近静止，检测失败或无法运行即停止，不发布成功制品。Paper HyperFrames 入口先在私有路径渲染、检查后才交出视频；实际结果保留在调用记录的 `motion_guard` 中。该检查仅阻止明显长静止，不能证明动作语义、美观或词锚正确；宿主仍须正常速度看动作前、中、后及父级合成区间。`process_completed`、媒体参数合格、静帧好看或人物小窗在动，都不能作为主体动态通过的理由。

完整读上游 `SKILL.md` 和它的纸质风格、提示词及本地分层动画参考。先验收一个完整画面，再准备固定背景、真正透明的动作图层和最终锁定帧。使用当前可用图片 Skill 制作纸质图像；失败不换成自写几何风格。检查 alpha，而不只相信生成请求参数；图层坐标必须配准，末尾锁定帧不能偷偷改变物体的位置、形状或语义。

完整画面的验收还要检查设计完成度，不能因语义正确就通过：主体形成集中焦点，工具、手和参照物有清楚的大小主次；留白服务动作和圆窗，不把素材孤立地散在空底上。纸纹、半调网点、切边和投影使用一致的细度与光向，避免粗重压纹、过大的手和生硬厚阴影。短标签须字形清楚、对比足、内边距舒适，抓握位置与物体接触关系自然。随后检查动作的起始状态、可读运动与终点停留，以及叠加圆窗后的整体平衡。具体配色和构图随文案选择，不把某次标尺案例固化为所有 B-roll 的模板。

```bash
node <vendor>/paper-collage-ad-codex/scripts/layer-animate.mjs \
  --manifest <本段图层清单.json> --output <本段.mp4>
```

清单显式写 `width=1080`、`height=1920`、批准 `fps`、精确 `duration`、真实 `background` / `finalFrame`、图层文件与位置、进入方向和时码。上游会缩放背景和末帧，**不会缩放各图层**；入库时先做同画布几何归一，保留原始图片尺寸，不把图片放大说成原生高清生成。不要只拿一张成图做推拉就宣称纸片动作成立。

### 接入当前 Job 的组件调用

主 Skill 宿主按其他组件相同方式加载 `scripts/paper_collage_adapter.py`，不直接把命令行生成的 MP4 塞进正式资产。先准备当前 Job 内不可变的 brief：

- `schema_version=1`；`source_binding` 精确记录当前已批准 A-roll 的 `aroll_sha256`、`segment_id`、`start/end`。
- `template_request` 沿用组件合同的语义家族、信息单元、数值及尺度字段；此图层入口不负责定量图表，数值列表为空、尺度为 `not_applicable`。
- `manifest` 是上述上游清单，图片位置改为逻辑 `media_ref`；背景和最终帧是约 9:16 的完整画布。动作层可用完整透明画布并归一到 1080×1920，也可用已在 1080×1920 坐标中裁好的透明纸片（宽高不超过画布），保持其原始像素尺寸和 `x/y`，避免正式接入后改变运动轨迹。保留合理的负 `startAt`，不要截成零改变动作。
- `assets` 每项包含 `media_ref/job_path/sha256/geometry` 和 `provenance={kind,tool,record_path,record_sha256}`。`geometry=full_canvas` 的图像按整幅画布归一；`geometry=native_cutout` 的动作纸片保持原尺寸与清单中的 `x/y`，即使其裁切框恰好也是 9:16，也不能误放大。背景和最终帧只用 `full_canvas`。图像与实际生成提示词/来源记录一起存入本 Job；生成图标为 `ai_generated`，不因动画由代码执行就改写来源。来源记录须对应具体原图及其实际尺寸、生成过程；不得只填写一个无关文件哈希。

通过 `create_adapter(upstream_root=..., python_executable=..., node_executable=..., ffmpeg_executable=..., ffprobe_executable=..., brief_loader=...)` 创建适配器，再以 `create_binding(adapter, brief_bytes, reference_sample=<真实参考片>)` 冻结本次绑定。绑定为 `dependency_id=paper-collage-ad / primary_renderer=PaperCollage / template_origin=custom_fallback`；`verification_id` 仅是该自定义实现身份，不是第三方模板资格。不得填 `verified_third_party`、预写退出成功或伪造样片。

把适配器放入当前阶段 `component_adapters["code_generated"]["paper-collage-ad"]`；用 `create_artifact_probe(ffprobe_executable)` 检查其无声 MP4（多类组件共存时按媒体合同分派已有 probe，不能用此不透明 probe 覆盖透明贴片的 probe）。传给现有 canary / visual-assets runner 的同一注册表，由它们共用 `execute_approved_components`；仅建立绑定而没有装载适配器不能执行。

执行器会冻结所有图片和来源记录，wrapper 将未达画布尺寸的整幅图归一到 1080×1920，原尺寸裁切纸片保持不变，并调用固定哈希的**原始** `layer-animate.mjs`。它不重写上游动画、不生成配音或小窗；原图941×1672等尺寸仍如实保留，视频验收为1080×1920、SAR 1:1及批准帧率。图片与来源记录共用执行器现有的8个输入名额；超出时在规划阶段减少分层，不绕过冻结。

当前片段必须重新验收动作及构图。自由分层引擎不套用固定文案模板的“双输入认证”；以后若要登记为已验证模板，仍须完整走模板资格流程。

开发样片「并行搭建测试环境」已用六张图片、同一来源记录和真实组件入口复跑；裁切纸片保持原生尺寸与坐标后，全部解码帧与原生 Paper 动画一致。后来同源 `video-use`/Scribe 将目标句锁定到 423.708333–425.458333 秒；按这 42 帧重渲后，`full_frame`、四边零边距的开发配方通过公共组件执行器、正式片段合成器和预览媒体命令，TalkCraft 零 cue 透明轨没有在 B-roll 上留下普通字幕，最终只用同区间原声与圆形小窗。证据与用户对开发样片的继续许可见 `speech-test-output/full-source-20260924/video-use-test/edit/verify/broll-upstream-skills-20260926/paper-parallel-environments-20260927/brief.md`；这仍不是完整已批准 Job 的 `prepare_preview_v2` 或交付验收，人工估测的头像参数也不得直接复用到正式计划。

## 手绘素材交给视频模型（开发调用实测）

静态素材入口不足以表达主体动作时，保留已验收画风与语义，交给用户批准的现成视频服务，再用既有 video-use 路径合成；不重写动画引擎。提交前读取当前模型能力，核对首帧画幅、支持时长、分辨率选项与费用授权；不要把服务默认值当成实际输出。任务 ID 返回后先保存再查询，未知状态不重复提交，失败不自动付费重试。

2026-09-26 用户指定 Lovart 的 Kling O1。本次实际调用 `kling/kling-video-o1` 的首帧入口，`mode=pro`、最短5秒，只上传已有手绘图；没有上传原始口播或真人素材。历史素材的设计来源仍保存在该次调用记录中，主体动画由 Lovart 执行，不将已移除的设计来源作为当前候选。原生帧检查显示讲者伸臂邀请交流、听众转头，未提前演出投票结果；父级取前75帧接入既有原声、圆窗和字幕时钟。此模型是该次选择，不是后续所有 B-roll 的默认服务。

实际输出为1080×1916，而非严格1080×1920。开发样片只上下各补2像素、未拉伸或裁切；原生尺寸项仍不通过，不以补边片冒充原生规格达标。服务状态中的比例字段也不代替文件探测。以后调用前准备准确画幅的参考图，返回后仍验真实尺寸；再次付费生成须遵守原授权范围。用户随后以“可以”确认该动态圆窗样片，可作为动作和构图参考；不代表放宽原生尺寸、批准所有后续镜头或通过正式成片验收。Agent 仅做过动作取帧检查，未宣称完成连续播放验收。

随后用户针对“沿用上下各补2像素的版本进入后续流程”明确回复“可以啊”。这次许可只绑定该原视频、现有75帧补边视频和已确认预览，见同目录 `padding-approval.json`；原始1916高度和原生规格未通过的事实保持不变。验收状态为“批准的派生输出”，不是“原生1920已通过”，不授权新生成或其他素材自动补边。

### Lovart 已完成结果的原字节复用

`scripts/lovart_existing_video_adapter.py` 是单组件交接，不是新生成器。先把原视频、真实 `generation.json`、对应 `qa.json` 按原字节放入当前 Job，逐个计算 SHA256 和字节数，再建立 `record`：

- `schema_version=1`、当前 `job_id / segment_id / component_id`。
- `source_binding={aroll_sha256,start,end}`，对应当前批准的 A-roll 和段落时间窗。
- `media / generation / qa` 各为 `{job_path,sha256,byte_count}`，路径必须是当前 Job 内相对路径，不能是 URL、符号链接或其他 Job 的路径。
- 复用明确获批的补边或页边清理版本时，成对增加 `derived_media / normalization_approval`，结构同上。`media` 仍指向原始服务视频，绝不替换原始来源身份；配方组件的 `sha256` 改绑定实际交出的派生视频。

原生竖屏视频仅缺少 SAR 字段时，可调用 `normalize_metadata_only_sar(source,output,ffmpeg路径)` 在当前 Job 生成不重编码的 `1:1` 派生文件；原件不覆盖。使用独立的 `metadata_only_sar_normalization` 记录宿主内部 QA，不填写用户预览批准或复制历史用户确认。准备入口实际核对完整逐帧像素、时间、帧数、尺寸、颜色和无音轨一致，且拒绝显式非方形或字符串 `N/A` 的源 SAR；校验失败不发布，不重新付费生成。这里只补缺失标记，不授权裁切、缩放、补边或改变颜色。

该元数据类型保留完整原视频。配方的 `render_window` 是片段内的合成时窗，不是源视频选段；不能把源帧偏移写进去。确需去掉空底开头时，调用 `normalize_lossless_source_window` 生成当前 Job 的原速无损选段，保留原件及 `lossless_source_window_normalization` 内部 QA，逐帧对账选中的 YUV 像素与归零后的时钟；派生组件使用局部 `[0, output_frames)`。此路径只允许选帧、时间归零及缺失 SAR 补为 1:1，不缩放、补边、插帧或改变颜色，不再次付费。旧补边、页边清理仍使用原先的用户确认和完整输出帧窗合同。转换及交接通过不代表动态语义、圆窗、字幕或成片已通过。

已确认预览中的页边清理可使用 `approval_type=single_asset_reviewed_margin_cleanup`，仍逐条绑定真实任务、原件、派生文件、预览摘要、帧窗和用户确认，不扩展到其他资产。仅接受原生1080×1920/24fps，输出同尺寸：不缩放、从第0帧截取当前镜头，并将像素比例标记为1:1；或只裁去底部120像素空白页边，再以 `0xf7f9f8` 补回同样120像素。`transform` 精确为 `{crop:[0,0,1080,1800],pad_bottom:120,color:"0xf7f9f8",scale:false,sar:"1:1"}`；仅规格化时改为 `crop:[0,0,1080,1920],pad_bottom:0`。原生来源身份不变，且必须复核主体未被裁切、动作与已确认预览一致。这不是通用裁切授权。

补边许可文件须包含 `schema_version=1`、`status=approved`、`approval_type=single_asset_padding_exception`、真实用户确认原文及问题、原 `generation_id`、原视频/派生视频/已确认预览摘要、原始与输出尺寸/帧数/帧率、所取原视频帧窗以及 `applies_to_other_assets=false`。当前入口只接受1080×1916→1080×1920、上下各2白像素、不缩放不裁切、从第0帧取已确认片段；帧数由当前片段绑定，不转成通用补边器。`qa.scene`、`qa.composition` 和 `qa.user_confirmation.preview_sha256` 必须与许可一致，且须先核验真实文件。缺一个引用、摘要或变换不符即拒绝；不得为不相干资产复制用户确认。

`generation.json` 保留真实 `request / submission_response / completion_response` 和 `status=completed`。`qa.json` 保留 `generation={provider,model,project_id,task_id,artifact_id,request_prompt_sha256}`、`native_video={sha256,width,height}` 和 `source_clock={cut_sha256,broll_frames_half_open}`；可保留其他原始检查结果。`request_prompt_sha256` 是实际 `request.prompt` 的 UTF-8 摘要，不是提示词文件摘要；后者可能多一个换行，应另记为 `prompt_file_sha256`。缺证据就停止，不手填成功或替换 generation 身份。

编译前先准备已完成视频的绑定，随后走正常 `visual_direction` 批准流程：

```python
binding = lovart_existing_video_adapter.prepare_existing_binding(
    job, record, ffprobe_executable,
)
compile_context["bindings"][component_id] = binding
recipe = broll_capability_router.compile_strategy(strategy, compile_context)
```

准备入口核对完成记录、任务/文件身份和实际媒体流，返回原有六项 AI 来源字段，加 `execution_mode=reuse_completed_lovart_video` 与 `source_dimensions={width,height}`。这两项仅供编译器消费，不进入最终配方；编译器仍是纯 JSON 编译，不读 Job 或执行媒体命令。不允许在 binding 中传 `executor` 或 `artifact_contract`；两项控制字段不齐、模式/provider/入口/媒体类型不符或尺寸不是 720×1280 / 1080×1920 时直接拒绝，不回退新生成。未选择该模式的其他 AI 绑定保持原有行为。

准备成功只说明交接事实成立，不等于语义、审美或 Job 批准；不要手填这些事实或跳过准备入口。批准配方由编译器产生 `kind=ai_generated`、`executor=lovart_existing_video`、`provider=Lovart`、实际模型、`endpoint_id=mcp__lovart__generate_video`（真实工具入口标识，非 HTTP 地址）、原 task ID 为 `generation_id`，以及实际请求提示词和输出视频摘要；`artifact_contract` 使用实测源尺寸，最终画布仍为 1080×1920。有批准的派生版本时，原视频摘要仍由 `media` 和调用证据保留。正常批准得到 `approved_recipe` 后使用：

```python
adapter = lovart_existing_video_adapter.create_adapter(job, record)
probe = lovart_existing_video_adapter.create_artifact_probe(ffprobe_executable)
artifact = execute_component(
    job, ComponentExecutionRequest(approved_recipe, component_id),
    adapters={"ai_generated": adapter, "artifact_probe": probe},
)
```

调用者先按当前组件选择对应 record；一份 adapter 只服务一个 Job/segment/component，不把它注册成所有镜头的通用 provider。多组件仍逐个交接，混合透明贴片时分派各自 probe；不覆盖其他组件的探针。当前 Job 的配置与批准门仍有效，开发 fixture 不替代正式批准。

适配器复用当前绑定 runtime 的安全快照，并探测实际无声竖屏 MP4；不执行补边、裁切或转码：直接交出原生 720×1280 或 1080×1920 视频，或单独许可中已审阅的派生视频原字节。身份、来源时钟、文件或实际输出尺寸不符即拒绝；合成画布仍须为1080×1920。实现、记录、许可和探针身份参与执行器缓存，未变产物由现有执行器复用。它不发起上传、生成或轮询，本次调用记录 `external_requests=0`，原 task ID 仍属于之前那次真实生成；不把这次本地复用伪称再次调用了 Lovart。

该入口的离线回归使用真实编码的无声 720×1280 和 1080×1920 测试视频，走准备绑定→公开编译入口→公共执行器→实际媒体探测，检查原字节发布和未变产物复用，并拒绝带音轨、伪尺寸、错误来源及保留字段输入。生成记录明确标为 synthetic，只证明交接能力，不证明 Lovart 已产出本次原生 720p/1080p 视频或 GBRO 动画通过审美与语义验收。此前原 Lovart 1080×1916 视频确实在媒体检查处被拒绝且未发布成功组件；单条补边许可及对应 `padding-reuse-check.json` 不扩展为其他资产授权。这些检查不代替正式 Job 审批或整条视频交付，也不产生新的付费调用。

## 验收和父级合成

1. 核对实际入口、版本、输入文件、退出码及新生成文件，不能预写成功。视频确实解码为批准画布、帧率与精确帧数，素材无音轨和常规字幕。
2. 按原声时码检查动作前、动作中、完成态：人物和场景是否正确，谁不变、谁变化，否定、先后、比较对象与结果是否符合当前口播，关键动作能否看清；画面不得凭空增加同意、人数、比例或提前给出后文答案。先把画面实际表达的一句话与当前口播对照，再单独判断美观；失败先保留并说明，不为了使用该 Skill 放宽标准。
3. 最终仅使用一个父级合成器。子 Skill 不添加人物小窗、旁白、普通字幕、片头或 BGM；父级继承已批准人物圆形白边、当前源片裁切和同时间轴嘴型，负责 8–12 帧进退场。
4. A-roll 与有口播的 B-roll 共用 TalkCraft 当前时码的唯一普通字幕轨；B-roll 字幕在同步圆窗上方，实际 alpha 应非零，并避开主体标题，不由子 Skill 烧录第二份。更换 B-roll 起止帧即使原声未变，也要按新视觉计划重建字幕，不能复用旧时间窗的透明轨；同时检查新 A-roll 时段仍有应显示的字幕。
5. 检查最终整条样片的真实画面、原声包身份、同步、完整帧数、圆形边缘和黑帧。机器检查与美观/语义判定分别记录，未通过后者不得称为可交付。

用户后续指出语义不符时，以该反馈更新当前语义状态并定位误解环节，技术通过记录不删也不冒充语义通过；修订后重新检查真正变化的画面与合成时窗，不自动重跑未变的全量测试。语义修订若改变已批准观点而不只是纠正表达，仍回到现有确认门。

测试产物保存在当前测试 `edit/verify/broll-upstream-skills-20260926/`，正式 Job 则使用自己的工作区；不引用会变化的测试路径为正式资产。上游渲染源码不复制进本 Skill，项目 glue 仅处理现有时码、字幕和人物合成。

本轮实际结论：Paper 精修样片完成内置图片生成、动作检查、原声圆窗合成，用户反馈“还行吧”，可作为当前候选参考，不是最终样式或完整 Job 批准。新增 Paper 适配器通过公共组件执行器真实调用，维护测试输出75帧/3.125秒的1080×1920无声视频，并检查动作前、中、终态；测试只替代批准阶段查询，没有创建或补签用户 Job。Whiteboard SVG 入口成功出片，但笔画重排导致能力点过晚出现，短句中只有画图过程，没有清楚的门槛移动，因此该样片视觉验收不通过；结论仅限该句与 SVG 入口，不排除其他语义或原生路径。两者均未取得已验证模板身份；不要把前者泛化到所有隐喻，也不要把后者的技术成功写成视觉成功。

后续 Whiteboard 能力样片改用真实口播“小调研”的时段，原生分组入口先画问题再展开回应，配准原图解决了过细线条；未编造调查结果。记录在 `whiteboard-survey/upstream-call.json`，失败的细线及空白配准图保留作对照，不用于当前合成。

Whiteboard 组件接入测试随后通过公共执行器生成75帧/3.125秒的静音竖屏视频，与上述原生样片逐帧像素和时钟一致；错配配准来源记录被拒绝，未产生错误组件。证据在 `whiteboard-executor-01/execution.json`。该维护测试仅替代批准阶段查询，冻结、上游调用和媒体探测均真实执行；没有创建、补签或通过正式用户 Job，也不授予精美样式或已验证模板身份。
