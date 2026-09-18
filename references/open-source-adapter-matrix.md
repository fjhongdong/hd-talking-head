# B-roll 开源能力适配矩阵

本矩阵是 10 个长期本地参考项目的执行边界。它们不是 10 套并行启动的完整应用，而是按单个 `ShotRecipe` 延迟加载的能力源。每个镜头只有一个主渲染器，重型并发永远为 1。

默认根目录：`<project>/参考项目/B-roll开源方案`。目录可由环境适配层改写，但仓库名、入口身份和导入规则不得静默改变。

## 精确适配

| 能力 | 已验证入口 | 本 Skill 采用 | 禁止做法 |
| --- | --- | --- | --- |
| `html-video` | `packages/core/src/registry.ts`;<br>`packages/adapter-hyperframes/src/render.ts`;<br>`packages/adapter-remotion/src/` | 采用 content graph、模板 metadata/搜索和 engine adapter 合同；将已批准内容变为逐帧 HTML，再路由到 HyperFrames 或 Remotion。 | 不启动 Studio；不直接复制示例文案；不使用 16:9 默认。 |
| `video-shotcraft` | `references/shots/`; `demos/`; `assets/lib/` | 采用 152 张镜头配方和 2.5D/分层运动语法，用于补全 `entry/hold/exit` 和复杂 UI 走位。 | 不引入其 BGM 或横屏 composition；不将动效词当作内容。 |
| `erduo-broll-loop-engineering` | `erduo-broll-loop-engineering/scripts/create-production-profile.mjs`; `erduo-broll-loop-engineering/SKILL.md` | 采用 `truth`/可修订 `creativeProposal`、代表样片→五镜头 canary、哈希/联系表/六帧 QA；显式 profile 使用 1080×1920/24fps/silent。 | 不启用其多 Agent 调度；不把装饰循环当主动画。 |
| `video-use` | `helpers/render.py`; `helpers/timeline_view.py`; `helpers/pack_transcripts.py`; `SKILL.md` | `speech_cleanup` 采用 0.40 秒长停顿阈值与 0.08 秒呼吸边缘；`edit_structure` 直接调用 EDL renderer，使用音频主时钟、分段提取、30ms 音频边缘和剪点自检。启动预检必须 smoke 三个入口并验证 `speech_edit_v2.py` 阶段绑定。 | 不把目录存在当作已接入；不并发子智能体；不生成或混入背景音乐。 |
| `video-autopilot-kit` | `src/asset_selection.py`; `src/review_loop.py`; `src/media_delivery_qa.py`; `src/camera_transition_director.py` | 采用语义重合、近义度、疲劳/重复惩罚和人工评审类别，用来排序过了硬门的素材。 | 不引入整个 Editkin runtime；不让软分数越过硬门。 |
| `HyperFrames` | `registry/blocks/notification-cascade/notification-cascade.html`、`registry/blocks/chatgpt-exchange/chatgpt-exchange.html`；CLI/runtime | HTML/CSS/GSAP/D3/Three/SVG 信息视觉与透明贴片的主渲染器；已验证两套原生 9:16 入口，并使用 `--workers=1 --low-memory-mode --strict`。 | 不同时启动多页；不在渲染时让网页再搜索素材；不把四节点通知或四项聊天表格泛化为任意关系图、海报或对比。 |
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

`broll_capability_router.py` 编译 ShotRecipe v2，并只解析已冻结的依赖入口，不 import 或启动整个仓库。`code_generated` 通过现有依赖 Skill 和登记 adapter 执行，并保留 `invocation_record`。一个 component 不能同时让 HyperFrames 和 Remotion 做最终缩放/转场。

### 已验证模板入口

五类来源同级；模板优先级仅限已经批准的 `code_generated` 内部。先用 `scripts/verify_broll_template.py` 验证 `references/verified-template-registry.json`，再把验证输出交给 `candidate_from_verified_template_record`。固定优先顺序为 `verified_third_party` → `verified_local_canonical` → `custom_fallback`，但必须先通过当前语义、信息容量和 `adaptation_level` 硬门。

当前登记的 `html-video/frame-data-rollup` 来自 `html-video/templates/frame-data-rollup/source/DataRollup.tsx`，已用原始第三方源码真实渲染 1080×1920 样片；只用于 `bar_chart`、`numeric_comparison`、`data_summary`。HyperFrames Vignelli 虽能产出竖屏 MP4，但真实代表帧出现右侧裁切，因此不得写成 `verified_third_party`。这条失败经验说明“第三方模板”不等于“已验证模板”。

声明输入 schema 不等于实际参数绑定；源码或登记 adapter 必须真实消费输入并留下差分样片。OpenMontage `ComparisonCard` 已验证能参数化并原生渲染 1080×1920，但实际竖屏只形成狭窄的中部横向 UI 卡片，留下大面积无目的空白，因此不具备整屏模板资格。组件可复用不等于 `verified_third_party`；若把该组件与标题、背景、头像或其他区域重新编排成海报，登记为 `custom_fallback`，不能继承组件来源的第三方模板优先级。

`verified_third_party` 的 `structural` 改造会失去原验证身份；`verified_local_canonical` 可在已登记的自有结构合同内使用 `structural`。ShotRecipe 和最终 manifest 必须保存 `template_origin`、`verification_id`、版本、入口和源码/样片哈希。历史样片不代替当前文案三态 QA。

### 已验证第三方模板入口

五类来源同级；模板优先级仅限已经批准的 `code_generated` 内部。先用 `scripts/verify_broll_template.py` 验证 `references/verified-template-registry.json`，再把验证输出交给 `candidate_from_verified_template_record`。固定优先顺序为 `verified_third_party` → `verified_local_canonical` → `custom_fallback`，但必须先通过当前语义、信息容量和 `adaptation_level` 硬门。

当前登记有 8 条记录：3 条原生第三方入口，以及 5 条由本 Skill 自有适配器执行的 `verified_local_canonical` 入口。`html-video/frame-data-rollup` 来自 `html-video/templates/frame-data-rollup/source/DataRollup.tsx`，只用于 `bar_chart`、`numeric_comparison`、`data_summary`；`hyperframes/notification-cascade` 只用于恰好四个顺序节点后收束为结论的内容；`hyperframes/chatgpt-exchange` 只用于提问、回答、四项对照表与回读结论。两套 HyperFrames 入口分别由 `scripts/hyperframes_notification_adapter.py` / `scripts/render_hyperframes_notification.cjs` 和 `scripts/hyperframes_chatgpt_exchange_adapter.py` / `scripts/render_hyperframes_chatgpt_exchange.cjs` 接入真实 CLI，不是按截图重画。HyperFrames Vignelli 虽能产出竖屏 MP4，但真实代表帧出现右侧裁切，因此不得写成 `verified_third_party`。这条失败经验说明“第三方模板”不等于“已验证模板”。

本发布包当前有 8 条带双输入验证证据的整屏记录；20 个本地家族与参考仓库数量不等于已验证模板数量。五个本地 canonical 记录为 `process-relations`、`viewpoint-comparison`、`evidence-source`、`timeline-progression`、`quote-thesis-artword`；全部原生 1080×1920/24fps/无音轨，证据模板支持图片与视频，关系图和时间线还有动作顺序附件。DataRollup 历史设计样片为 30fps，仅用于验证来源和参考效果；Notification Cascade 的原生合同为 1080×1920、24fps、336 帧、14 秒、无音轨；ChatGPT Exchange 为 1080×1920、24fps、358 帧、14.916667 秒、无音轨。正式实例必须遵循各自执行合同，不能直接交付历史样片。DataRollup 会将数值四舍五入，且在最大/最小正值比达到 50 时自动改用对数高度；Notification Cascade 要求 4 个无数值信息单元和上游 ±20% 字符窗口；ChatGPT Exchange 要求 4 个无数值信息单元、22 个显式内容字段和包装器声明的中文容量。所有字段必须实际由 adapter 传入，当前文案仍需三态 QA。

声明输入 schema 不等于实际参数绑定；源码或登记 adapter 必须真实消费输入并留下差分样片。OpenMontage `ComparisonCard` 已验证能参数化并原生渲染 1080×1920，但实际竖屏只形成狭窄的中部横向 UI 卡片，留下大面积无目的空白，因此不具备整屏模板资格。组件可复用不等于 `verified_third_party`；若把该组件与标题、背景、头像或其他区域重新编排成海报，登记为 `custom_fallback`，不能继承组件来源的第三方模板优先级。

任何 `structural` 改造都失去原验证身份；只有 `tokens_only` / `content_reflow` 可继承证明。ShotRecipe 和最终 manifest 必须保存 `template_origin`、`verification_id`、版本、入口和源码/样片哈希。历史样片不代替当前文案三态 QA。

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
