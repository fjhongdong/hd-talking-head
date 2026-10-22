# 上游场景 Skill 与本地渲染合同

本合同把父 Skill 的边界固定为：理解语义、选择并编排镜头、冻结批准素材、验收静帧与成片、合成 A-roll 小窗和唯一字幕轨。父 Skill 不重写上游动画引擎，也不把“参考过仓库”写成“调用过 Skill”。每个新场景必须先读取上游完整 `SKILL.md` 及所选 DIRECTOR、TECHNIQUE、STYLE（或 composition/motion/look）指引，再按上游工作流制作 source，最后才允许本地 runner 渲染。

## 选择与资格

先按 `semantic_match_score`，再按 `quality_score` 排序；同分才比较 `template_origin`，最后比较 `reuse_gap`。来源资格仍是硬门，不能替代语义或美术判断。`verified_third_party`、`verified_local_canonical`、`custom_fallback`、`structural` 是资格描述，不是语义替代链。新的自由场景即使使用开源代码，也不能冒充 `verified_third_party`；记录 `producer_type=dependency`、`dependency_id`。新制作不得新增动效算法、关键帧、曲线或替代时间线；历史 `custom_fallback / structural` 记录保持原名，不追认、不迁移。现成本地 canonical 不进入新选型。prompt 库只能提供提示词参考，不能充当制作依赖。

保留既有边界：HyperFrames 负责透明 A-roll/轻组件，TalkCraft 负责精确数据，Doudou 负责白板与思维导图，Paper 负责拼贴分层，Lovart Kling O1 负责已批准的场景动作。它们都是实际调用入口，不互相借用 producer 身份。父级仍统一处理圆窗、原口播和全片唯一字幕；场景输出无声、整屏、1080×1920。

手绘圈注的静态说明须避开整只手、手腕和投影的运动覆盖区，不只避笔尖或检查结束帧。被圈标题保持在圈注目标内，辅助说明另找可读位置；不能为避让把标题移出圈外。当前 Job 的文字位置可做薄排版，原生手部、圈注和动作时钟不变，渲染后核对实际运笔过程。

### 先识别能力类型，再交给上游制作

- **现成模板/组件**：使用真实可编辑槽及原生参数，不重画已存在的动作。
- **已核对的风格创作工具包**：只有具体原生场景或公开组件已经接通时，才依照其完整导演和制作流程调用；父级只提供内容参数、静态放置、公开 props 与 start/end 时钟，不在项目内重写场景动作。历史 Lemo/OneTake 记录不自动构成当前候选。
- **生成服务**：使用所选 Skill 的提示词与生成工作流，沿用具体上传、模型和费用授权。
- **OpenFilm 原生创作 Skill（本次明确授权）**：按 [专属接入合同](openfilm-motion-graphics.md)实际读取并执行 `motion-graphics`，产出本句专属、可编辑的原生页面，再调用原生公开导出入口；不是模板库，也不是父级动效引擎。此许可只限 OpenFilm，不改变其他入口仅用原生组件的边界。

不得只借一个 renderer 再自写场景、动作或时序；没有可调用的原生动作时，批准前换候选或保留 A-roll，批准后失败停当前 route 进入 revision。

上句不禁止已明确授权的 OpenFilm 原生创作流程；但只运行它的 renderer、未执行其创作 Skill，仍不能冒称调用完成。不能借这个例外重写现成组件，或把旧样片的手机／放大镜／信封改字套用到所有主题。

### 候选能力与内容交接

选型使用上游已有检索和详情入口，核对真实内容槽、对象结构、动作先后、原生时长、画幅及透明能力。词语命中和排名不证明语义成立；否定中的词也可能被命中，须由宿主按完整原文排除。沿用已有 brief/treatment 记录对象、核心变化、禁项、词锚和相邻实际画面，并说明每项含义由哪个槽位、图形或原生动作表达；不要求原词全部上屏，也不能用按钮换字、重复字幕或状态数冒充多个业务对象。

先区分用途：整屏场景要能在目标竖屏中组织主要对象和关系；局部组件只提供一段反馈，等比放大或输出竖屏文件不赋予整屏资格；生成服务按已授权的创作输入返回素材。公开 props、静态放置和独立原生组件的起点可做薄编排，但不能重排内部阶段、轨迹、曲线，或停住末态补足口播时窗。原生自带的阅读停留保留；原生过程与真实词锚不相容时换候选，不硬改文案或动作。

接入测试的 `process_completed` 只证明调用执行成功。供用户判断效果前，宿主仍须看当前原尺寸画面与正常速度动作，核对内容完整、主次、可读性、风格协调和词锚；已有风格批准不重复索取。接口测试不填造视觉批准，也不反复展示未改变的技术样片。原素材已获认可且输入未变时，按既有来源记录复用原字节，测试只重新合成受影响部分；复用不记为新的上游生成或通用模板资格。

### Lemo 原生导演交接

以下是历史制作记录，不是新计划的准入许可。当前 Lemo/OneTake 的适配器接收本期自由场景代码，不能仅凭调用 renderer 证明动作来自现成组件；新选型暂排除这两条入口。之后只有具体原生场景或公开组件被接通，才逐条加入，不修改第三方来补齐。

父级交给 Lemo：本句想让观众理解的关系或变化、当前批准原文和真实词锚、准确帧数/尺寸、同期圆窗及唯一字幕的避让位置、前后镜头的实际视觉语言，以及可核对的视觉质量参照。父级决定“表达什么”，不预先决定“几个同形卡片、几根箭头和一个中心圆”。多来源、比较或监测也不能默认套同一张关系图。

交接须包含按[单镜信息密度](visual-quality-contract.md#单镜信息密度)拆出的可见语义拍：哪些是任务对象、谁在执行、最重要的动作是什么、变化前后如何区别。把这些内容放入已有 treatment/beat_sheet，不增加模板、时钟或审批链。上游可以自由设计道具、构图和原生动作，但不能只制作名词标签而漏掉主句动词。

按原生顺序执行：

1. 读完整 Skill、DIRECTOR、TECHNIQUE 和所选 STYLE；先写本期 treatment，再读该风格 DEMO。已有输入足够就直接推进，不重复询问已确认的配置。
2. treatment 内部列出三个简短构思并选一个，写明主动作、视觉标杆借什么/不借什么和相邻镜头如何区分；这不是三轮渲染或三次用户确认。参照未实际看过时只写待检查，不冒称已审阅。
3. 用上游原生风格语法设计本期构图和运动。一个短镜头围绕一个读得懂的主变化，让相关对象、过程和上下文随口播展开；“一个主变化”不等于全段只有一个空泛图标。可随内容发生 re-flow、状态改变、空间转换或对象动作，不以标签依次出现和轻微推拉充当全段动态。不可复制 DEMO 的故事、镜头顺序、道具或时码。
4. 用本期代码实际生成原尺寸 style frames，再原生渲染完整短镜头。自托管中文字体要覆盖全部实际可见字符并在 READY 前加载；分片字体不能只拷贝任意一片，浏览器字体加载成功亦不证明没有缺字回退。检查初始信息是否能辨认、主变化是否明显、最终状态是否确实表达本句，以及全速动作是否自然；移动中的标签也不能被其他元素穿过。来源 labels、监看动作、消息推送分别绑定它们真正说到的词，不提前发出未说到的结果。
5. 同屏看相邻镜头的形态和主要动作：换了 Skill 名却仍是白底卡片加连线，不算多样性。先在当前镜头改构图和动作；能力确实不足才换上游。沿用既有短 canary 和复用流程，只替换授权修改的组件，不重做其他已确认内容。

短 B-roll 的父级规格覆盖上游独立长片默认值：不额外生成配音、背景音乐、子字幕、片尾签名或缩略图；不为凑齐流程延长、变速或重复付费。父级只接入原生无声视觉，保留唯一音轨和字幕轨。

### 动作交接的使用示例

口播“以前自己刷公众号、群聊、网站，以后这些盯的事交给它”时，三个信息来源交代任务对象，人的操作交代原执行者，AI 接管交代核心变化。可用本期道具呈现“人持工具操作 → AI 接触并接住 → 人松手撤离 → AI 独立继续操作”，接触与松手对齐“交给”，并让接管后状态有可读的动作时间；准备动作可先出现，但不能提前完成交接。只让 AI 图标弹出、放大镜继续扫或出现“交给它”字牌，都漏了控制权转移。

这个已认可做法是语义动作参考，不是固定放大镜模板。其他主题按自身任务选择对象与动作，实际复用所选上游的原生工具；不要复制本例道具、布局或绝对秒数，也不要为增加信息提前显示未说到的通知或结果。完整动作须在批准时窗内完成，不能侵占相邻已确认贴片或破坏圆窗、原声和唯一字幕。

## 本地依赖与固定来源

### TalkCraft 资格卡误拦修复

新选型读取实际 `edit/hd/tools/talkcraft_matcher` 绑定的当前资格库。108 张资格卡的 `.tsx` 入口并非自由场景：只有卡片 ID、版本、资格 ID、源码入口、源码哈希与参考样片哈希全部匹配时放行，执行依赖必须是 `hd-talking-head-talkcraft`。未知卡、错哈希和借用其他依赖身份仍拒绝；旧自由场景与贴片路线没有恢复。当前真实资格卡已通过排名与 ShotRecipe 编译检查，不重渲已确认样片。

### Adu 原生对比组件

新调用唯一使用 `scripts/adu_native_adapter.py` 和 `scripts/render_adu_native.mjs`，版本 `2.3.0`。新生成时桥接层复制固定提交 `4a52ae2cff542cfb0bfcf6e93e5120c55d0110cf` 的完整原生 template，按公开参数调用 `TPL.compare`。关闭人物、品牌、口播字幕及进度线；在自有 `ENTRY.html` 同目录写入公开的 `output-signature.json`（`schema='adu-output-signature/1', enabled=false`），关闭新增装饰时码和 Logo。不修改原生源码、内部布局、划线、盖章、相机震动和退出过程。新版原生色彩检查要求 FFmpeg 9；只绑定项目 `skill-development/runtime/ffmpeg-9.0.2/bin/`，不替换系统 FFmpeg。由当前所选 Python 运行原生 `color_management.py --export-plan` 并检查通过后才允许生成；未准备时停止，不绕过门禁。

此入口只表达 `old_new_comparison`：两侧各 1–3 项，总计 2–6 项，5–10 秒。brief 包含 `source_binding / template_request / composition`、短 `title`、`left/right={title,items}`、整数 `left_frame/right_frame/strike_frame` 及短 `stamp`。公开入口的盖章固定发生于 `strikeAt + .35s`，不得另造盖章时钟。没有真实前后对比、内容过长、动作与词锚不相容时换候选，不改原生过程。

原生画板固定 1920×1080；父层仅将整板等比放进竖屏，不裁切、不伸展、不修改内部字号。因此它是局部对比组件，不是原生竖屏整屏模板；不得仅因输出 1080×1920 而自动用于需要饱满主体演出的整屏 B-roll。它仍为 `custom_fallback / structural`，不是已验收的通用第三方模板。

嵌入 B-roll 时，父级拥有回到 A-roll 的转场，不能把原生整片片尾淡黑一起带入。我们的调用层将公开 `CONFIG.end` 和 `TPL.compare.t1` 设在实际采集终点后 0.5 秒；采集仍严格为本段批准帧数，左右卡、划线和盖章词锚不变。这样原生片尾淡黑留在未导出的区间，不修改上游代码、不冻结或重复末帧、不变速，也不删除主要动作。检查真实组件末尾及最终合成接缝；流参数或整屏黑帧检测不能证明局部画板没有黑带。旧制品不会自动改变，需要当前受影响镜头正常修订和重新生成。

用户要求升级依赖后，Playwright `1.64.0` 放在我们自己的 `<project>/skill-development/runtime/adu-native`，使用本包 `assets/adu-native-runtime` 的精确锁文件；原仓库的 `1.58.2` 和锁文件保持不动。准备入口仍为 `ensure_visual_broll_skills.py --skill adu-motion-video`，只准备项目内环境。真实原生调用已输出 144 帧、6 秒、1080×1920/24fps、无声、SAR 1:1，fullrange→limited 转换保持时长不变。开发样片位于 `<project>/edit/verify/native-scene-connect-ke6PEQ/Adu-原生对比调用样片.mp4`，只是调用和布局检查，不代表用户已认可效果，也不替换正式成片。

正式执行器的 `--output` 是受控文件描述符，不是可派生旁路文件的普通路径。Adu 的完成日志输出到 stdout，失败日志仍保留在独立工作目录；不得在 `/dev/fd/N` 后追加日志后缀。原生渲染已完成、但包装器日志收尾失败时，先核对保留的原生视频、当次冻结输入和子命令退出记录，再新增一份明确区分“原生生成完成／包装器收尾失败”的恢复记录，通过现有 `create_existing_adapter` 导入；不改旧失败日志或 transaction，不重新渲染。

新版原生输出可能未写 SAR。我们的交接层仅在缺失时，用项目 FFmpeg 的视频流复制与 `h264_metadata=sample_aspect_ratio=1/1` 补齐方形像素及 9:16 显示标记，不重新编码画面；明确的非 1:1 比例仍由严格媒体检查拒绝。恢复已有制品时保留原片，在独立新副本执行同一元信息处理，记录原件与派生件及实际命令，核对解码画面、帧数、时长与颜色未变，再绑定新副本；不放宽通用探针或重做原生动效。

### Hypit 原生计划对话

唯一来源为 `<project>/skill-development/research/hypit-source` 的固定提交 `0d36de9a9d17562fca0e478969b80eb1c16a7693`，发行版 `0.3.1`。选中后完整读取 `skills/hypit/SKILL.md`、其发行/本地 runtime/渲染/字体/Build 指引，以及 `examples/semantic-composition/packages/chat-scene` 的原生说明。准备使用 `ensure_visual_broll_skills.py --skill hypit-native-chat`：缺失时仅在项目本地准备固定源码、pnpm 10.33.0 冻结依赖及原生 compiled chat 包，不下载浏览器，不开生成服务。

`scripts/hypit_native_adapter.py` 的 `create_adapter/create_binding/create_artifact_probe` 登记为 `hypit-native-chat`，版本 `1.2.0`、`HTMLCanvas`、`custom_fallback / structural`，源码固定为 `0d36de9a9d17562fca0e478969b80eb1c16a7693`。本项目 executor 另需该依赖的同名注册；Skill 包不包含父级运行时，不借 Adu 或其他身份执行。固定入口为 `scripts/render_hypit_native.mjs`，新生成只调用 Hypit 原生 `build` 与 `get`，不借浏览器 renderer 自写聊天动效。

输入为 `source_binding / template_request / composition`、短 `title`、2–4 项 `messages={sender,text,side,frame}`，仅适用于 `plan_change_dialogue`。每条消息最多 28 字，5–10 秒；到达帧升序，最终消息须保留原生入场及阅读时间。原生固定副标题 `A small change of plan` 保持原样，不能用于不涉及改变计划的普通通知、流程或数据图。消息出现、缩放、滚动和状态点的动作均为原生 chat-scene；独立父级 layout 只把完整 540×480 画板静态 scale(2)，放于 1080×1920 的 y=80，给圆窗与唯一字幕留空间。不改原生 HTML、CSS、setup、data 或动作。

私有项目复制原生 chat 的 `package.json/dist` 原字节，并通过私有 `node_modules` 连接已安装依赖，不能往第三方目录补文件。时间全部使用原生精确帧写法，例如 `104f`，不转为近似小数秒。Build 只提交一次；结果协议为 `hypit.cli-build@1`，编号读取 `build.id`，检查 `build.work.outcome=complete` 与 `build.result.state=complete` 后才 `get`。观察超时或结果不明时保存原编号与日志，不重复提交。

原生 HTML-video 即使没有 AudioTrack，也会封装一条静音 AAC；我们的交接层只复制视频流、去掉该音轨，并以 H.264 元信息写明 SAR 1:1，不重编码、不 retime、不改变动作。只关闭本次私有 runtime 与它的程序，不影响共享进程。异常目录和日志保留，停止当前路线；已完成的原生 Build 直接取回，不重做动效。

当前唯一真实 Build 为 `bld_20261011T050711371Z_04E73B25A5`，原生已完成 144 帧；修正我们自己的结果接法后直接取回同一结果，没有第二次生成。开发产物为 `<project>/edit/verify/native-scene-connect-ke6PEQ/Hypit-原生计划对话样片-无声.mp4`，6 秒、1080×1920/24fps，样片对话是调用测试，不作为本期口播或用户已认可效果。未修改正式 Job、开头、贴片、封面或已验收成片。

### HyperFrames 原生聊天与屏幕流程

Python 原生入口同样经冻结 stdin 在项目目录之外执行，须由 adapter 显式传入 `--skill-root`，再从该目录导入自有 `hyperframes_runtime`；不能依赖当前目录、环境里的模块路径或 stdin 的 `__file__`。启动检查使用同一 stdin/工作目录/精简环境，不能以普通目录中的 import 代替。原生 CLI、格式交接和探针的真实命令及完整输出在失败时保存在 `/tmp/hd-native-hf-*/failure-log.json`，绑定本次 brief 与原声时窗；失败目录及已产出的视频保留，不自动重试。成功后才清理这次专用临时目录。

普通申请与补充资料的聊天不走 Hypit 的固定“改变计划”场景。可调用 `hyperframes_native_adapter` 的 `hyperframes/chat-message` 原生组件；按原生 `type/text/tail/delivered` 内容槽、独立实例起点和静态宿主布局编排，不修改其 GSAP 入场。组件本地约 0.4 秒才显示消息，词锚须计入该延迟并查看实际首个可见帧，不能把宿主 start 当作显示时刻。宿主根使用唯一 ID，明确每个实例的尺寸，避免通用 `#root` 样式污染右对齐气泡。

`hyperframes/screen-flow-carousel` 接受 2–5 个静态屏幕内容槽，以及公开 `screens/captions/cues/accent/exit` 参数。轨道推进、缩放和焦点变化均由原生组件执行；宿主只提供真实内容、静态外观和公开切换时间，不重排内部动画。原生有 0.9 秒入场和最长 0.84 秒切换，cues 会按可用时窗夹取；实际画面需核对词锚与末屏阅读时间。不能用默认英文或无意义骨架替代本句语义，也不能虚构办理完成。

这两条入口冻结本次实例输入，静态配色、字号和版式属于父级宿主；编排身份仍为 `custom_fallback / structural`，不冒充通用整屏模板。完整竖屏场景合成使用 `full_frame`，保留父级圆窗、原声和唯一字幕。

HyperFrames 优先读取子根自己的公开 `data-duration`，外层挂载时长不能覆盖它。时窗不同于默认值时，仅在 Job 自有实例中设置公开的根及 clip 时长元数据；上游仓库、原生脚本、动作、曲线和阶段算法保持不变，禁止全局替换脚本中的默认数字。分别记录上游来源与适配后实例身份，不能再宣称实例逐字节等于原版。实际检查早、中、晚词锚和退出前画面；输出帧数正确但子组件提前退场仍不合格。若必须改逻辑、变速、循环或冻结末态才能适配，则换候选。

### 已完成原生制品复用

Adu/Hypit 均提供 `create_existing_adapter(project_root, node_executable, brief_loader, *, completed_record)`；后续仍用同模块的 `create_binding`、`create_artifact_probe` 和公共 `execute_component`，不借用 Lovart 或本地素材身份。`completed_record` 为：

```json
{
  "schema_version": 1,
  "media": {"job_path": "native-reuse-input/native.mp4", "sha256": "<实际视频哈希>"},
  "original_brief": {"job_path": "native-reuse-input/original-brief.json", "sha256": "<原brief哈希>"},
  "generation_evidence": {"job_path": "native-reuse-input/native-generation.json", "sha256": "<原调用记录哈希>"}
}
```

三份文件先普通复制进当前 Job，路径须互异。仅复用宿主已核对来源的本地制品；日志不是第三方资格或可信签名，不把未知上传日志当证明。Adu 原日志没有记录原输出哈希，只说明原调用完成；本次绑定的实际 MP4 哈希和逐字节复用结果由当前执行器验证。Hypit 使用原 Build 命令的完整 `hypit.cli-build@1` 响应核对完成状态，不能用旧 `source_valid` 日志代替；外层包装器因旧编号读取失败，不代表该 Build 未完成。

`scripts/native_completed_artifact.py` 保留原生 adapter 的计划、配方、原声、窗口和运行时守卫。当前 brief 只允许重新绑定 `source_binding`；标题、内容、构图 ID、帧数和动作时点须与原 brief 相同。执行器把三份原件冻结为 FD 快照，wrapper 的显式 `--reuse-media-manifest` 分支只复制视频字节，在任何原生生成前退出；缺项或错配直接失败，不回落生成。复用记录保留原 brief、视频与调用证据的路径和哈希、当前绑定及 `native_generation_count=0`；真实调用证据中的复用参数和 adapter ID 区分本次复制与原生生成。

2026-10-11 两条均已通过一次公共 `execute_component`，组件输出与原视频 SHA-256 一致，再经现有 `segment_render` 和 `preview_v2` 完成人物圆窗、同源原声及既有唯一口播字幕合成。结果各 144 帧、6 秒、1080×1920/24fps、SAR 1:1；未重做动效、字幕或正式成片，旧测试编号失败日志保留。记录位于 `<project>/edit/verify/native-reuse-closeout-hzwths/closeout-results.json`，两条 `*-seg-001` 子目录各有执行记录和合成视频。

效果检查结论是“技术闭环已接通、用途受限”，不升格通用模板资格。Adu 的双卡片、划线和盖章清楚，但横版整板缩小后文字较小、竖屏留白较多，只适合简短局部对比。Hypit 的消息到达和滚动清楚，只适合改变计划的聊天；固定英文副标题仍保留，它是场景标题，不是第二条口播字幕。首、中、尾合成帧已核对圆窗比例、中文显示及图文避让；本轮借用同源口播和字幕只验证合成，不声明这两条内容与本期词锚完全匹配，也不替换已验收成片。新语段仍须核对实际语义、阅读速度和全速动作。

### 未采用的制作流程项目

`motion-video-skill` 固定核对提交 `dd11881e22b36523243444c49c5c29cfecc200e3`。它提供制作流程与检查脚本，不自带可直接填内容的 Remotion composition；要产出本期 B-roll 仍需重新编写动效，因此不登记为制作依赖。

`ai-promo-video-maker` 固定核对提交 `279ba5178c3c80d472b84ac2efa36c6fca33bba2`。它是宣传片制作流程，模板的 `Example.tsx` 只有三段示例文字，`anim.ts` 是底层动作工具而非口播场景库；用于本期同样要另写场景。故不登记 B-roll 入口，不借其 renderer 冒充调用，也不扩展为配音或音乐任务。

Lemo/OneTake 的历史共用适配器保留以下固定来源；新的 Adu 只使用上述原生对比组件接口：

| dependency_id | upstream_commit | 原生入口 |
| --- | --- | --- |
| `lemo-opuscar` | `b5e8ef93930b6d828f352055a689320f138237b1` | `node core/render/video.mjs <scene>` |
| `onetake` | `415758128aa45cc54340df40d8109363447f582e` | `.venv/bin/python scripts/render.py index.html` |

依赖由 `ensure_visual_broll_skills.py` 在项目本地自动准备，脚本内固定 render 包版本；Skill 新版在环境检查前按[更新规则](dependency-preflight.md#依赖-skill-更新)处理，不在渲染中联网拉取或切换。禁止全局安装和 worktree 共享。Lemo 复用项目 Chrome，不运行自动 reset/setup；OneTake 使用项目 Python 3.12。两套依赖必须同时登记到正式 executor 与 `visual_plan`，运行时不支持即停止，不能只带 Skill 文件声称跨机器可执行。

本地适配合同由 `scripts/upstream_scene_adapter.py` 实现，原生 runner 由适配器调用（API 优先，CLI 仅用于探测和真实执行）：

```python
create_adapter(project_root, dependency_id, python_executable, brief_loader)
create_binding(adapter, brief_bytes, reference_sample)
create_artifact_probe(ffprobe)
```

`dependency_id` 仅允许 `lemo-opuscar` 或 `onetake`；`primary_renderer=HTMLCanvas`；适配器版本为 `1.0.0`。CLI 支持真实 runner 及本地探测：`--probe --project-root ROOT --dependency-id ID`。

创建 binding 后登记到 `component_adapters["code_generated"][dependency_id]`，并接入现有 artifact probe/执行链；不得另起旁路渲染器。

## Wise Motion 参数组件（接入候选）

先读 `<project>/skill-development/vendor/wise-motion/SKILL.md`、`REMOTION.md` 和公开内容槽说明。依赖检查／准备走 `ensure_visual_broll_skills.py --project-root <project> --skill wise-motion`；只在项目的 `skill-development/runtime/wise-motion-0.1.21` 安装固定 npm 包 `wise-motion@0.1.21`、Remotion `4.0.532`、React `19.3.0`。使用随包锁文件与原生素材安装脚本，不调用自动降级安装器、不升级父级 4.0.520。Git 文档来源固定为 `ee0e33b9ee3fe6c3bf8c9c6de0711851e423a989`，运行包身份单独记录；不假定 npm 包与该提交等价。连续五卡环行明确选公开 `variantId='original'`；新版默认 `aboutlove-28` 是不同的词球场景，不能因为同名 `orbit` 就替换已批准画面。

当前接入候选是 `orbit` 原生主体组件：五张带图形符号的卡片连续环行，位置、侧转、深度、大小和明暗由 `catalog/effects/continuous.js` 原样提供。原生画板为 640×360，周期 6000ms、`loop=true`，公开速度为 0.5–2。循环组件按真实口播时窗持续运行，不要求台词凑足整数周期，也不冻结末态补时；非循环候选仍须保留完整原生过程。原生卡片编号只是图形编号，不代表真实任务或竞品数量。

按原 Skill 的 `scripts/match.mjs` 查候选，再用 `scripts/show.mjs <id> --details` 核对真实主体动作和内容限制，并对照实际 npm 包。`orbit` 没有内容槽；只能传公开 props，文案和静态 AI 标识由父级编排。它可用于“持续关注多项信息”的示意，不是自动导演，也不能单独表达任务接管、发现变化或推送通知。文字逐字显现、划线和静态图标不能替代主体动作。固定 Siri 音乐指令、地中海雷达捕获等场景不因看起来会动就用于本期监看语义；静止飞机和微弱折翼也不能当作清晰主体动作。

调用 `wise_motion_adapter.create_adapter(project_root, node_executable, brief_loader)`、`create_binding(adapter, brief_bytes, reference_sample)` 和 `create_artifact_probe(ffprobe)`，登记到现有 `component_adapters['code_generated']['wise-motion']`。当前 adapter 版本为 `3.1.0`、模板标识为 `wise-motion/orbit-tracking-component`。brief 沿用 `source_binding / template_request / composition`，增加 `theme='light'`、短 `title`、三项 `context_labels` 和唯一 `layers` 项：`id='orbit' / content={} / from=0 / transparent=false / speed / layout`；请求家族为 `continuous_tracking`，不提供虚构业务数值。`layout` 保持 640×360 等比画板，位于竖屏安全区域。真正运动的卡片只由公开 `WiseMotionEffect` 生成，父级只做静态位置与文案；输出无声、不透明 1080×1920/24fps，父级统一接圆窗、原声与唯一字幕。

正式执行器通过标准输入运行冻结入口，工作目录不是 Skill 目录。适配器必须显式传递 `--skill-root`；桥接脚本不能从 `import.meta.url` 推导资源目录。此纯参数组件使用 `media_loader=None`，不登记不存在的 Job 媒体。

执行器给出的是无媒体后缀的暂存路径。我们的桥先让 Remotion 写入本次临时目录中的 `native.mp4`，成功后原样交回该路径；不把暂存文件名直接传给 Remotion。临时目录由 `finally` 清理，失败保留执行日志，不自动重试。这个修正只影响我们的输出交接，不修改上游。

元数据保留 `custom_fallback / structural` 这一组件编排身份，不伪装成已验证第三方整屏模板。历史 172 帧 `interface-feedback` 样片因语义缺失、空场和额外末态保持被否决；后续 188 帧 `type-reveal / word-focus` 清单也被指出只有文字动，均不作为本期合格 B-roll 选回。旧 Doudou 复用结果仅验证父级合成，不证明新的 Wise 能力。

当前代表样片只实际调用一次 `orbit`，对应原剪后口播 53.041667–59.208333 秒的完整提问与赛道追踪说明；输出 148 帧、6.166667 秒、1080×1920/24fps，含同区间圆形人物小窗、原声和唯一关键词字幕。产物位于 `<project>/edit/verify/wise-native-orbit-ZG46Zy/Wise-原生主体环绕样片.mp4`；已看主体位置明显变化的前、中、后三帧并完成解码检查。用户以“这个可以”认可该样片，验收绑定成片 SHA-256 `600baf4f15675b7b63ec38a05cbaf79b416f7e3a3ee9b73f108e74dfdc98807f`。此认可仅适用于该“持续关注信息”构图和原生主体动作，不升级为通用模板资格，不替换原成片；新文案仍须核对语义、时窗和实际画面。

同日只完成一条代表复用样片：先拒绝上述 172 帧 Wise 输入，再按原发布记录复用同一语段的 Doudou 制品，合成原圆窗、原声和唯一关键词字幕；输出 172 帧、1080×1920/24fps，动效字节与来源身份未变。该结果验证拒绝错误替换及父级合成，不是重新调用 Doudou 生成，也不赋予 Wise 整屏模板资格。

测试 A-roll 必须使用独立的普通文件副本，不使用硬链接或符号链接；复制后核对内容一致且源文件与副本均只有一个硬链接。此前硬链接导致的合成失败日志保留，测试链接已移除，原片内容未改。父级合成失败时先停止并说明原因；获准修正后复用已生成动效，不自动重渲第三方动效，也不改动正式 Job 和已验收成片。

## Lemo/OneTake 的 brief 与 workflow（历史记录）

`brief` 固定为 schema 1，字段如下：

```text
source_binding={aroll_sha256,segment_id,start,end}
template_request
composition={id,width:1080,height:1920,fps:24,frames}
dependency_id
files=[2..8 个冻结 Job 相对文件]
workflow_media_ref
```

每个 file 写 `media_ref/job_path/scene_path/sha256`，并覆盖 `index.html`、`workflow.json`、本期 JS、字体和素材；依赖 core 资源只引用固定 upstream。`workflow.json` 必须锁定 `dependency_id` 和 `upstream_commit`，写出真实选择路径列表、concept、beat_sheet、`upstream_features`（原库路径或 style 函数及说明）以及实际静帧 QA；不能只写“已调用”。沿用这些现有字段记录本期 treatment、具体参照及复用/新增边界，不新增一套时钟、审批链或艺术评分框架。词锚从当前 Scribe 和 timeline-map 映射，旧 treatment 的绝对输出秒数不得当作当前时码。

## 原生 runner 与探针

Lemo-Opuscar 使用：

```bash
node core/render/video.mjs <scene> --size 1080x1920 --fps 24 --workers 1 --out <output>
```

成功必须观察 `READY`、`render` 和 `DUR`。OneTake 使用：

```bash
.venv/bin/python scripts/render.py index.html --width 1080 --height 1920 --fps 24 --dur <秒> --workers 1 --out <output>
```

成功必须观察 `__ready`、`__seek` 和 `__meta.dur`。两者均为无声整屏输出；仅 OneTake 保留 180 度快门；不硬编码人物或配音，不自动付费。适配器只冻结 source 与依赖身份，不自行改写场景语义。

原生执行必须保留 frameclock 与无声守卫。`workflow.json` 中的 feature path、symbol、usage 必须能在本期实际 source/code 中对账；OneTake 还须保持原生 `motion.js` 字节一致。现有适配器的路径和 symbol 检查只核对来源声明，不能证明函数已执行、构图符合风格或画面美观；原生执行证据与真实画面审阅各自保留。QA 只写实际检查过的静帧和全速动作，未渲染、未观看的项目保留待检查，不预填通过。

开发调用验证：Lemo 与 OneTake 各有一条真实 executor smoke，均输出 1080×1920、24fps、144 帧、6 秒、无声；这只是开发调用验证，不是新正式 Job 全流程。Lemo 实测 JPEG 输出为 fullrange `yuvj420p`，适配器须做真实 fullrange→limited `yuv420p` 颜色转换并核对 SAR 1:1，不得只改标签，也不得缩放、retime 或 loop。OneTake 保留原 180 度快门，不重编码，仅允许写入 SAR 元信息。两者画风不同，开发样片不是永久模板；旧 Job 不变。

## 阶段与兼容边界

继续沿用 full-v2 十二阶段、批准素材和状态级联。旧 Job 不重签、不迁移为新依赖；新依赖只进入新 revision。渲染前父级必须确认 source、依赖提交、brief 哈希和静帧实际审阅；渲染后再检查尺寸、帧率、帧数、无声、动作前中后和 source_binding 时钟。任何一项缺证据就停在当前阶段，不能用历史样片、目录存在或成功退出码代替真实验收。
