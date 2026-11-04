# A-roll 透明贴片：编排、调用、验收

> 当前生产流程与交付边界以 [SKILL.md](../SKILL.md) 和[视觉规划](visual-quality-contract.md)为准。本文保留原生入口与能力资料；历史样片和质量记录不构成每期交付门槛，原生 Skill 自身技术 QA 不变。

先查询[自有动效能力库](motion-capability-library.md)中用途为 `aroll_overlay` 的具体原生入口，根据完整台词选择关系、动作及美术表现，不把 B-roll 或未接通的 TalkCraft 原生 overlay 直接当作透明贴片。正式选择会核对能力档案的审阅版本、用途和现有 binding；原词锚、alpha、避让和实播检查不被标签替代。

Overlay Studio 的原生 `pin-board` 是独立的 A-roll 短要点候选。它只在台词确实需要“逐项出现并落板”的并列或累积关系时选用，不进入 B-roll 候选，不替代既有 B-roll，也不作为全片默认样式；不在本轮宣称支持其全部卡片。按[Overlay Studio 原生要点钉板](overlay-studio-pinboard.md)建立 `overlay-studio-native` binding，继续使用现有 `aroll_with_overlay / mode=none`、唯一字幕轨和父级合成。其他关系仍按本合同已接通的原生组件选择。

先读取实际使用的上游 Skill。现成组件能表达本句关系时直接调用；允许 import 原生组件、使用公开 props、静态放置和 Sequence start/end 时钟，不新增主要动作、关键帧、曲线或替代时间线。不要把普通字幕放大重复一次，也不要为所有新口播硬套同一张示意图。

台词含一个确切数值时，可按[Huashu 原生数值贴片](huashu-stat-overlay.md)选 `huashu-motion/talking-head-stat`。其语义登记是 `numeric_emphasis / huashu-stat / native_count_up / single-metric`，仅用于 `aroll_with_overlay`；不把“一条思路”等泛指改成事实数字，也不替换 B-roll。此路线有独立的原生计数时钟与来源检查，不套用其他组件的 0.8 秒容差。当前已有测试数值的视觉样片、MOV 复用和新数值原生生成封装的执行证据；真实数字口播按用户决定留到下一条，首次实际使用仍须经过原有 canary，不能写成已经通过生产验收。

仅优化 A-roll 贴片时，保留原有 B-roll 的内容、位置、时长及来源绑定。代表样片先用 `audit_visual_coverage.require_aroll_window(approved_visual_plan, start, end)` 对照原已批准计划，只有原有 `mode=none` 的 A-roll 窗口才可继续准备和渲染；不能先把 B-roll 改标为 A-roll 再检查，也不能从被 B-roll 覆盖的原始 A-roll 取样来代替该处成片。样片若需包含相邻 B-roll 作上下文，直接复用其原产物，不重做、不覆盖。开发样片和已验收整片分开保存，不能把这种选段错误算作贴片验收通过。

同一正式流程混用 HyperFrames 不透明 B-roll 与透明贴片时，使用 `hyperframes_native_adapter.create_artifact_probe`：按冻结的 alpha 合同分发到既有严格 MP4 或 QTRLE/ARGB MOV 检查。不把只接受不透明视频的 Doudou probe 用于透明贴片；组合检查器使用独立身份，不改写失败事务或沿用旧 probe 名称掩盖变化。

三节点流程先检索 HyperFrames Registry 的原生 `hw-pipeline`。它自带逐节点手绘框和曲线连线动效；正式入口是 `scripts/hyperframes_hw_pipeline_adapter.py` 的 `create_adapter`、`create_binding`、`create_artifact_probe`，调用 `scripts/render_hyperframes_hw_pipeline.cjs` 读取锁定的上游块，替换三节点文案、时长、位置及中文字体／背景可读性参数，再由 HyperFrames 真正渲染。保持64px标签的原生像素尺寸，从1920×1080画布上方截取1080×608区域，再透明补到1080×1920，转成QTRLE/ARGB MOV，交给既有 `ReferenceProcessAdapter` 和正式合成器；不重写动效。此组件仅用于真实三步流程，不硬套比较、门槛或抽象结论。`brief` 必须包含当前批准的三节点标签、帧数、各节点入场帧 `label_frames`、对应源转写词的 `word_anchors` 与 `source_binding`；adapter 将标签实际显现时刻对照批准的 Scribe 词和剪后时间轴，不能等间隔套用旧样片。它还复核批准的 VisualPlan、A-roll 哈希、段落时钟、上游源码及依赖版本。制作时安排框、箭头、文字避开人物和字幕。

## 当前可执行接口

固定原生布局须先核对真实字号。当前 `before-after-wipe` 的 `.baw-chip` 为 `min(3cqw,4.2cqh)`，1080像素宽容器内最多32.4像素，公开参数未提供独立字号；不能把它当作已满足关键标签可读性的候选。若本句必须依赖这些标签，且合法静态容器也无法满足阅读标准，则保留完整匹配缓存并排除此项当前用法，再联合分配；不修改上游样式、隐瞒文字或放宽字号来保留渠道数。

同一原生 `before/after` 公开内容槽可承载关键大字与静态图形，原生 chip 可用公开参数留空。用 `bind_native_slots(..., labels={"before": <前态原词>, "after": <后态原词>})` 显式绑定槽文字；每槽文字须逐字等于对应标签，支持静态 SVG `text` 字号及字体属性，仍禁止脚本、动态内容、样式覆盖和外链。原始源码、CSS、擦入时间线及词锚校验保持不变；不能因采用内容槽而放宽 chip 本身的32.4像素限制。

`notification-stack` 的标题字号为 `min(3.2cqmin, card_h × 0.24)`，默认1080×1920容器下最多34.56像素，公开参数没有独立字号。提醒语义可使它进入候选，但依赖标题传达关键信息时仍须核实合法可读的装配；未经验证的大容器放大设想不能计作已可兑现能力。此组件不适用上述 `before/after` 内容槽接法，不能据此宣称已解决字号。

批准清单的 `visible_text` 为空时，pin-board 与 before-after-wipe 只可从本镜实际保留的口播连续原词兑现标签，并将每条入场、变化锚点绑定到该标签内的真实词。已有非空 `visible_text` 仍逐字一致，不允许任意补写。规划未填写 `overlay_selection` 时，兑现声明只能验证已冻结的同一渠道、模板与对应关系；已有非空声明保持原样。

先按语义检索具体原生组件，不把 `hw-pipeline` 和紧凑线稿作为全片默认样式。正式透明贴片支持 `grid-card-assemble`、`notification-stack`、`toggle-flip`、`before-after-wipe`，以及专用适配的 `hw-pipeline`。并列对象用卡片，提醒用通知，状态切换用开关，真实做法／状态对照用擦入比较，真实三步操作才用流程。目录内其他组件不因底层支持 alpha 就算正式可用：必须同时具备内容槽、原生动作和已接通的词锚检查。当前 `strikethrough-replace` 只有静态演示与注释中的时间线建议，没有可直接调用的完整时间线或文本槽；`mk-specs-list` 的内容是源码常量。两者不进入新贴片选型，也不补写动作冒充原生调用。

`toggle-flip` 只用于原声确实描述同一对象在启用／停用等两种状态之间切换，须能说明切换前后各是什么。“不依赖／无需／不用云 API”是依赖关系或能力边界，不自动等于关闭开关；否定标签配关闭状态还可能产生反向理解。此类句先找能表达实际关系的原生组件；没有合适能力时保留真人，不用一个会动的开关凑贴片。词锚和显示文字正确，也不能替代这项语义判断。

上述原生来源的薄适配使用 `scripts/hyperframes_native_adapter.py`，统一新 brief schema 2：`source_binding`、`template_request`、`entry`、`assets`、`upstream_route`、`source_pins={route,sha256}`，以及 `composition={width:1080,height:1920,fps:24,frames,alpha}`。透明 A-roll 的 `alpha=true`；整屏 B-roll 为 false。保留所选源文件的 HTML/CSS/GSAP 实现，Job 只绑定原生内容槽、字体、词时钟和必要版式；不得用只带相同类名的自写图形冒充调用。原生 CLI 输出透明 ProRes 后转换 QTRLE/ARGB，真实检查 alpha、精确帧数、尺寸与像素比例。每个候选仍需在当前真人画面检查，不复用上游演示人像。

装配预检使用固定版本 HyperFrames 的真实 preview 页面、播放器和时间轴；手工 clone template 后执行脚本不构成实际装配证据。内嵌子组件的 `id="root"` 会变成 `data-hf-authored-id="root"` / `data-hf-inner-root`；宿主没有自己的 root 元素时，不能用 `#root .子类` 覆盖样式，应使用组件类或运行时保留属性，并检查真实计算样式。检查器按当前 mount 定位唯一实例，核对主、子时钟；启动或就绪失败不能降级为模拟通过。比较组件还在实际稳定事件后检查 after 标签与填充图形的祖先透明度、overflow 和 inset 裁剪交集，不强制从某一侧揭示。内容摆放方向必须与裁剪方向一致；非零交集只证明未被完全裁掉，残留小块、语义和完整可读性继续由正式实际画面检查判断。

逐帧检查只覆盖当前 mount 及宿主中存在的前后边界帧，保留宿主时间坐标，不扫描其余空窗。正式入口按条目数和有效帧数分配有上限的检查时间，超时报条目、阶段和已检查帧数，保持失败，不判作画面不合格或模拟通过。全组复用一个浏览器；Chrome 在执行前登记独立进程组与启动身份，Python 拥有检查临时目录，先停登记进程，再读取最终记录回收浏览器，覆盖启动未交接、单条超时及整组超时。检查缓存、浏览器资料和项目副本均留在该临时目录；不扫描或关闭用户已有浏览器，也不重签旧 Job、重做已批准成片。

整屏 B-roll 的时间推进或拖延可选同一适配器的 `hyperframes/beat-timeline` 原生有序节拍：只绑定公开的 `beatCount`、`interval`、`labels` 和父级时窗，保留其逐拍进入与退场。它不是通用日历，也不自动证明某个产品已执行任务；按本句使用真实时间标签和明确未完成状态，不伪造日期或改写原生时间线。此入口尚未补齐透明贴片的实际词锚接法，不进入当前 A-roll 选型。

薄适配不包括重写主要布局或时间线。若一张组件需要改写核心动作才能表达本句，换一个现成入口；不能因为组件名字成熟，继续把所有含义改成三框、双框或标题。标题/关键词与普通字幕重述相同内容时不算新增贴片。已有词锚、避脸、单字幕轨和已确认内容保留检查均继续生效。

`notification-stack` 不显示正文时，显式传入公开 `bodies` 逗号列表中的空项，例如单条通知用 `bodies: ","`。省略此字段或传空字符串会触发上游英文示例正文；词锚检查通过仍须检查实际卡片，不能把默认示例带进成片。父级静态摆放按本次原生画布和真人安全区检查，旧片的负 y 偏移或缩放值不能直接当作可用布局；确认卡片全边界和最终计算后的字号，再复用该产物。


补充贴片的样片通过后，必须立即更新当前正式 director 的对应组件、原生 brief/source binding 和 `manifests/confirmed-content.json`；详见[视觉修订的保留检查](visual-revision-reuse.md#已确认内容的保留检查)。后续只修改开头、剪切或 B-roll 时，贴片默认保留并按词锚重绑定，不再从早期无贴片计划覆盖。保留记录有而正式计划没有的贴片，正式入口直接报错。

同风格三节点流程直接调用上述 HyperFrames 入口。双项对比改选真正支持对比的现成组件；不通过删除箭头或另写原语状态转场改造成新动效。真实口播窗口允许 3–15 秒，不为凑时长延长镜头。下列 TalkCraft 原语关系是历史结构适配记录，不进入新选型；已有确认内容保留，不回退旧大面板或越界节点。

历史 `edit.hd.tools.talkcraft_overlay` 提供 `create_adapter`、`create_binding`、`create_artifact_probe`，项目入口为 `edit/hd/integrations/talkcraft/aroll-overlay/render.mjs`，通过既有 `ReferenceProcessAdapter` 执行。它不取得新制作原生场景资格；不能只因导入了原语，就继续自行编写主体动作。

- 依赖身份：`hd-talking-head-talkcraft-overlay`，Remotion 4.0.520；与 108 张 qualified 整屏卡的 `hd-talking-head-talkcraft` 分开。
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

## 制作与交付

按真实语义、词锚和原生接口制作透明贴片，字幕与人物避让。文件可用及必要规格检查后随全片一次合成，不设置本期样片、canary 或逐帧质量审批；原生 Skill 技术 QA 保持不变。
