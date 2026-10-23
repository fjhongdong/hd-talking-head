# B-roll 开源能力适配矩阵

本矩阵说明 9 个长期本地参考项目的采用边界，不表示它们全部已接通为制作 Skill。参考方法、渲染引擎与可调用场景分开判断；新制作的可调用候选以 [统一选型入口](broll-capability-router.md#唯一选型入口与记录) 为准。它们不是 9 套并行启动的完整应用，而是按单个 `ShotRecipe` 延迟加载的能力源。每个镜头只有一个主渲染器，重型并发永远为 1。

默认根目录：`<project>/参考项目/B-roll开源方案`。目录可由环境适配层改写，但仓库名、入口身份和导入规则不得静默改变。

## 精确适配

| 能力 | 源码入口 | 本 Skill 采用 | 禁止做法 |
| --- | --- | --- | --- |
| `html-video` | `packages/core/src/registry.ts`;<br>`packages/adapter-hyperframes/src/render.ts`;<br>`packages/adapter-remotion/src/` | 采用 content graph、模板 metadata/搜索和 engine adapter 合同；将已批准内容变为逐帧 HTML，再路由到 HyperFrames 或 Remotion。 | 不启动 Studio；不直接复制示例文案；不使用 16:9 默认。 |
| `erduo-broll-loop-engineering` | `erduo-broll-loop-engineering/scripts/create-production-profile.mjs`; `erduo-broll-loop-engineering/SKILL.md` | 采用 `truth`/可修订 `creativeProposal`、代表样片→五镜头 canary、哈希/联系表/六帧 QA；显式 profile 使用 1080×1920/24fps/silent。 | 不启用其多 Agent 调度；不把装饰循环当主动画。 |
| `video-use` | `helpers/transcribe.py`; `helpers/render.py`; `helpers/timeline_view.py`; `helpers/pack_transcripts.py`; `SKILL.md` | 字级转写由宿主实际调用 `transcribe.py`，项目 `transcribe.transcribe_job` 只验收原始 Scribe JSON 与调用证据；`speech_cleanup` 采用 0.40 秒长停顿阈值与 0.08 秒呼吸边缘；`edit_structure` 有剪点时直接调用 EDL renderer，使用音频主时钟、分段提取、30ms 音频边缘和剪点自检。启动预检 smoke 四个入口。20 秒真实片段已验证原始输出与零时长词适配；完整原片仍须独立授权和实测。 | 上传原声和消耗额度前取得本次许可并确认凭据；不把目录存在、读取说明或 helper 冒烟当作真实转写；不并发子智能体；不生成或混入背景音乐。 |
| `video-autopilot-kit` | `src/asset_selection.py`; `src/review_loop.py`; `src/media_delivery_qa.py`; `src/camera_transition_director.py` | 采用语义重合、近义度、疲劳/重复惩罚和人工评审类别，用来排序过了硬门的素材。 | 不引入整个 Editkin runtime；不让软分数越过硬门。 |
| `HyperFrames` | `registry/blocks/notification-cascade/notification-cascade.html`；通用原生组件及 CLI/runtime | 信息视觉与透明贴片渲染器。Notification Cascade 按活动资格调用；其他原生场景与透明贴片按各自用途调用，使用 `--workers=1 --low-memory-mode --strict`。 | 不同时启动多页；不在渲染时搜索素材；不把技术路由都当成完整 B-roll；已退出资格的 ChatGPT Exchange 不进入新选型。 |
| `Remotion` | `packages/renderer`; `packages/bundler`; `packages/cli` | 复杂中文排版、真实 UI、2.5D 镜头、负责任布局和头肩头像的可编程渲染器。Composition 必须显式 1080×1920/24fps，`concurrency=1`。 | 不构建整个 monorepo；不从横屏 composition 二次裁切。 |
| `OpenMontage` | `tools/tool_registry.py`; `tools/video/grok_video.py`; `skills/creative/prompting/grok-prompting.md` | 采用 capability registry/provider envelope；对精确模型 `grok-imagine-video` 直接包装 `GrokVideo`，支持 text/image/reference-to-video、9:16、无声、本地参考图 data URI。 | 不启动 Backlot/全流水线；不使用 `fallback_tools`；不重试；不换成 preview 模型。 |
| `Generative-Media-Skills` | `core/media/generate-video.sh`; `core/media/image-to-video.sh`; `schema_data.json` | 采用参数 schema、上传/轮询和多 provider 提示词编译思路；用户批准其 MuAPI 映射时才可调用。 | 当用户指定精确 `grok-imagine-video` 时不用它的 `grok-imagine-*-to-video` 别名代替。 |
| `Open-Generative-AI` | `packages/studio/src/models.js`; `videoToolCapabilities.js`; `videoWorkflows.js`; `modelCapabilities.js`; `imageInputContracts.js`; `utils/generationLifecycle.js` | 采用模型能力目录、输入契约和异步 task 生命周期，用于非 xAI 精确模型的环境适配。 | 不将 `grok-imagine-video-1-5-preview` 或 MuAPI 别名当作 `grok-imagine-video`。 |

## 统一镜头数据流

```text
已批准 content-analysis
  → VisualIntent（事实/人物/数字/关系/情绪）
  → 五类同级候选
  → 语义角色与来源分离评估
  → none / single / hybrid
  → ShotRecipe v2 冻结来源绑定
  → 单一主渲染器
  → 入场/稳定/退场三态 QA
  → canary 人工确认
  → 相同字节复用到正片
```

`broll_capability_router.py` 编译 ShotRecipe v2，并只解析已冻结的依赖入口，不 import 或启动整个仓库。`code_generated` 必须先读取并实际调用所选依赖 Skill，再由登记 adapter 执行并保留 `invocation_record`；父 Skill 只编排和验收。一个 component 不能同时让 HyperFrames 和 Remotion 做最终缩放/转场。

### 已验证模板入口

五类来源同级；候选先按 `semantic_match_score`、再按 `quality_score` 排序，同分才比较 `template_origin`，最后比较 `reuse_gap`。先用 `scripts/verify_broll_template.py` 验证 `references/verified-template-registry.json`，并保留当前语义、信息容量和 `adaptation_level` 硬门；资格不能覆盖语义。

当前登记的 `html-video/frame-data-rollup` 来自 `html-video/templates/frame-data-rollup/source/DataRollup.tsx`，已用原始第三方源码真实渲染 1080×1920 样片；只用于 `bar_chart`、`numeric_comparison`、`data_summary`。HyperFrames Vignelli 虽能产出竖屏 MP4，但真实代表帧出现右侧裁切，因此不得写成 `verified_third_party`。这条失败经验说明“第三方模板”不等于“已验证模板”。

声明输入 schema 不等于实际参数绑定；源码或登记 adapter 必须真实消费输入并留下差分样片。OpenMontage `ComparisonCard` 已验证能参数化并原生渲染 1080×1920，但实际竖屏只形成狭窄的中部横向 UI 卡片，留下大面积无目的空白，因此不具备整屏模板资格。组件可复用不等于 `verified_third_party`；若把该组件与标题、背景、头像或其他区域重新编排成海报，登记为 `custom_fallback`，不能继承组件来源的第三方模板优先级。

`verified_third_party` 的 `structural` 改造会失去原验证身份；`verified_local_canonical` 可在已登记的自有结构合同内使用 `structural`。ShotRecipe 和最终 manifest 必须保存 `template_origin`、`verification_id`、版本、入口和源码/样片哈希。历史样片不代替当前文案三态 QA。

### 已验证第三方模板入口

五类来源同级；候选先按 `semantic_match_score`、再按 `quality_score` 排序，同分才比较 `template_origin`，最后比较 `reuse_gap`。先用 `scripts/verify_broll_template.py` 验证 `references/verified-template-registry.json`，并保留当前语义、信息容量和 `adaptation_level` 硬门；资格不能覆盖语义。

活动资格及数量以 `verified-template-registry.json` 为准，实际新制作候选以 `select_broll_skills.py discover` 为准，两者不等同。Huashu 的 `y1_kurzgesagt` 仅支持三节点机制流程，`y2_vox` 仅支持单张横向来源图整行高亮，`t2_keynote_ui` 仅支持 `product_features` 的恰好三张原生功能卡。三条共用原生启动器，不改上游文件或动效，见 [Huashu 接入](huashu-native-motion.md)。`html-video/frame-data-rollup` 只用于 `bar_chart`、`numeric_comparison`、`data_summary`；`hyperframes/notification-cascade` 只用于四个顺序通知节点收束为结论，由 `scripts/hyperframes_notification_adapter.py` / `scripts/render_hyperframes_notification.cjs` 接入真实 CLI。ChatGPT Exchange 因正文和表格裁字已退出资格，历史样片与适配器不构成当前可用证明。

保留的本地 canonical、RelationMotion 与 SemanticState 登记用于历史证据，不进入新制作候选；参考仓库数、旧家族数和技术路由数都不是已接通的 B-roll 数量。DataRollup 历史设计样片为 30fps，仅用于来源与效果验证；正式实例须遵循当前执行合同。它会取整，且最大/最小正值比达到 50 时自动改用对数高度，不能用于不满足数值门的内容。Notification Cascade 固定为 1080×1920、24fps、336 帧、14 秒、无音轨，要求四个无数值信息单元与上游 ±20% 字符窗口；不得把它与 A-roll 的 `notification-stack` 混为一谈。所有内容字段必须实际传入，当前文案仍需三态 QA。原生组合组件、Flat/GBRO 设计来源及 Lovart 视频执行的区别，统一见 [候选准入与选型记录](broll-capability-router.md#唯一选型入口与记录)，不在此另建一份活动清单。

声明输入 schema 不等于实际参数绑定；源码或登记 adapter 必须真实消费输入并留下差分样片。OpenMontage `ComparisonCard` 已验证能参数化并原生渲染 1080×1920，但实际竖屏只形成狭窄的中部横向 UI 卡片，留下大面积无目的空白，因此不具备整屏模板资格。组件可复用不等于 `verified_third_party`；若把该组件与标题、背景、头像或其他区域重新编排成海报，登记为 `custom_fallback`，不能继承组件来源的第三方模板优先级。

`verified_third_party` 的 `structural` 改造会失去原验证身份；只有 `tokens_only` / `content_reflow` 可继承第三方证明。`verified_local_canonical` 可在已登记的自有结构合同内使用 `structural`。ShotRecipe 和最终 manifest 必须保存 `template_origin`、`verification_id`、版本、入口和源码/样片哈希。历史样片不代替当前文案三态 QA。

## 素材与渲染决策

- `local_material` 和 `official_material`：真实媒体必须成为已批准 component 的实际内容，代码只负责容器、标注、来源与进退场。
- `code_generated`：数据、对比、流程、关系图、真实 UI 讲解和技术演示调用已冻结依赖 Skill；信息密度超出容量时切镜头，不缩成小字。
- `external_stock`：真实场景、行为、地点或氛围镜头保留 provider 素材 ID、作者、素材页和许可记录。
- `ai_generated`：先绑定已批准生成文件的路径、字节数和 SHA-256；文件不存在时 blocked，不以其他 kind 的产物代替。
- B-roll 边界：用 8–12 帧 alpha 显隐回到同时间轴 A-roll；不复制末帧、不突然缩放、不添加黑场。
- 头像：从同时间轴 A-roll 派生单一 256px 头肩圆形轨，位于 y=1420–1676，不超过 soft-safe 1700。

## 精确 Grok 合同

用户选择 `grok-imagine-video` 时，路由结果必须包含：

```json
{
  "model": "grok-imagine-video",
  "provider_adapter": "OpenMontage:GrokVideo",
  "audio": "none",
  "canvas": "1080x1920",
  "heavy_concurrency": 1
}
```

调用前仍要在本 Job 环境门确认 endpoint、账号连接、参考图要求、额度和用户是否修改上次配置。`GrokVideo` 的 retry/fallback metadata 不等于本 Job 的执行选择；本 Skill 包装层只发一次请求，暂停后只展示 `retry_same_strategy` 和 `replan_visual_direction`。
