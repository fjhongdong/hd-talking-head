# A-roll 透明贴片：编排、调用、验收

先查询[自有动效能力库](motion-capability-library.md)中用途为 `aroll_overlay` 的具体原生入口，根据完整台词选择关系、动作及美术表现，不把 B-roll 或未接通的 TalkCraft 原生 overlay 直接当作透明贴片。正式选择会核对能力档案的审阅版本、用途和现有 binding；原词锚、alpha、避让和实播检查不被标签替代。

Overlay Studio 的原生 `pin-board` 是独立的 A-roll 短要点候选。它只在台词确实需要“逐项出现并落板”的并列或累积关系时选用，不进入 B-roll 候选，不替代既有 B-roll，也不作为全片默认样式；不在本轮宣称支持其全部卡片。按[Overlay Studio 原生要点钉板](overlay-studio-pinboard.md)建立 `overlay-studio-native` binding，继续使用现有 `aroll_with_overlay / mode=none`、唯一字幕轨和父级合成。其他关系仍按本合同已接通的原生组件选择。

先读取实际使用的上游 Skill。现成组件能表达本句关系时直接调用；允许 import 原生组件、使用公开 props、静态放置和 Sequence start/end 时钟，不新增主要动作、关键帧、曲线或替代时间线。不要把普通字幕放大重复一次，也不要为所有新口播硬套同一张示意图。

台词含一个确切数值时，可按[Huashu 原生数值贴片](huashu-stat-overlay.md)选 `huashu-motion/talking-head-stat`。其语义登记是 `numeric_emphasis / huashu-stat / native_count_up / single-metric`，仅用于 `aroll_with_overlay`；不把“一条思路”等泛指改成事实数字，也不替换 B-roll。此路线有独立的原生计数时钟与来源检查，不套用其他组件的 0.8 秒容差。当前已有测试数值的视觉样片、MOV 复用和新数值原生生成封装的执行证据；真实数字口播按用户决定留到下一条，首次实际使用仍须经过原有 canary，不能写成已经通过生产验收。

仅优化 A-roll 贴片时，保留原有 B-roll 的内容、位置、时长及来源绑定。代表样片先用 `audit_visual_coverage.require_aroll_window(approved_visual_plan, start, end)` 对照原已批准计划，只有原有 `mode=none` 的 A-roll 窗口才可继续准备和渲染；不能先把 B-roll 改标为 A-roll 再检查，也不能从被 B-roll 覆盖的原始 A-roll 取样来代替该处成片。样片若需包含相邻 B-roll 作上下文，直接复用其原产物，不重做、不覆盖。开发样片和已验收整片分开保存，不能把这种选段错误算作贴片验收通过。

同一正式流程混用 HyperFrames 不透明 B-roll 与透明贴片时，使用 `hyperframes_native_adapter.create_artifact_probe`：按冻结的 alpha 合同分发到既有严格 MP4 或 QTRLE/ARGB MOV 检查。不把只接受不透明视频的 Doudou probe 用于透明贴片；组合检查器使用独立身份，不改写失败事务或沿用旧 probe 名称掩盖变化。

三节点流程先检索 HyperFrames Registry 的原生 `hw-pipeline`。它自带逐节点手绘框和曲线连线动效；正式入口是 `scripts/hyperframes_hw_pipeline_adapter.py` 的 `create_adapter`、`create_binding`、`create_artifact_probe`，调用 `scripts/render_hyperframes_hw_pipeline.cjs` 读取锁定的上游块，替换三节点文案、时长、位置及中文字体／背景可读性参数，再由 HyperFrames 真正渲染。保持64px标签的原生像素尺寸，从1920×1080画布上方截取1080×608区域，再透明补到1080×1920，转成QTRLE/ARGB MOV，交给既有 `ReferenceProcessAdapter` 和正式合成器；不重写动效。此组件仅用于真实三步流程，不硬套比较、门槛或抽象结论。`brief` 必须包含当前批准的三节点标签、帧数、各节点入场帧 `label_frames`、对应源转写词的 `word_anchors` 与 `source_binding`；adapter 将标签实际显现时刻对照批准的 Scribe 词和剪后时间轴，不能等间隔套用旧样片。它还复核批准的 VisualPlan、A-roll 哈希、段落时钟、上游源码及依赖版本。样片通过不等于新 Job 已批准；实际真人画面仍需检查框、箭头、文字不越界、不压头发、脸和字幕。

## 当前可执行接口

先按语义检索具体原生组件，不把 `hw-pipeline` 和紧凑线稿作为全片默认样式。正式透明贴片支持 `grid-card-assemble`、`notification-stack`、`toggle-flip`、`before-after-wipe`，以及专用适配的 `hw-pipeline`。并列对象用卡片，提醒用通知，状态切换用开关，真实做法／状态对照用擦入比较，真实三步操作才用流程。目录内其他组件不因底层支持 alpha 就算正式可用：必须同时具备内容槽、原生动作和已接通的词锚检查。当前 `strikethrough-replace` 只有静态演示与注释中的时间线建议，没有可直接调用的完整时间线或文本槽；`mk-specs-list` 的内容是源码常量。两者不进入新贴片选型，也不补写动作冒充原生调用。

`toggle-flip` 只用于原声确实描述同一对象在启用／停用等两种状态之间切换，须能说明切换前后各是什么。“不依赖／无需／不用云 API”是依赖关系或能力边界，不自动等于关闭开关；否定标签配关闭状态还可能产生反向理解。此类句先找能表达实际关系的原生组件；没有合适能力时保留真人，不用一个会动的开关凑贴片。词锚和显示文字正确，也不能替代这项语义判断。

上述原生来源的薄适配使用 `scripts/hyperframes_native_adapter.py`，统一新 brief schema 2：`source_binding`、`template_request`、`entry`、`assets`、`upstream_route`、`source_pins={route,sha256}`，以及 `composition={width:1080,height:1920,fps:24,frames,alpha}`。透明 A-roll 的 `alpha=true`；整屏 B-roll 为 false。保留所选源文件的 HTML/CSS/GSAP 实现，Job 只绑定原生内容槽、字体、词时钟和必要版式；不得用只带相同类名的自写图形冒充调用。原生 CLI 输出透明 ProRes 后转换 QTRLE/ARGB，真实检查 alpha、精确帧数、尺寸与像素比例。每个候选仍需在当前真人画面检查，不复用上游演示人像。

装配预检使用固定版本 HyperFrames 的真实 preview 页面、播放器和时间轴；手工 clone template 后执行脚本不构成实际装配证据。内嵌子组件的 `id="root"` 会变成 `data-hf-authored-id="root"` / `data-hf-inner-root`；宿主没有自己的 root 元素时，不能用 `#root .子类` 覆盖样式，应使用组件类或运行时保留属性，并检查真实计算样式。检查器按当前 mount 定位唯一实例，核对主、子时钟；启动或就绪失败不能降级为模拟通过。比较组件还在实际稳定事件后检查 after 标签与填充图形的祖先透明度、overflow 和 inset 裁剪交集，不强制从某一侧揭示。内容摆放方向必须与裁剪方向一致；非零交集只证明未被完全裁掉，残留小块、语义和完整可读性继续由正式实际画面检查判断。

逐帧检查只覆盖当前 mount 及宿主中存在的前后边界帧，保留宿主时间坐标，不扫描其余空窗。正式入口按条目数和有效帧数分配有上限的检查时间，超时报条目、阶段和已检查帧数，保持失败，不判作画面不合格或模拟通过。全组复用一个浏览器；Chrome 在执行前登记独立进程组与启动身份，Python 拥有检查临时目录，先停登记进程，再读取最终记录回收浏览器，覆盖启动未交接、单条超时及整组超时。检查缓存、浏览器资料和项目副本均留在该临时目录；不扫描或关闭用户已有浏览器，也不重签旧 Job、重做已批准成片。

整屏 B-roll 的时间推进或拖延可选同一适配器的 `hyperframes/beat-timeline` 原生有序节拍：只绑定公开的 `beatCount`、`interval`、`labels` 和父级时窗，保留其逐拍进入与退场。它不是通用日历，也不自动证明某个产品已执行任务；按本句使用真实时间标签和明确未完成状态，不伪造日期或改写原生时间线。此入口尚未补齐透明贴片的实际词锚接法，不进入当前 A-roll 选型。

薄适配不包括重写主要布局或时间线。若一张组件需要改写核心动作才能表达本句，换一个现成入口；不能因为组件名字成熟，继续把所有含义改成三框、双框或标题。标题/关键词与普通字幕重述相同内容时不算新增贴片。已有词锚、避脸、单字幕轨和已确认内容保留检查均继续生效。

`notification-stack` 不显示正文时，显式传入公开 `bodies` 逗号列表中的空项，例如单条通知用 `bodies: ","`。省略此字段或传空字符串会触发上游英文示例正文；词锚检查通过仍须检查实际卡片，不能把默认示例带进成片。父级静态摆放按本次原生画布和真人安全区检查，旧片的负 y 偏移或缩放值不能直接当作可用布局；确认卡片全边界和最终计算后的字号，再复用该产物。

已确认组件必须落实到每个适用镜头，不能只替换样片中的一个镜头就沿用其余被否决的旧贴片。全片报审前按正式 VisualPlan 列出全部 `aroll_with_overlay`，对照各自实际产物与已确认设计；任何被用户否决的样式仍存在，旧预览即未通过。文件名、渲染完成或相同视觉轨哈希不能证明视觉修复完成。

补充贴片的样片通过后，必须立即更新当前正式 director 的对应组件、原生 brief/source binding 和 `manifests/confirmed-content.json`；详见[视觉修订的保留检查](visual-revision-reuse.md#已确认内容的保留检查)。后续只修改开头、剪切或 B-roll 时，贴片默认保留并按词锚重绑定，不再从早期无贴片计划覆盖。保留记录有而正式计划没有的贴片，正式入口直接报错。

同风格三节点流程直接调用上述 HyperFrames 入口。双项对比改选真正支持对比的现成组件；不通过删除箭头或另写原语状态转场改造成新动效。真实口播窗口允许 3–15 秒，不为凑时长延长镜头。下列 TalkCraft 原语关系是历史结构适配记录，不进入新选型；已有确认内容保留，不回退旧大面板或越界节点。

历史 `edit.hd.tools.talkcraft_overlay` 提供 `create_adapter`、`create_binding`、`create_artifact_probe`，项目入口为 `edit/hd/integrations/talkcraft/aroll-overlay/render.mjs`，通过既有 `ReferenceProcessAdapter` 执行。它不取得新制作原生场景资格；不能只因导入了原语，就继续自行编写主体动作。

- 依赖身份：`hd-talking-head-talkcraft-overlay`，Remotion 4.0.520；与 108 张 qualified 整屏卡的 `hd-talking-head-talkcraft` 分开。
- 当前可表达“固定能力点＋移动评判标准”、三步流程和双项对比。直接调用锁定上游 `Sketch / Panel / Plate / Label / Node / Connector / DrawPath`；布局是项目适配，分类必须为 `custom_fallback / structural`。三种关系都须按本片真人实拍底图重新验收。
- `create_adapter` 接受当前 Node、FFmpeg、浏览器绝对路径与读取本 Job 冻结 brief 的 `brief_loader`；不得传旧 Job 的参数或隐式升级上游运行时。
- 以 `{"code_generated": {dependency_id: adapter}, "artifact_probe": probe}` 注入正式 canary / visual_assets。生成前冻结 `create_binding` 返回的源码、版本、brief 和真实参考样片哈希，计划状态为 `planned`，不能预写成功。
- `source_sha256` 覆盖实际 TS/Node 入口、上游 schematic/icons 及两组依赖锁文件。源码变化须重新冻结配方；`verification_id` 在此只是实现身份，不是双输入模板资格证明。

## 启动依赖

`check_runtime.py` 同时检查字幕与贴片入口，以及贴片目录的 `@remotion/paths@4.0.520`。此包是线稿原语的必需依赖，不是“可选、失败后跳过”。若只有该目录的依赖缺失且版本锁文件完整，在已授权本地依赖安装范围内执行：

```bash
npm ci --prefix <project>/edit/hd/integrations/talkcraft/aroll-overlay --ignore-scripts --no-audit --no-fund
python3 <project>/edit/hd/integrations/talkcraft/check_runtime.py
```

安装限项目内；不修改全局 Skill，不升级既有整屏卡的 `runtime/`。版本或源码不符不是缺包，停止并说明差异。

## 配方和时钟

`composition.family=aroll_with_overlay`，`mode=none`，`presenter_mode=full_frame`；非空组件只能是透明 `code_generated / annotation`，`component_dependencies=[]`。这里没有组件间的资料底图依赖，真实底图仍是本 Job 已批准的 A-roll。`no_broll` 仍不允许组件；B-roll 的真实资料底图依赖不放宽。

brief 包含 `schema_version=1`、`source_binding` 与 `renderer_input`：

- `source_binding` 为 `aroll_sha256 / segment_id / start / end`，逐项对照当前批准 VisualPlan 和真实 A-roll 文件；start/end 是剪辑后 A-roll 的区间，原片区间另由本 Job 时间映射绑定，不重复减偏移。
- `renderer_input` 包含版本、`canvas`（1080×1920、24fps、当前段帧数）、与关系类型相符的 `labels` 和 `timing`。标签为当前内容批准的 1–4 个可见字符。
- timing 是组件局部秒数，分别绑定入场、点线绘制、标准移动和退场；不能机械复制历史样片秒数。`exit` 是淡出终点，之后必须全透明；段落比动画长时仅保留透明尾部，不拉长动作。
- 每个贴片在制作前记录可在本 Job 的 Scribe 词表中逐字定位的口播锚点、该词的剪后时间、贴片要解释的关系，以及入场／变化／退场分别响应的词。入场不得早于关系被说出；关键图形变化落在对应词发声附近，下一语义主题开始前退场。计划的 `start/end`、组件局部 timing 与字幕 cue 必须在同一剪后时钟逐项对照；抽查实际片段的入场、关键变化和退场，不能只凭 brief 的英文意图推断时机正确。
- 多节点贴片优先给每个标签分别绑定 `label_times`，不要用等间隔 `step` 代替实际口播停顿。深色字所在的亮色结果框必须先完成填色，再显示文字；在真实 A-roll 上抽查中间帧，不能只看最终定格。
- 新增贴片的视觉分段起止也要落在整词边界或真实停顿，不能因方便安排动画把字幕词语拆开，例如“假｜期”。先调整分段位置，再把原生动作的局部时钟对齐原声词锚；不改原声、不手改已发布字幕来掩盖错误。
- 贴片按完整画布原坐标合成，不缩放到 B-roll 容器。安全区外不承载有效信息；当前适配图形位于画面上方，字幕位置不变。更换位置、关系、样式或文案容量须重新验收。

## 必须验收

制作前先把每个贴片写入独立贴片语义列表，再在已有 treatment 的 `overlay_selection` 为每项做一次完整候选匹配并保留全部合格候选。贴片候选与 B-roll 一起参与整片分配，先最大化真实渠道，再最大化具体模板；不能逐项提前锁定圈线或唯一 `preferred`。正式检查后才校验时间覆盖和可读性；`repeat_review` 只能记录比较后仍需复用的理由，不能替代候选比较或自动放行同形重复。覆盖遗漏、未知入口或绑定不符时停止。

每项字段为 `segment_id / component_id / intent_relation / native_route / visible_action / visual_structure / selection_reason`。当前对应关系为：`parallel / grid-card-assemble / staggered_card_reveal / grid-list`；`reminder / notification-stack / notification_stack / notification-stack`；`state_change / toggle-flip / state_toggle / toggle-rail`；`compare / before-after-wipe / moving_split_reveal / before-after-split`；`process / hw-pipeline / three_node_process / process-chain`。`native_route` 不含 `hyperframes/` 前缀；正式入口还将它与词锚检查实际读取的 brief 路由核对，不能只按模板名字放行。`repeat_review` 是 `{native_route, visual_structure, reason}` 列表，理由非空并覆盖实际重复结构；它不授权文案与台词不符的组件。

`before-after-wipe` 通过公开 `label_a / label_b / wipe_at / rest_split / exit` 绑定内容与时钟；用 `bind_native_slots` 只填原生 before/after 的静态内容槽。当前槽内仅放无文字的静态图形，文案统一走已检查的两处原生标签，不隐藏额外小字绕过词锚检查。保留上游文件及原生脚本、样式；`_native_clock` 用原始母版、公开槽内容和明确时长交接重建预期字节，不能忽略所有 HTML 差异。擦入开始和落定分别对应 `wipe_start / wipe_land`，实际浏览器读取原生时间线，不能把开始擦入当作全文已经可读。父画布透明，带底色的比较区域只静态放置在真人安全区，不覆盖整个原画面。

装配后核对实际消费的样式，不只检查输入 CSS：原生 scoped 样式可能覆盖父级静态字号。此比较组件的真实主标签须达到默认阅读基线并完整容纳于各自半幅；必要时仅在自有父级 CSS 对字号、颜色、间距等静态属性加明确覆盖，不改透明度、transform、clip-path 或原生动作。原生 root 的 `--bg` 保持透明，由公开内容槽的底色随原生 stage 共同淡出，不能让 root 的不透明底板留在真人上。既有浏览器时钟检查同时读取计算后字号、标签容量和 root 透明度；中段与退场仍看实际输出。

正式 `prepare_visual_direction` 在冻结配方前调用 `overlay_alignment.validate_treatment`。使用 HyperFrames 透明贴片的 treatment 必须有 `overlay_alignment`：每项记录 `segment_id / component_id / brief_path / events`；每个事件记录原生 `slot / kind / text / anchor={index,text} / basis`。普通入场为 `reveal`，toggle 的实际切换另记 `toggle_flip`。路径属于当前 Job，brief 必须匹配 binding 哈希；不向原生 brief 增添非公开 props。

校验读取已批准的逐词转写、剪后映射和原生 HTML 的真实公开参数，核算 `notification-stack / grid-card-assemble / toggle-flip / before-after-wipe` 实际触发时刻及退场。原生引擎将 cue 提前超过一帧时直接阻断，不把作者填写的秒数当作真实结果。`current_clause` 词锚必须在当前镜头中，入场最多提前一帧、最多滞后 0.8 秒；`recap` 只能总结已经说过的内容，不能提前展示未来结论。结果写入本次正式 `visual-routing.md`，不另设无人消费的验收文件。该检查只证明词锚与时钟一致，完整否定关系、因果和文案含义仍需实际审阅。

这三个原生组件的内部脚本读取自己的 `root.dataset.duration`，但 HyperFrames 外部子组件装配会删除此属性，不能只改源 HTML 或父级时长。制作 Job 输入时用 `overlay_alignment.bind_native_clock(source_bytes, route, mount_duration)`：绑定公开时长属性，并在原生同步脚本前后添加独立参数交接片段。前段通过框架的 scoped document 定位原生 root、临时传入时长，后段确认原生时间线已建立并移除临时属性。原生 JS/CSS 字节不变，不新增动作、seek、计时器或时间线；共享 adapter 和第三方源码不改。带延后 mount 的贴片使用 mount 自身时长，不使用父镜头总长。保留旧输入，生成新的独立 Job 副本。

`source_pins.sha256` 核对未改的上游源文件，`assets.sha256` 核对实际渲染副本，两者用途不同，不要求数值相同。正式门禁以原始字节执行相同的精确属性绑定及两个确定的参数片段，要求产物逐字节等于 Job 副本；其他差异直接拒绝。随后实际调用已安装的 HyperFrames 装配器和本地浏览器执行完整装配结果，不导出媒体、不访问外网，读取原生时间线的真实入场与退场时间，核对临时时长已移除、clip 零起点及 host 延时。只读取输入属性、复算公式或检查总帧数不能代替实际消费检查；结果随原有 visual-routing 发布，样片实际首、中、尾仍须验收。

贴片须用短句或短标签表达补充关系，不整句重复字幕。不制造台词没有说过的错误主张再划掉；否定句从第一帧可读文字起就保留“不”等限定。

每个新 Job 的样式起点读取 [默认制作配置](production-defaults.json) 的 `aroll_overlay`：沿用浅暖色、深墨字和清晰的字体层级，64px／800 是主标签的阅读起点。`card_family` 的边距、圆角和间距仅用于卡片，不覆盖开关、通知、比较或手绘流程的原生形状。父级只绑定公开字体／色板参数和必要静态摆放，不统一添加奶油色横条、不把全部文字改为同一字号、不批量隐藏图标或说明而破坏原生表达。当前尚无时序支持的正文不擅自恢复，先补对应内容槽接法。该配置不是可原样传给上游的 props 对象，也不授权改动第三方或原生时间线。

`layout` 是 1080×1920 下的初始可用区域，不是要求全部组件套同一排版。按本期真人、当前原生组件和文案长度调整位置、容器高度与换行；优先缩短补充标签或重排，不能只缩小主字掩盖裁切。保留各原生组件的构图和动作差异；B-roll 不统一套用该贴片布局。缺少已批准字体或用户本次明确改变风格时，在当前 Job 记录具体差异并重新检查，不静默换成上游演示效果。只做一条含代表关系的样片；整片导出前仍需核对其余贴片实际可读、无裁切、无遮挡、无时间漂移。

同一条 A-roll 样片的画面、主音轨、Scribe 词级时码、字幕和贴片必须绑定同一个源文件哈希及明确的源时间区间；不得根据文件名、旧笔记或推测的秒数拼接不同区间。合成前核对音频指纹/时码与源片一致，合成后同时检查最终画面的进入/中段/退出帧、实际字幕和最终音轨；透明 WebM/MOV 还要在真人合成后的画面中确认 alpha 生效，不能只凭透明元数据或播放器可播放判定通过。任一绑定或复核失败，样片标记为失败并停在当前阶段，不得进入人工确认或正式 Job。

真实输出为单视频轨的 QTRLE/ARGB MOV。必须解码检查透明通道和入场/中段/退场，不接受只看流信息；VP9 中间文件不可直接交给默认解码器造成黑底。正式合成对全范围原片做明确色彩转换后输出标准 yuv420p，不放宽规格检查。

canary 必须纳入有贴片的 A-roll；资产阶段复用已通过的 canary 字节。字幕阶段在 A-roll 和有口播 B-roll 都显示同一普通字幕轨，B-roll 字幕避让沿用本 Job 已批准参数的圆形人物小窗。最终还需检查贴片未遮人物、不是字幕复述、音轨与同一源区间一致。

美观验收在真人实拍底图上进行，不只看透明贴片单独画面：主体层级、字号与留白应与封面／B-roll 的本片视觉语言一致；一块大白板加少量字线、大片无目的空白、遮到头发或脸、与口播不符的抽象符号都退回重选组件或布局。用户反馈贴片太少时先盘点每段纯 A-roll 的可视化关系及已有贴片覆盖时窗，再按语义补足，不复制同一张图到无关句子。

开发期临时测试 Job 仅验证执行入口、复用及媒体结果，不形成用户的正式阶段批准。正式交付仍须最终预览与交付回执。
