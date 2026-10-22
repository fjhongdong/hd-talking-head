# 自有动效能力库

本库统一现有 A-roll 贴片、B-roll、可组合组件和设计／原生创作能力的理解与检索，不增加渲染器，也不合并它们的执行资格。维护数据为本包 `motion-capability-index.json`；入口为 `scripts/select_motion_capabilities.py`，项目接法为 `edit.hd.tools.motion_capabilities`。

> 本页与 `motion-capability-index.json` 中的 evidence 路径一律以**项目根**为基准(如 `skill-development/...`、`edit/hd/...`),不是 Skill 包内相对路径;换机或脱离项目目录时这些外链不随之迁移。

## 先理解，再建档

对每个具体原生入口读取当前说明、内容槽、动作实现及已有真实效果记录，再维护自己的 profile。相同 Skill 的不同模板分别记录；同一入口的贴片与 B-roll 接法分别核对。网站条目、模型名称、画风和 renderer 不是可复用动作。

profile 记录主体、可见动作、信息关系、人物感受、视觉特点、构图模式、可编辑内容、限制及证据路径；绑定 `reviewed_version` 和 `reviewed_sources`。无证据的标签保持空，不从分类名推断动作。动作写清作用对象，例如“词语二维飞入”，不能把文字／卡片移动或静态 presenter 当成人物业务动作。`summary` 以当前生产 Card／adapter 实际消费的输入为准，不沿用原 demo 的能力承诺。原 demo 可改而当前入口不可传的正文、数字、图片与兴趣点，明确写为固定内容；公开字段只通过校验而未显示时也注明。历史认可不等于所有新内容都美观。

TalkCraft 的 108 张卡按当前 `src/cards/*.tsx`、contract 与资格案例核对；库中逐卡列出已验证的 `raw.*` 字段、`scene_inputs.*` 槽和帧钟。`card-semantic-index.json` 的旧 demo 描述不再作为本库的动作正本；保留它与 `card-registry.json` 的原资格关联，以及 `card-event-capabilities.json` 的事件限制，不修改这些正本。每个实际 raw 输入必须完整匹配某个已验证字段组合；空、缺项或跨组合拼接返回待复核，额外字段继续拒绝。字段组合检查不绑定案例中的演示值，不代替原生值／帧校验，也不证明每个字段都影响画面。未有正式透明接法的卡片仍是组件，不因原生角色含 overlay 就进入 A-roll。

库同时列出当前原生入口、设计来源、待适配项和历史停用项。已有资格库中的旧 canonical、RelationMotion 与 SemanticState 只读引用，旧 Lemo／OneTake 自由场景、旧 TalkCraft 贴片及退出资格的场景不恢复调用。Flat／GBRO 仅提供设计，实际视频仍使用已批准的 Lovart 链路，不能把设计标签当作已生成的动作。

本轮从 CutCod 的公开资源目录接入一组可核对的 `eian-riso-broll` 原生信息模板，登记为同一 B-roll 入口下的 10 个语义 profile：`title`（章节标题）、`number`（数字强调）、`compare`（同单位数值对比）、`converge`（多项归类收束）、`network`（集合关系）、`focus`（选项突出）、`steps`（顺序流程）、`shot`（真实资料截图）、`quote`（结论引语）和 `versus`（旧新状态对照）。它们共同使用双色印刷纸面与原生 GSAP 时间轴，但不共享同一种语义：选择由口播主体、动作和关系决定，不按颜色或网站分类轮换。模板字段只写入我们自己的项目副本，第三方仓库保持原样。

Riso 的草稿预检与正式组装共用 `riso_output_contract`：`layer_role=base`、`layout_slot=full_frame`，`composition.family` 只允许 `single_full_frame` 与 `evidence_with_data_overlay`，且 `alpha=false`。适配器在执行前复核这些用途要求，不将全屏画面当作 A-roll 贴片。输出步骤按时间戳采样到 24 帧，并真正转换为有限范围 `yuv420p`，不通过改标签或放宽检查掩盖格式差异。已有 `number` 的一条 5 秒代表样片；其他 9 个模板只完成源码、内容槽和接法建档，不声称已逐一渲染验收。真实口播仍按当前内容检查语义、版式和实际动作。

这 10 个 profile 已计入当前能力档案：总条目由 156 增至 166，已登记可选入口由 101 增至 111，其中 B-roll 由 92 增至 102；`needs_adapter`、`excluded` 和历史条目保持不变。这些是入口登记数，不是逐模板画面验收数；`shot` 仍要求真实本地截图，所有模板均为信息图，不承担人物动作、情绪或软件操作的表达。

## 每条视频怎么用

1. 先理解整篇口播与真实时码，拆出每段的主体、动作、变化、关系、人物负担，以及否定、条件和不能提前展示的后续结果。先提出表现方式，再根据具体候选修正；不预先锁死某个 Skill 或模板。
2. 从全库查询候选。检索需有完整动作或关系短语命中；中文单字、普通文字碎片、人物素材、情绪或配色不能独立使候选入选。主体与美术线索只辅助排序，返回 `matched_dimensions` 展示实际依据，允许无匹配。宿主先理解原话，再用既有 `semantic_goal / required_change` 表达预期可见变化；不新增另一套意图语言、配额或随机轮换。`search` 不是语义模型，否定、条件、隐喻与真实动作仍由宿主复核；无匹配不等于上游一定没有能力，先核对目录与实际入口。限制、候选名和选择理由不作适配证据。
3. 比较候选能否完整表达本句。并列不画成流程，“无需”不自动画成关开关，推测不画成事实，人物痛点不靠卡片移动代替。擦入比较可表达有原文依据的做法、方案或状态对照，不限于时间前后；它不能凭空增加因果或状态切换。美观、多样性比较真实构图与动作，不只看颜色或 Skill 名。
4. 把选择交回原有 treatment：B-roll 使用 `skill_selection` 的 `discover → assign → check`；贴片使用 `overlay_selection`、`overlay_alignment`。不新增另一套批准记录或最终计划 schema。现有发现结果带上本库 capability 描述，贴片入口核对当前用途和版本；未知或版本变化的元数据先复核，不能静默套用旧标签。
5. 在整片时间线上协调新增和复用镜头。统一色调、字级和可读性，不统一卡片形状；保持已确认镜头。贴片不能顶替 B-roll 数量或挪掉已确认 B-roll。相关但未接通的命中明确记录缺口，不混入实际执行选择。

统一入口均经项目现有 Python 入口运行，不加 `--prepare`，这些命令不安装、不更新、不访问生成服务、不渲染或修改 Job：

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/select_motion_capabilities.py catalog --project-root <project> --summary-only

<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/select_motion_capabilities.py search --project-root <project> \
  --use aroll_overlay --query "并列 要点 累积"

<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/select_motion_capabilities.py search --project-root <project> \
  --use broll --query "人物 反复操作 资料 困扰"

<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/select_motion_capabilities.py check --project-root <project> \
  --director-brief <已有director-brief.json> --treatment <已有treatment.json> \
  --job-dir <已有Job目录>
```

`catalog` 是档案，不是可执行计数。`supported` 延续原发现器的入口登记含义，不证明本机环境已通过；`needs_adapter`、`not_registered`、`excluded` 均不能作为已接通入口。`search --include-history` 仅用于追溯，不能恢复执行。设计来源即使在 B-roll 检索中命中，也只有设计用途。

## 不能由索引替代的检查

- A-roll：真实透明通道、原生动作／词锚、入场与退场、真人和字幕避让。
- B-roll：既有模板／组件资格、当前内容容量、主体动作、整屏构图、圆窗和唯一字幕、末尾连续性。
- 共用：当前来源及版本、实际输入绑定、全速动作、美观度、语义与有效信息密度。动作标签不证明当前内容实际消费正确。

`check` 只读现有 workflow 中批准的逐字稿和时间线映射，核对其原记录哈希后复用字幕映射函数取剪后真实台词；不加载、迁移或重签 Job。原生 brief 从 treatment 的既有 `brief_path` 读取并与 binding 已有 SHA 对比，贴片 route 从实际 brief 取得，不能从 binding 自造一个相同值。`selection_reason`、自填关系和模板名不参与台词证据。

标签命中结果只进入 `checks[].retrieval`，不决定语义状态。没命中不等于错配，命中也不能替代宿主判断。宿主先从原声提取完整命题，保留对象、否定、条件与当前已说到的结果，再对照实际输入给出判断；选择理由、语义目标和创作要求都不能自证实际内容已经匹配。

### 有出处的语义判断

宿主在当前 treatment 的 `semantic_assessments` 为每个动效组件记录一条判断，不新增审批文件或用户确认门：

```json
{
  "segment_id": "seg-example",
  "component_id": "scene",
  "candidate_id": "overlay:grid-card-assemble",
  "verdict": "pass",
  "reason": "说明原文命题与实际内容的对应，明确直接表达、摘要或隐喻及未表达的部分。",
  "transcript_refs": [
    {"start_word": 0, "end_word": 3, "quote": "对应词段的完整原文", "basis": "current_clause"}
  ],
  "content_refs": [
    {"path": "native-inputs/example/brief.json", "sha256": "当前绑定的实际SHA256", "pointer": "/title", "value": "实际显示标题"}
  ]
}
```

示例中的索引、文案和哈希是格式说明，必须替换成当前真实输入。`start_word` 为剪后映射词列表的零基索引，`end_word` 不包含尾项，不是原转写的字锚编号。`current_clause` 必须覆盖当前时窗的完整词段，不可删掉否定词再引用。必要上文用独立 `basis=recap` 引用，只取同话题中已经说过的最少内容；不能引用未来台词补证。一个标签包含两个事实时分别说明出处，不将跨句事实冒充当前原文。普通字幕和原生事件继续使用原合同的字锚。

`content_refs` 只接受该组件哈希绑定的 brief 或其声明的冻结文件。JSON 用 `pointer/value` 定位实际内容；文本场景文件用 `path/sha256/quote` 引用真实源码片段。brief 中的 `template_request`、`creative_handoff`、来源和画布信息不是可见内容证据。OpenFilm 必须引用本条冻结场景的实际内容，不能仅引用通用能力、制作要求或旧场景。宿主仍要读懂场景动作；程序确认引用存在不等于机器独立证明语义正确。

`verdict` 为 `pass / fail / needs_review`。缺判断、重复判断、原文或内容引用失效时待审；有效判断才能采用其结论。原文或绑定内容变化后旧判断不能沿用。已有已验收视频不补写此字段、不迁移或重新验收。

### 原生检查与状态

候选发现沿现有 adapter 登记携带 `adapter_module`，离线检查直接调用该接法已有的 `validate_brief`，Paper／Whiteboard 复用现有 wrapper 校验，TalkCraft 复用生产 brief 合同和已验证字段组合。DataRollup、Notification Cascade 与 hw-pipeline 等现有 Node 接口只调用 `--validate`，在读取浏览器或运行渲染前返回；缺现有 Node 时待审，不安装。设计 Skill 的原生 JSON 检查标为 `not_applicable`，不因此失败；其 provider、实际素材与输出检查仍按原合同执行。没有可用入口的必需检查明确标未覆盖，不能假装已通过。

检查只报告各校验器实际覆盖的输入约束，不调用 `check_runtime / create_adapter / render`。输入约束失败或有效宿主判断明确不符时为 `fail`；缺证据、无有效判断或检查未覆盖时为 `needs_review`；必需项均完成才是离线 `pass`。优先级为 `fail > needs_review > pass`。报告明确语义结论来自宿主，原生输入通过不能替代语义判断。

Skill 管理的新 Job 在正式视觉发布前执行同一离线检查，并将结果合并到原有 `visual-routing.md`；未通过时在任何冻结或发布写入前停止。它不启动原生 timeline、浏览器或媒体工具，不能证明词锚、alpha、实际画面或本次成片验收通过。正式流程继续保留原有词锚、运行环境及视觉检查，不重复审查已验收成片。

## 更新与维护

schema 2 的 `reviewed_sources` 逐项保存 evidence 中实际生产源码、契约、相关上游入口及接法的 SHA-256；不包含索引自身，不给检索代码或无关环境文件建立循环身份。新 Job 按原有依赖更新合同核查上游。即使 adapter 版本号没变，实际来源与已审阅摘要不符也会停止并指出档案和文件；Flat／GBRO 的 `source` 字符串不能绕过这一检查。入口、内容槽、动作、容量或版式变化时，只复核相应 profile 和接法，再由维护者显式更新摘要；加载和检查命令不自动重签标签。网站分类变化不等于能力失效。

不将网站接成生产运行时依赖，不批量安装目录中的所有资源。新的来源先进入待核对／待适配档案，实际加入调用池仍按既有入口、资格和授权合同办理。当前已批准 Job 不静默更新版本，不回写历史 treatment、标签或批准，不重做已验收媒体。
