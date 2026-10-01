# 视觉资产前置检查

本检查同时约束 `visual_direction` 的素材取得顺序，以及已批准 VisualPlan schema v3 / ShotRecipe v2 的执行条件。`visual_canary` 和 `visual_assets` 只消费已冻结配方。

## 0. `visual_direction` 的素材取得顺序

`visual_direction` 先根据语义确定 kind 和 provider，不因当前连接状态改选其他来源。随后在首次请求前完成所选 provider 的连接检查；检查通过后，再搜索、下载或生成并写入当前 Job。实际文件、来源、许可、generation identity 和 SHA-256 校验完成后，冻结实际 `source_bindings` 并编译 ShotRecipe v2，最后才进入 `ready_for_review`。

这一顺序不是来源优先级：语义选型在前，连接检查只判断已选路线能否继续。本 Job 的基础账号连接在启动时已确认；当草案选中具体 provider 时复核该项，不需要先伪造完整 ShotRecipe。完整计划冻结后再运行 schema、binding 和实际入口复核，然后报审。

## 1. 状态与输入

- 进入 `visual_canary` 或 `visual_assets` 前重新 `load_job`，确认 `visual_direction` 已 approved，并且当前阶段与工作流一致。
- 绑定 `visual-plan.json`、director brief、A-roll、avatar track、官方资料记录、许可记录和批准基线 ID；记录路径、字节数与 SHA-256。
- 验证画布为 1080×1920/24fps，片段时间轴覆盖完整且不互相重叠。
- 上游已交付且预览认可的 1080×1920 整屏 B-roll，底层组件在 ShotRecipe 中必须用 `layout_slot=full_frame` 且 `safe_zone` 四边为 0；否则正式合成会将整屏画面缩进内容框并补模糊背景。`visual_canary` 与 `visual_assets` 均检查实际合成视频的进入、稳定、退出原尺寸画面和圆形人物小窗，不能只验收子 Skill 的无声视频。配方不符时返回 `visual_direction` 修订，不在执行阶段暗改。
- 字体、可见文案、composition、头像规则、`safe_zone` 或来源绑定改变时，返回 `visual_direction` 形成 revision，不在执行阶段临时改写。
- 只接受 VisualPlan schema v3 和 ShotRecipe v2；不兼容旧 visual Job。

## 2. 五类组件闭包

逐段调用 `validate_shot_recipe_v2`，验证 mode 与 component 数量对应，再检查每个 component 的 `kind`、`semantic_role`、`layer_role`、executor、媒体类型、`render_window`、`safe_zone`、产物合同和精确来源字段。

- `local_material`：`material_id`、Job 内路径和 SHA-256 一致。
- `official_material`：`source_id`、publisher、HTTPS URL、snapshot、获取时间和 SHA-256 一致。
- `code_generated`：`dependency_id / entrypoint / producer_version` 与预检报告一致；`invocation_record` 可记录已完成的依赖 Skill 调用。
- `external_stock`：provider 素材 ID、作者、素材页、Job 内文件、`license_snapshot`、下载时间和 SHA-256 一致。
- `ai_generated`：provider、精确模型、endpoint ID、prompt 哈希、generation ID 和媒体 SHA-256 一致。

五类的检查形式不建立来源顺序。某个已批准 kind 暂时不可执行时，保持原配方并 blocked，只提供 `retry_same_strategy` 和 `replan_visual_direction`。

## 3. 代码组件与依赖 Skill

`code_generated` 不由视觉 runner 重新实现。它调用 ShotRecipe v2 已冻结的现有依赖 Skill：

- `html-video` 按具体登记入口选择 HyperFrames 或 Remotion；当前合格的 `frame-data-rollup` 使用 Remotion。独立 `hyperframes/notification-cascade` 与 `hyperframes/chatgpt-exchange` 使用 HyperFrames 原生 CLI；三者都按登记入口判定，不按仓库名猜引擎。
- `video-shotcraft` 使用 `SkillInvocationAdapter` 和 Remotion 执行镜头配方。

实际执行前，binding probe 返回的 dependency ID、entrypoint、producer version 和 adapter identity 必须与已批准配方一致。执行后 `invocation_record` 保留 argv、退出码和产物记录，作为 Skill 调用证据。

编排脚本仅为当前已批准计划实际选中的入口创建适配器并执行 binding probe；不得因旧脚本仍登记未使用入口而构造、检查或运行其依赖。启动阶段的基础必需依赖检查仍保留，所选组件的真实调用与产物验收不省略。

## 4. 官方资料、外部素材和生成媒体

已批准新视觉计划后，重新生成绑定该计划文件身份的依赖预检；不能沿用旧计划的报告。正式渲染前逐项核对所选 kind 的实际适配器是否接通，素材下载成功不等于执行入口接通。官方视频使用 `scripts/official_video_adapter.py:create_adapter(ffmpeg_executable)` 接到 `official_material`，保留上游下载来源与原 snapshot 身份，先以视频流复制去掉原资料音轨，再交给严格无声视频探针；最终只保留原口播声音。

原生全画幅 B-roll 的 `base / full_frame` 外层边距为零；子 Skill 已处理内部排版，父级不再次缩成带背景的资料卡。人物圆窗与统一字幕在父级合成，仍按各自避让规则验收。模板登记在同一进程、同一 Skill 发布身份下检查一次；重新加载路由不能导致每个镜头重复解码全部历史资格样片。新发布身份仍重新检查，不缓存失败结果，也不跳过本次素材和正式成片的检查。

命名人物、职务、组织、官方事实和精确数字都保留可核对的发布者、URL、访问时间、本地 snapshot 和 SHA-256。命名人物不使用生成脸、无来源截图或泛化人物图代替。

`external_stock` 在首次搜索前确认供应商连接状态。选中后保留 provider 素材 ID、作者、素材页和许可记录；不只保存下载文件。

`ai_generated` 在首次生成前确认 provider、账号连接、精确模型 ID、endpoint、参考图支持、9:16、无声输出和额度。有项目 adapter 时使用 `model_is_available()`；直接检查时使用正确的 `/v1/models`。选择 `grok-imagine-video` 时，模型列表必须包含该精确 ID。图生视频组件必须已绑定参考图及 SHA-256；文生视频只在配方明确选中时执行。

## 5. Generation 和尝试记录

- 累计 ledger 与当前 generation 分开报告。
- 当前 generation 只统计本轮 segment ID、实际请求数和已落盘资产。
- 本地字段、路径、绑定或媒体检查未通过时，外部请求数为 0。
- 只有实际发出生成请求才增加本轮尝试数。
- 媒体已生成但比例、解码、帧连续性或记录不一致时，保留实际结果和检查报告，不标记为 ready。

## 6. 产物一致性

`asset-manifest.json` 的资产类型字段是 `type`。每条记录绑定路径、字节数、SHA-256、segment ID、媒体规格、来源和执行记录。渲染完成后复核：

- manifest 中五类 component 的实际数量、mode 和 plan 一致。
- `code_generated` 的预览来源记录必须把已批准配方与实际调用证据逐项对齐：依赖 Skill、入口、版本、brief、渲染器、调用编号及成功状态；保存调用证据摘要。仅有计划中的 `invocation_record` 或最终 MP4 不算已调用验收通过。
- 所有文件存在，路径在 Job 允许目录内，字节数与 SHA-256 匹配；正式片段和成片视频可完整解码且为 1080×1920/24fps。仅无透明通道的 AI 动态 B-roll 源视频可按已冻结的素材合同为 720×1280/24fps，并须在合成后检查清晰度。
- 官方视频和外部素材视频抽取进入、稳定、退出三帧，确认媒体运动与 ShotRecipe 一致。
- 每个 B-roll 检查头像、`safe_zone`、文字溢出、元素重叠和最后 8–12 帧连续性。

报审摘要分别列出配方闭包、依赖 Skill 调用、官方资料、外部素材许可、当前 generation、manifest 资产计数和三态 QA；不只写“生成成功”。
