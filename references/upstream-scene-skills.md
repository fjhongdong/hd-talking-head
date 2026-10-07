# 上游场景 Skill 与本地渲染合同

本合同把父 Skill 的边界固定为：理解语义、选择并编排镜头、冻结批准素材、验收静帧与成片、合成 A-roll 小窗和唯一字幕轨。父 Skill 不重写上游动画引擎，也不把“参考过仓库”写成“调用过 Skill”。每个新场景必须先读取上游完整 `SKILL.md` 及所选 DIRECTOR、TECHNIQUE、STYLE（或 composition/motion/look）指引，再按上游工作流制作 source，最后才允许本地 runner 渲染。

## 选择与资格

先按 `semantic_match_score`，再按 `quality_score` 排序；同分才比较 `template_origin`，最后比较 `reuse_gap`。来源资格仍是硬门，不能替代语义或美术判断。`verified_third_party`、`verified_local_canonical`、`custom_fallback`、`structural` 是资格描述，不是语义替代链。新的自由场景即使使用开源代码，也不能冒充 `verified_third_party`；记录 `producer_type=dependency`、`dependency_id`，自研时如实记录新增实现。现成动画优先，只有上游能力确实不足且已记录缺口时才允许最小自研。prompt 库只能提供提示词参考，不能充当制作依赖。

保留既有边界：HyperFrames 负责透明 A-roll/轻组件，TalkCraft 负责精确数据，Doudou 负责白板与思维导图，Paper 负责拼贴分层，Lovart Kling O1 负责已批准的场景动作。它们都是实际调用入口，不互相借用 producer 身份。父级仍统一处理圆窗、原口播和全片唯一字幕；场景输出无声、整屏、1080×1920。

### 先识别能力类型，再交给上游制作

- **现成模板/组件**：使用真实可编辑槽及原生参数，不重画已存在的动作。
- **风格创作工具包**（Lemo）：依照其完整导演和制作流程创作本期场景，复用原生引擎、风格语法和动作工具；本期构图与场景代码如实记为 `custom_fallback / structural`，不是“自建动画引擎”，也不是已验证填词模板。
- **生成服务**：使用所选 Skill 的提示词与生成工作流，沿用具体上传、模型和费用授权。

不得因为工具包没有固定模板就只借一个 renderer，亦不得为了证明调用而机械增加函数数量。

### Lemo 原生导演交接

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

### Adu 独立结构改编（当前候选范围）

`adu-motion-video` 使用独立的 `scripts/adu_motion_adapter.py`，不复用 Lemo/OneTake 的身份，也不把原仓库参考写成已调用。固定来源为 `4d9777d799c73e4ed212b2ecb6ec6cece33f98a7` 的 `classic-performance@1.0.0 / decompose-and-consolidate`；原作者时钟保持 60fps，父级输出为 1080×1920、24fps、无声、不透明。适配只保留原组对象编舞和 `timed_scene` 时间映射，删除人物口播、人物标签、品牌、普通字幕和音频；真实改编素材位于：

```text
skill-development/hd-talking-head/assets/adu-motion-video/scene.js
skill-development/hd-talking-head/assets/adu-motion-video/style.css
```

冻结的浏览器输入闭包为七项：`index.html`、`config.js`、`scenes.js`、`style.css`、`lib.js`、`macro_runtime.js`、`workflow.json`。源输入必须使用原组真实 cue ID `concept`、`decompose`、`result`，并由 `adapt_project.py` 的 `timed_scene` 在 60fps 作者时钟上编译，再采样到 24fps；不得把输出帧数直接当作 60fps 源帧数。三项 `part_cues` 只有在分别匹配三项焦点且归纳不早于第三项时才可接受，动作窗口、词锚冲突或末采样不相容就拒绝，不变速、不循环、不冻结补时。

`adu_motion_adapter.py` 提供 `prepare_scene(...)`、`create_adapter(project_root, dependency_id, python_executable, brief_loader)`、`create_binding(adapter, brief_bytes, reference_sample)` 和 `create_artifact_probe(ffprobe)`。准备输入须包含当前 `source_binding`、精确 `frames`、三项原生 `cues`、完整 `inputs`、口播原文、三项标签、结果及三项真实 `part_cues`；执行时重新原生编译并核对冻结工程，不接受任意 HTML 冒充调用。登记到 `component_adapters["code_generated"]["adu-motion-video"]`；绑定为 `custom_fallback / structural`、`HTMLCanvas`、不透明输出。

2026-10-02 已用原组示例内容通过原生 probe、五帧竖屏 stills，以及真实公共 `execute_component` 的冻结、原生 runner 与媒体探针，输出 432 帧、18 秒、1080×1920/24fps、H.264/yuv420p、SAR 1:1、无音轨。产物在 `<project>/edit/verify/stickman-adu-integration-20261002/adu-public-executor-fixture-rfyoqsn1/job/08-visual-assets/components/seg-native-layout-fixture/adu-r9.mp4`；批准计划和口播只在明确的 integration fixture 中模拟，不能称为真实 Adu 语段验收。渲染前过短时窗、词锚冲突和工程错配亦会拒绝。对当前 v54 全部口播的遍历没有发现同时满足“三项分解→归纳”、内部节奏和保护窗口的正式语段，因此该候选不得默认进入实际成片；只能在新的语段通过上述时序和静帧/成片验收后使用。

## Lemo/OneTake 的 brief 与 workflow

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
