# TalkCraft 完整原生调用

`video-talkcraft` 调用固定提交 `ccb8a571f4bd620b5588bef4b264b5120f5042fc` 的完整第三方 Skill。项目内入口为 `edit/hd/integrations/talkcraft/upstream/SKILL.md`。`talkcraft-native-source.json` 保存该提交原始归档及全部 917 个原始文件的身份；自有桥按此清单核对，第三方文件保持原样。补齐时逐字比较重叠文件，只补原始缺文件。

## 函数边界

桥为 `scripts/talkcraft_skill_adapter.py`，dependency 为 `video-talkcraft`。父级传用户目标、当前真实口播及字时码、素材、原生配方、输出时钟和资源授权。输入契约不接受父级设计稿、镜头动作、构图或代码。原生执行者读取完整 Skill 和所选配方，自行产出 SHOTBOOK、构图、节拍、工程和 QA；父级不预先写这些产物。

原生 Skill 规定的“复制模板到本片工程并调整 CONFIG”由原生执行者在本 Job 独立目录内完成，第三方 Skill 包本身不改。不得用 `edit/hd/integrations/talkcraft/runtime/src/cards` 或其 `production-adapters` 的自有派生动画替代原生配方；可复用兼容的现有 Remotion 依赖。原有四个已验证组件保留原身份，本入口不重做它们。

## 入口与结果

准备入口是 `python scripts/prepare_talkcraft_native.py --project-root <完整包根>`；增加 `--check` 只检查，不安装。它把第三方原始 `runtime/package.json` 和 `package-lock.json` 原封放入包内 `skill-development/runtime/talkcraft-native-ccb8a571/`，仅执行锁文件安装，不调用 upgrade、不改原生源码、不改派生生产 runtime。新创作默认使用原生锁定 Remotion 4.0.519。检查会核对全部直接依赖版本、加载必要 Remotion API，并核对本机 Node、FFmpeg、FFprobe 和现有 Chrome；没有浏览器时明确失败，不隐式下载。

桥的 `--probe --project-root <完整包根>` 使用同一真实依赖检查。原生任务返回已准备的 `runtime.node_modules` 与 `runtime.browser`，独立 Job 工程链接这份依赖并显式传浏览器路径。无需已有样片工程、全局安装的 Skill 或派生卡动画。

`speech` 唯一表示已经裁好的本段音频。桥检查它只有音轨，时长与本段时钟一致。`speech_window` 始终为局部 `0..frames/fps`，`word_anchors` 使用同一局部时钟；全片来源位置单独保存在 `source_binding`。不得对子片再次按全片秒数截取。`validate_selected_inputs(job, director, treatment)` 可在确认前检查真实声音、素材及当前已批准 A-roll 的来源绑定，不生成媒体。

- `validate_brief(payload)` 校验本期任务、素材身份、语义请求和准确时钟。
- `load_card_catalog(project)` 读取原生 frontmatter 和 TSX，返回 108 项身份及真实类别；不读取旧派生语义索引。
- `native_task(job, recipe, component, brief_path)` 返回 `execute_native_skill` 待执行任务。它不是成功回执。
- `capture_render(job_dir, brief_path, argv)` 只记录并执行原始 `scripts/render_shots.mjs`，工作目录为 brief 的独立 `project_directory/remotion`。本接口只收无声视频输出，不替换原声。
- `publish_completed(..., qa_note=...)` 在实际画面检查及原始 `card_lint.py` 通过后发布完成记录。已有完成记录不覆盖。
- `inspect_result` 检查实际原生调用、源码、文件身份与真实媒体；`load_result(..., expected_record=...)` 只接收审核冻结的 path/sha256/bytes。
- `load_result` 还要求 `expected_renderer_version` 与组件冻结值一致。真实调用冻结实际 renderer/package.json，结果版本必须与它相符；显式传给消费 adapter 的版本表示该条已生成媒体的真实身份，不能用新准备环境的版本重标旧输出。
- 正式 `ReferenceProcessAdapter` 消费既有审核结果，不再次创作或重渲；输出仍由现有正式 executor 发布。

技术修订沿现有 `state.revise`，使用新 brief、新原生项目与新结果路径。旧源码、媒体与完成记录保留。当前授权和正式 mapping 未建立之前，待执行任务不能视为已获新的执行许可。

## 能力用途与计数

完整 Skill 是一个来源，108 张原生配方不是 108 个渠道。类别映射为 scene 51、overlay 22、annotation 14、transition 13、camera 8。角色决定匹配用途，不能把旧目录的 72 个 base 全当整屏 B-roll。

当前正式媒体协议为 1080×1920、24fps、无声 H.264/yuv420p MP4。原生 Remotion 可省略方像素 SAR 标签；存在显式 SAR 时须为 1:1。没有接入透明视频协议，不宣称这 57 个非 scene 配方已成为透明 A-roll 贴片或独立边界转场执行器。它们可通过完整原生 Skill 参与场景工程；具体用途以生产路由与输出契约为准。

## 本次代表样片

样片独立存放于项目外层 `skill-samples/20261028-native-integration/talkcraft/`，不在 Skill 包、旧 Job 或已验收成片中。它复用旧合同项目已批准的 14.25–20.00 秒原声及字时码，以原生 `source-converge` 表达“整份合同、年报、项目材料一次全部塞进去”。

样片由原生执行者生成独立 SHOTBOOK 与工程，调用固定版 `render_shots.mjs` 得到 138 帧无声 MP4。原始 `card_lint.py` 对 Job 内模板副本检查通过。正式消费 Smoke 使用明确的批准上下文夹具，真实执行 mapping 冻结、描述符比对、进程适配器、冻结文件传递和正式媒体发布；输出字节与原生媒体一致。它是接线验收，不是完整用户 Job 重制，也不代表 108 张卡逐张完成效果验收。

该既有样片实际复用了 Remotion 4.0.520 依赖，只调用原始配方及渲染流程。补齐准备链后如实保留其 4.0.520 产物身份，并使用 `run_stage` 默认的 `material_adapter.create_artifact_probe` 重新验证、冻结和消费，未重新渲染或改报 4.0.519。默认原生锁定 4.0.519 已完成安装与关键 API 可调用检查；未为此重复生成样片。

确认前的语义检查只审核本段已批准原声、素材、原生配方和语义目标。此时引用 brief 的 `/transcript`、`/card_id`、`/semantic_goal`，检查结果标为 `planning_inputs`，不表示动画已完成或可见内容已验收。用户确认后才产生完整原生创作 action。最终发布仍采用完成态语义门；必须引用实际完成记录的 `/status=completed`、冻结 SHOTBOOK 和本次工程全部 src 源码片段。完成记录、工程源码、媒体与 renderer 身份都由原生结果检查验证。

捕获正式原生调用必须使用原脚本公开 `--all`；不接受只渲缺失段、`--changed` 或 `--only`。分段目录必须处于本次原生工程内，防止改动源码后误用旧分段缓存。每次返修仍使用新的独立原生项目与结果位置。
