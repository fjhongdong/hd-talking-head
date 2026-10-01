# A-roll 透明贴片：编排、调用、验收

先读取实际使用的上游 Skill。现成组件能表达本句关系时直接调用；仅有原语而需要组合新关系时，明确记录上游复用部分与本项目新增部分。不要把普通字幕放大重复一次，也不要为所有新口播硬套同一张示意图。

三节点流程先检索 HyperFrames Registry 的原生 `hw-pipeline`。它自带逐节点手绘框和曲线连线动效；正式入口是 `scripts/hyperframes_hw_pipeline_adapter.py` 的 `create_adapter`、`create_binding`、`create_artifact_probe`，调用 `scripts/render_hyperframes_hw_pipeline.cjs` 读取锁定的上游块，替换三节点文案、时长、位置及中文字体／背景可读性参数，再由 HyperFrames 真正渲染。1920×1080 原生画布等比缩到竖屏上方，转成 1080×1920 透明 QTRLE/ARGB MOV，交给既有 `ReferenceProcessAdapter` 和正式合成器；不重写动效。此组件仅用于真实三步流程，不硬套比较、门槛或抽象结论。`brief` 必须包含当前批准的三节点标签、帧数、各节点入场帧 `label_frames`、对应源转写词的 `word_anchors` 与 `source_binding`；adapter 将标签实际显现时刻对照批准的 Scribe 词和剪后时间轴，不能等间隔套用旧样片。它还复核批准的 VisualPlan、A-roll 哈希、段落时钟、上游源码及依赖版本。样片通过不等于新 Job 已批准；实际真人画面仍需检查框、箭头、文字不越界、不压头发、脸和字幕。

## 当前可执行接口

已确认组件必须落实到每个适用镜头，不能只替换样片中的一个镜头就沿用其余被否决的旧贴片。全片报审前按正式 VisualPlan 列出全部 `aroll_with_overlay`，对照各自实际产物与已确认设计；任何被用户否决的样式仍存在，旧预览即未通过。文件名、渲染完成或相同视觉轨哈希不能证明视觉修复完成。

同风格三节点流程直接调用上述 HyperFrames 入口；双项对比可用同一上游原生节点绘制能力，`template_request.semantic_family=dual_contrast`、两组标签/词锚，并去掉连接箭头，避免将对比误画为因果。这是结构适配，不冒充原生双项模板。真实口播窗口允许 3–15 秒，不为凑时长延长镜头。门槛移动等不能由该组件表达的关系仍用下列 TalkCraft 原语适配，按已确认的紧凑上方版式重新验收；不回退旧大面板或越界节点。

不适合 `hw-pipeline` 的关系可用 `edit.hd.tools.talkcraft_overlay` 的 `create_adapter`、`create_binding`、`create_artifact_probe`。原生组件入口为项目内 `edit/hd/integrations/talkcraft/aroll-overlay/render.mjs`，通过既有 `ReferenceProcessAdapter` 执行；不是另建合成器。

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
- 贴片按完整画布原坐标合成，不缩放到 B-roll 容器。安全区外不承载有效信息；当前适配图形位于画面上方，字幕位置不变。更换位置、关系、样式或文案容量须重新验收。

## 必须验收

真实输出为单视频轨的 QTRLE/ARGB MOV。必须解码检查透明通道和入场/中段/退场，不接受只看流信息；VP9 中间文件不可直接交给默认解码器造成黑底。正式合成对全范围原片做明确色彩转换后输出标准 yuv420p，不放宽规格检查。

canary 必须纳入有贴片的 A-roll；资产阶段复用已通过的 canary 字节。字幕阶段在 A-roll 和有口播 B-roll 都显示同一普通字幕轨，B-roll 字幕避让沿用本 Job 已批准参数的圆形人物小窗。最终还需检查贴片未遮人物、不是字幕复述、音轨与同一源区间一致。

美观验收在真人实拍底图上进行，不只看透明贴片单独画面：主体层级、字号与留白应与封面／B-roll 的本片视觉语言一致；一块大白板加少量字线、大片无目的空白、遮到头发或脸、与口播不符的抽象符号都退回重选组件或布局。用户反馈贴片太少时先盘点每段纯 A-roll 的可视化关系及已有贴片覆盖时窗，再按语义补足，不复制同一张图到无关句子。

开发期临时测试 Job 仅验证执行入口、复用及媒体结果，不形成用户的正式阶段批准。正式交付仍须最终预览与交付回执。
