# 上游场景 Skill 与本地渲染合同

本合同把父 Skill 的边界固定为：理解语义、选择并编排镜头、冻结批准素材、验收静帧与成片、合成 A-roll 小窗和唯一字幕轨。父 Skill 不重写上游动画引擎，也不把“参考过仓库”写成“调用过 Skill”。每个新场景必须先读取上游完整 `SKILL.md` 及所选 DIRECTOR、TECHNIQUE、STYLE（或 composition/motion/look）指引，再按上游工作流制作 source，最后才允许本地 runner 渲染。

## 选择与资格

先按 `semantic_match_score`，再按 `quality_score` 排序；同分才比较 `template_origin`，最后比较 `reuse_gap`。来源资格仍是硬门，不能替代语义或美术判断。`verified_third_party`、`verified_local_canonical`、`custom_fallback`、`structural` 是资格描述，不是语义替代链。新的自由场景即使使用开源代码，也不能冒充 `verified_third_party`；记录 `producer_type=dependency`、`dependency_id`。新制作不得新增动效算法、关键帧、曲线或替代时间线；历史 `custom_fallback / structural` 记录保持原名，不追认、不迁移。现成本地 canonical 不进入新选型。prompt 库只能提供提示词参考，不能充当制作依赖。

保留既有边界：HyperFrames 负责透明 A-roll/轻组件，TalkCraft 负责精确数据，Doudou 负责白板与思维导图，Paper 负责拼贴分层，Lovart Kling O1 负责已批准的场景动作。它们都是实际调用入口，不互相借用 producer 身份。父级仍统一处理圆窗、原口播和全片唯一字幕；场景输出无声、整屏、1080×1920。

### 先识别能力类型，再交给上游制作

- **现成模板/组件**：使用真实可编辑槽及原生参数，不重画已存在的动作。
- **风格创作工具包**（Lemo）：依照其完整导演和制作流程调用原生引擎、风格语法和动作工具；父级只提供内容参数、静态放置、公开 props 与 start/end 时钟，不在项目内重写场景动作。
- **生成服务**：使用所选 Skill 的提示词与生成工作流，沿用具体上传、模型和费用授权。

不得只借一个 renderer 再自写场景、动作或时序；没有可调用的原生动作时，批准前换候选或保留 A-roll，批准后失败停当前 route 进入 revision。

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

Lemo/OneTake 共用适配器支持以下固定来源；Adu 使用后述独立适配器：

| dependency_id | upstream_commit | 原生入口 |
| --- | --- | --- |
| `lemo-opuscar` | `f3c590dffab39419e2f3018416706e046986fe11` | `node core/render/video.mjs <scene>` |
| `onetake` | `cf09bde3e392c9aa32c4157f80cdbe1fa556685e` | `.venv/bin/python scripts/render.py index.html` |

依赖由 `ensure_visual_broll_skills.py` 在项目本地自动准备，脚本内固定 render 包版本；禁止全局安装、worktree 共享、自动更新或运行时联网拉取。Lemo 复用项目 Chrome，不运行自动 reset/setup；OneTake 使用项目 Python 3.12。两套依赖必须同时登记到正式 executor 与 `visual_plan`，运行时不支持即停止，不能只带 Skill 文件声称跨机器可执行。

本地适配合同由 `scripts/upstream_scene_adapter.py` 实现，原生 runner 由适配器调用（API 优先，CLI 仅用于探测和真实执行）：

```python
create_adapter(project_root, dependency_id, python_executable, brief_loader)
create_binding(adapter, brief_bytes, reference_sample)
create_artifact_probe(ffprobe)
```

`dependency_id` 仅允许 `lemo-opuscar` 或 `onetake`；`primary_renderer=HTMLCanvas`；适配器版本为 `1.0.0`。CLI 支持真实 runner 及本地探测：`--probe --project-root ROOT --dependency-id ID`。

创建 binding 后登记到 `component_adapters["code_generated"][dependency_id]`，并接入现有 artifact probe/执行链；不得另起旁路渲染器。

### Adu 独立结构改编（历史范围，不用于新选型）

旧结构改编保留原记录和已验收素材，但不进入新编译。新上游 `6ea0c875363739a30a4c1bcdfe798b43b15fb03c` 的 `vivid-sticker-performance@0.2.0-candidate / keyword-to-conclusion` 有原生竖屏，要求完整 8.06 秒、六个关键词并保留原生人物与品牌层；当前父级圆窗方案没有匹配的纯 B-roll 入口，因此本轮不创建绑定、不修改这些层、不裁短动作。这个结论只针对所查场景，不表示整个 Adu 库不可用。

`adu-motion-video` 使用独立的 `scripts/adu_motion_adapter.py`，不复用 Lemo/OneTake 的身份，也不把原仓库参考写成已调用。固定来源为 `4d9777d799c73e4ed212b2ecb6ec6cece33f98a7` 的 `classic-performance@1.0.0 / decompose-and-consolidate`；原作者时钟保持 60fps，父级输出为 1080×1920、24fps、无声、不透明。适配只保留原组对象编舞和 `timed_scene` 时间映射，删除人物口播、人物标签、品牌、普通字幕和音频；真实改编素材位于：

```text
skill-development/hd-talking-head/assets/adu-motion-video/scene.js
skill-development/hd-talking-head/assets/adu-motion-video/style.css
```

冻结的浏览器输入闭包为七项：`index.html`、`config.js`、`scenes.js`、`style.css`、`lib.js`、`macro_runtime.js`、`workflow.json`。源输入必须使用原组真实 cue ID `concept`、`decompose`、`result`，并由 `adapt_project.py` 的 `timed_scene` 在 60fps 作者时钟上编译，再采样到 24fps；不得把输出帧数直接当作 60fps 源帧数。三项 `part_cues` 只有在分别匹配三项焦点且归纳不早于第三项时才可接受，动作窗口、词锚冲突或末采样不相容就拒绝，不变速、不循环、不冻结补时。

`adu_motion_adapter.py` 提供 `prepare_scene(...)`、`create_adapter(project_root, dependency_id, python_executable, brief_loader)`、`create_binding(adapter, brief_bytes, reference_sample)` 和 `create_artifact_probe(ffprobe)`。准备输入须包含当前 `source_binding`、精确 `frames`、三项原生 `cues`、完整 `inputs`、口播原文、三项标签、结果及三项真实 `part_cues`；执行时重新原生编译并核对冻结工程，不接受任意 HTML 冒充调用。登记到 `component_adapters["code_generated"]["adu-motion-video"]`；绑定为 `custom_fallback / structural`、`HTMLCanvas`、不透明输出。

2026-10-02 已用原组示例内容通过原生 probe、五帧竖屏 stills，以及真实公共 `execute_component` 的冻结、原生 runner 与媒体探针，输出 432 帧、18 秒、1080×1920/24fps、H.264/yuv420p、SAR 1:1、无音轨。产物在 `<project>/edit/verify/stickman-adu-integration-20261002/adu-public-executor-fixture-rfyoqsn1/job/08-visual-assets/components/seg-native-layout-fixture/adu-r9.mp4`；批准计划和口播只在明确的 integration fixture 中模拟，不能称为真实 Adu 语段验收。渲染前过短时窗、词锚冲突和工程错配亦会拒绝。对当前 v54 全部口播的遍历没有发现同时满足“三项分解→归纳”、内部节奏和保护窗口的正式语段，因此该候选不得默认进入实际成片；只能在新的语段通过上述时序和静帧/成片验收后使用。

## Wise Motion 参数组件（接入候选）

先读 `<project>/skill-development/vendor/wise-motion/SKILL.md`、`REMOTION.md` 和公开内容槽说明。依赖检查／准备走 `ensure_visual_broll_skills.py --project-root <project> --skill wise-motion`；只在项目的 `skill-development/runtime/wise-motion` 安装固定 npm 包 `wise-motion@0.1.12`、Remotion `4.0.532`、React `19.3.0`。使用随包锁文件与原生素材安装脚本，不调用自动降级安装器、不升级父级 4.0.520。Git 文档来源固定为 `096b220cbe021cbba2d38e8a48fa3651ab8edbb7`，运行包身份单独记录；不假定 npm 包与该提交等价。

当前接入候选是 `orbit` 原生主体组件：五张带图形符号的卡片连续环行，位置、侧转、深度、大小和明暗由 `catalog/effects/continuous.js` 原样提供。原生画板为 640×360，周期 6000ms、`loop=true`，公开速度为 0.5–2。循环组件按真实口播时窗持续运行，不要求台词凑足整数周期，也不冻结末态补时；非循环候选仍须保留完整原生过程。原生卡片编号只是图形编号，不代表真实任务或竞品数量。

按原 Skill 的 `scripts/match.mjs` 查候选，再用 `scripts/show.mjs <id> --details` 核对真实主体动作和内容限制，并对照实际 npm 包。`orbit` 没有内容槽；只能传公开 props，文案和静态 AI 标识由父级编排。它可用于“持续关注多项信息”的示意，不是自动导演，也不能单独表达任务接管、发现变化或推送通知。文字逐字显现、划线和静态图标不能替代主体动作。固定 Siri 音乐指令、地中海雷达捕获等场景不因看起来会动就用于本期监看语义；静止飞机和微弱折翼也不能当作清晰主体动作。

调用 `wise_motion_adapter.create_adapter(project_root, node_executable, brief_loader)`、`create_binding(adapter, brief_bytes, reference_sample)` 和 `create_artifact_probe(ffprobe)`，登记到现有 `component_adapters['code_generated']['wise-motion']`。当前 adapter 版本为 `3.0.0`、模板标识为 `wise-motion/orbit-tracking-component`。brief 沿用 `source_binding / template_request / composition`，增加 `theme='light'`、短 `title`、三项 `context_labels` 和唯一 `layers` 项：`id='orbit' / content={} / from=0 / transparent=false / speed / layout`；请求家族为 `continuous_tracking`，不提供虚构业务数值。`layout` 保持 640×360 等比画板，位于竖屏安全区域。真正运动的卡片只由公开 `WiseMotionEffect` 生成，父级只做静态位置与文案；输出无声、不透明 1080×1920/24fps，父级统一接圆窗、原声与唯一字幕。

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
