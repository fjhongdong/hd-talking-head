# 已验证模板的双输入实测资格

仅在新增、更新或审查 `verified_third_party` / `verified_local_canonical` 登记时加载。普通视频任务只消费已验证记录，不重复运行模板资格实验，也不重做用户已批准资产。

## 资格不等于目录里有模板

`verify_broll_template.py` 同时检查历史设计样片和 `execution_qa`。只有入口真实消费输入，且原生 1080×1920 中能独立完成构图、信息层级和三态动效，才可登记为整屏模板。库里的单张横向卡片、动效 primitive、固定横屏网页不能因“可渲染”获得这一身份。结构改造仍记为 `custom_fallback`，不得改标签冒认。

当前 registry 共 14 条：3 条 `verified_third_party` 和 11 条 `verified_local_canonical`。本地登记包含通用的 `process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword`，原生 `relation-motion`，以及 `semantic-state-replacement`、`semantic-state-threshold`、`semantic-state-delay`、`semantic-state-hierarchy`、`semantic-state-feedback`。每条均有两组内容、真实 MP4 和三态帧附件；关系图、时间线与六类原生语义动效还必须通过动作顺序帧。`evidence-source` 同时实测图片和视频证据；五类 SemanticState 另绑定用户批准的 25 秒头像合成 canary。模板数量读取验证器结果，不读取参考仓库数量。

## 先筛查，再进行昂贵渲染

新增入口先读模板自己的编辑合同和真实源码，做两组目标语言输入的低成本参数检查。不改变现有已验证记录或要求普通 Job 重跑历史资格实验。

- **编辑范围**：列清哪些可见内容来自变量，哪些是写死的示例。修改标题、几张卡片或片尾不等于正文也已替换；对完整场景逐项核对，不只比较两张不同的末态截图。不可编辑的示例论断、产品宣传或数据与本期无关时，该入口不能原样入选。正常界面按钮不等同于残留论断，但也要符合当前语言与演示语境。
- **长度与字体**：读取当前入口的字数窗口、最大长度、截断逻辑与字体约束。英文的字符数量不等于中文的像素宽度。超过已声明范围的文案先排除，不加无意义文字、不删关键含义、不缩小字体或插入空格来迁就模板。长度合规后仍检查中文实测宽高及整屏平衡。
- **语言与动效**：逐词、逐字和打字类模板必须检查其实际拆分和时间轴。仅按空格分词时，无空格中文整句可能变成一个动画单元；“时间轴存在”或“有帧差”不能证明逐字效果正确。分别观察输入、展开中、完整阅读态；不能靠随机装饰补偿语义动效缺失。需要改分词、重排版或重设计节奏时，如实记录为适配，不沿用未验证的原样身份。
- **运行证据边界**：浏览器 DOM/GSAP 诊断只用于提早发现问题。替换了依赖版本、模拟了 clip 显隐或未使用正式执行器时，必须注明，不能作为 `execution_qa`、真实 MP4 或当前 Job 批准的替代。筛查通过只表示可以继续正式双输入渲染，不表示已合格。

以上是维护者的筛查与目视要求，不是 `verify_broll_template.py` 已具备自动语言理解、OCR 或审美检测。失败入口保留源码版本、输入、诊断结果和准确限制；只有相关源码或适配方式改变时再测，避免下一位 Agent 重复尝试相同缺陷。

## 必须保留的原始证据

每份登记的 `execution_qa` 必须包含：

- `status=reviewed`、实际检查日期和检查者；是维护者的技术检查，不代表用户批准。
- `content_paths`：至少一个真实内容字段的 JSON pointer，当前协议限定于 `props.data` 下的对象键，如标题、条目、单位；不接受时长、背景色等代替内容变化。数组作为整体绑定，不使用数组索引。
- `source_registry`：真实执行时使用的登记快照，保存路径和 SHA-256。它只供核对历史来源，不是另一份活动主版本。
- 恰好两组 `cases`，每组包含原始 `brief`、冻结的 `recipe`、真实 `receipt`、输出 `sample` 的路径和 SHA-256，以及进入、稳定、退出三张 PNG 的角色、时码、路径和 SHA-256。

两组必须改变所有声明的内容字段，保持所测入口和原生结构一致。首次测试在独立维护夹内运行真实 renderer；计划先写 `planned / exit_code=null`，成功之后保存进程自然产生的回执。不得先填写成功或伪造旧记录绕过资格门。目前封装的证明格式是正式 `ReferenceProcessAdapter` 回执；其他执行器须补真实适配和反例测试后才能登记，没有通用自动首轮注册器。`verified_third_party` 只允许 `tokens_only` / `content_reflow`；`verified_local_canonical` 为本 Skill 自有结构，可按已登记的结构合同使用 `structural`，但不得换入口或超容量。

资格只表示模板可进入候选池。每个新 Job 仍必须用当前已批准文案执行 canary，由人工检查语义、文字、头肩头像、安全区和动效顺序；不得用历史资格样片自动批准当前 Job。

SemanticState 登记使用的头像合成 canary 只能通过 `validate_human_approval` 接受人工批准。验证器必须先校验完整 machine receipt：五类 `qualification_evidence`、每类 `reviewed_input` 与 `consumed_snapshot` 的逐文件哈希、合成片媒体规格、头像安全区、`pixel_qa`、逐态 `frames`、25 秒 montage 和 contact sheet，再核对人工批准绑定的三份 SHA-256。验证时还要对每段与 montage 重新 FFprobe；像素 QA 固定使用 `stable=4 / presence=8 / exit=4`，并直接从已哈希绑定的 consumed sample 与 source A-roll 现场抽取对照帧重新计算，不能信任 receipt 自报阈值或未绑定的缓存帧；最后抽取五个稳定帧验证 montage 的固定顺序。只有模板 ID 或 montage/contact sheet 哈希的极简回执必须拒绝；维护工具不得以补字段或重签旧证据绕过此门。

已有符合当前源码、入口、引擎和输入协议的实测，可按原字节归档复用，不必重新生成。源码、封装入口、容量、渲染合同或内容绑定方式改变，则旧证据不能自动继承。新增证据会改变当前 `verification_id`，不倒改旧 recipe 或 receipt；使用原始登记快照核对其身份。

## 机器具体检查什么

1. 所有附件存在、SHA-256 一致，路径不得越界或使用符号链接；JSON 与对象字段可读。
2. 登记快照与当前原生来源字段、源码附件、容量、引擎、render contract 一致；允许本轮新增证据导致的验证 ID 变化。
3. brief 与配方冻结的内容请求、输入哈希、帧窗一致；回执必须匹配完整 `{recipe, component_id}` 的规范 JSON SHA-256、revision、产物合同及输出身份。
4. 实际调用成功、未超时、无未解决进程组；入口字节、来源快照、渲染引擎和输入/输出哈希一致。两组调用 ID、brief 与输出身份不能相同。
5. 对两份 MP4 实际运行 FFprobe：1080×1920、SAR 1:1、DAR 9:16、零旋转、24fps、批准帧数和视频轨时长；回执中的探测字段须匹配。
6. 三态时码位于有效帧边界且严格有序。FFmpeg 单线程真实解码 PNG 与 MP4 对应帧，转 RGB 后逐帧比较像素 SHA-256，不缩放、不写新媒体。PNG 必须真实可解码为 1080×1920，不能拿 JSON 或别段截图顶替。两组稳定帧的 RGB 哈希须不同，同图不同压缩不算变化。

命令只读，FFprobe/FFmpeg 每个子进程上限 20 秒；需要两者在当前 PATH 中。缺解码器或颜色解码差异导致比对失败时，报告环境和证据问题，不放宽条件或修改原帧凑通过。证据不是防伪签名系统；哈希证明一致性，不能替代可信的实际执行及目视审查。

## 仍要人工检查什么

机器可证明“不同输入、不同像素、对应同一真实回执”，不能单独证明变化来自正确的文字、数字或语义。检查者必须对照两份 brief 逐一读出实际标题、标签、数值和单位，查看入场顺序、稳定阅读状态、退出连续性，并记录限制。改变颜色造成不同像素也不够。

本包 DataRollup 两组虚构测试分别显示不同标题、3/4 条柱、不同数值与单位。Notification Cascade 两组虚构测试分别显示四条不同中文通知，随后退场并收束到不同中文结论；只支持 `milestone_notifications`、`progress_sequence`、`delivery_checkpoints`，信息单元必须恰好为 4，所有变量保持上游默认字符数的 ±20%。其中 `NOW` 与 `Show less` 是模板原生界面文字，不是残留论断。ChatGPT Exchange 两组虚构测试分别替换问题、两段回答、三列表头、四行对照与四个 chip，共 22 个内容字段；只支持 `ai_dialogue_comparison`、`four_factor_comparison`、`prompt_to_table`，信息单元必须恰好为 4、不得传入数字序列，并按包装器的中文字符容量检查。它固定保留 ChatGPT 应用外壳，末态保持到 358 帧，由外部合成器退出。首次真实 CLI 编译需要已固定的本地运行时与字体资产；不能把资格写成任意环境无条件可用。三种资格样片均不包含头像、口播或事实审核。每个新 Job 仍需当前文案的三态 QA、正式合成的头像安全区与转场检查，以及原有人工作品验收。资格实验不是 canary，也不自动批准历史 Job 升级。

## 已排除的原样候选（避免重复筛查）

以下是本地指定提交的源码结论，不代表上游未来版本永久不适合：

| 项目与入口 | 本次不直接纳入的原因 |
| --- | --- |
| html-video `templates/frame-decision-tree/`、`frame-swiss-grid/` | 固定 1920×1080 几何，含写死的示例内容，不能原样用于竖屏整屏 |
| html-video `frame-bold-poster/source/index.html`、`frame-bold-signal/source/index.html` | 元数据宣称竖屏，但源码仍固定 1920×1080 且文案写死 |
| html-video `frame-data-chart-nyt/source/index.html` | 固定横向图表几何和示例数据，尚无当前内容参数适配 |
| html-video `frame-liquid-bg-hero/source/index.html`、`frame-glitch-title/source/index.html` | 元数据虽声明 9:16 与标题等输入，真实 HTML 却未消费这些参数，仍写死产品宣传、技术标签和示例正文；仅依靠 `100vh` 或响应式字号不等于形成可替换的竖屏内容模板。补输入绑定、中文排版和竖屏结构属于适配，不原样登记 |
| html-video `frame-light-leak-cinema/source/index.html` | 元数据声明可传 `title`、`subtitle` 并支持 9:16，但源码仍锁定 `aspect-ratio: 2.39 / 1`，标题、地点、胶片元数据全部写死；不能以竖屏画布外包横向电影条或裁切取得整屏资格 |
| html-video `vfx-text-cursor/source/index.html` | 元数据声明可传 `text` 与打字速度，但源码没有输入绑定，正文、署名、片头片尾均为固定示例；当前只有 CSS 光标闪烁，没有按输入逐字生成的执行合同，不能原样作为中文竖屏文字动效模板 |
| html-video `frame-logo-outro/source/index.html` | 元数据声明品牌名、标语和网址输入，源码却固定为 HTML Anything 品牌与网址；虽然有 logo 拼装和淡入动效，但未消费用户品牌资产或文字，且 84px 固定横向品牌行未做竖屏容量验证。只可作片尾动效参考，不原样登记 |
| OpenMontage `KPIGrid`、`LineChart` | 固定横屏网格或 SVG 几何，不能以裁切作为原生竖屏资格 |
| OpenMontage `ComparisonCard`、`StatReveal` | 前者既有整屏实测留白失衡；后者属于局部覆盖组件，不是整屏海报 |
| HyperFrames `registry/blocks/flowchart-vertical/flowchart-vertical.html` | 虽是 1440×2560 的 9:16 源画布，节点仍集中于顶部约 1000px，字号仅 18px、文案与纠错剧情写死；不是可直接填入中文内容的合格整屏模板 |
| HyperFrames `registry/blocks/hw-pipeline/hw-pipeline.html` | 1920×1080 横向透明流程组件；纵向重排成海报属于结构适配，不继承整屏资格 |
| HyperFrames `registry/blocks/ai-chat-reveal/ai-chat-reveal.html` | 中文段落按空格拆分后整段仅 1 个揭示单元；两组中文诊断及同字符数控制均复现。不作为已支持中文流式展开的原样模板；不否定它在其他语言/语义下的使用价值 |
| HyperFrames `registry/blocks/notes-reveal/notes-reveal.html` | 替换全部公开文本变量后，主要笔记正文仍是上游英文示例，不能忠实消费本期正文；需另行适配而不是只换标题交付 |
| HyperFrames `registry/blocks/share-sheet-carousel/share-sheet-carousel.html` | 原生 1080×1920 的四图轮播与接受反馈时序正常，但主面板固定 668×974，整屏面积占比约 31.4%，高信息密度 B-roll 中留白失衡；保护的英文句式与中文变量产生不自然混排，底部说明过小。仅可作局部 UI 参考，不原样登记为整屏模板 |
| HyperFrames `registry/blocks/message-thread-reveal/message-thread-reveal.html` | 原生 1080×1920 且中文打字使用字符序列，但主消息气泡固定 `white-space: nowrap`、最大 720px、32.9px 字号；上游合同又要求开场问题最少 30 字符，自然中文必然溢出。链接卡标题最少 42 字符而显示宽度只有 318px。修改换行、气泡高度和时序属于结构适配，不原样登记 |
| HyperFrames `registry/blocks/slack-notification-ad/slack-notification-ad.html` | 原生 1080×1920 且通知堆叠节奏强，但每张正文只有 16.5px 的两行显示区，超出部分被 `-webkit-line-clamp: 2` 隐藏；上游字长合同对第 1/3 条至少要求 50 字符。同等信息的中文在实际缩放宽度内无法完整显示，会截断关键信息；不为追求动效而降低文案完整性，不原样登记 |

html-video 提交：`c414ecc07f795add03807d5d9ce4baefd807cea2`；OpenMontage 提交：`cd9f3c1f03368be87b140af494914b8ee4e3c7a4`。本条目只记录排除原因，不扩增合格模板数。继续扩展时优先找原生竖屏、可参数化、与真实文案关系相符的入口；必要结构设计应如实归类，另做样片审核。

上述新增 html-video 原样候选的源码 SHA-256 为：

- `frame-liquid-bg-hero`：`00f6797bd0bacfa2311c7c5c609d56b2cac4f90bba93bc215d3def95b7d12d72`。
- `frame-glitch-title`：`0580a4fd775ec38f2af0282fac3b3b73aa5eb8c0d574c0419c09e19211d21e2b`。
- `frame-light-leak-cinema`：`e00ecf47b8e135e9bac3e168b19293632327691de38687e0209710e67206efc8`。
- `vfx-text-cursor`：`769847165be432a8b0f3938fd539883bb6c0f396c29dc4afb33c0b909b5cdb42`。
- `frame-logo-outro`：`b391529945d3d70a8e381c56375e2c653badd204b0609a3bd108e9e880717520`。

HyperFrames 上述四项对应提交 `0fd70b1d2165d6ac9f4199bfafa9f22c711bfc8f`。源码 SHA-256 分别为：

- `flowchart-vertical`：`371a521511591c15ea6b0a659ab31522a1fae70443c0b13d10f877360274200a`。
- `hw-pipeline`：`5f2d91c91d37dd6b57a015a02361c67c9a62ca33849b901b3bebad8157fb7dbb`。
- `ai-chat-reveal`：`4d83a33ef6a92d6a7af7483cc6e554f2c931a89a8999c8f4e3c3f6083fd9f6ed`。
- `notes-reveal`：`a5907f47a4e1c64afe3c0371a236ad45c7f028e4d911f835ab2da56eb74e7544`。
- `share-sheet-carousel`：`ac23b271bac33a858f939035d8f6ea2b10e9bd8fb6b6fe752f3143ccc6ea728b`。
- `message-thread-reveal`：`9355f1bbfc6f614913061290ad690b210faa5e213127ada6b4eec1a6a4d66e6f`。
- `slack-notification-ad`：`34e2532bc16e3b982a043cf265b7dd767257339dccc5803b91a35085e9434519`。

两组自然中文诊断超出了上游 ±20% 字符数窗口，不能据此宣称是合规英文模板的运行故障；另用与默认值等字符数的非语义中文控制输入，仍观察到上述分词和正文覆盖问题。诊断只在单浏览器内用本地 GSAP 3.15.0 执行原生 DOM/时间轴，代替了源码 CDN 3.14.2 并模拟 clip 显隐；不是正式 HyperFrames 实渲染或新增验证资格。源码本身的空格分词及写死正文与诊断一致。生产资格仍按前述完整流程重新验证，不将这些排除记录永久套用于更新后的上游版本。
