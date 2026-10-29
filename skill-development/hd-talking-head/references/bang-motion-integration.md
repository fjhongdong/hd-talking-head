# Bang Motion 原生来源与接入边界

来源 `https://github.com/bangtutorial/bang-motion`，固定提交 `c1aa65e921c970d858705fcb4a53a8294d1a4131`，MIT；源码在包根 `skill-development/vendor/bang-motion`，逐文件 SHA-256 见 `bang-motion-native-source.json`。该目录是完整原样源码，不在其中写 Job、安装依赖或修改文件。目录与工作流候选见 `bang-motion-template-catalog.json`；标签统一维护于 `motion-capability-index.json`；逐项原生入口路径位于目录的 `native_paths`，不维护第二份标签。

上游原生分为 10 个风格方向（`SKILL.md` 的 Arah gaya）、6 个 explainer 风格及各自 starter（`references/explainer.md`，第六项另见 `references/kartun-panggung.md`）、19 个 opener 概念（`references/opener-konsep.md` 的 Menu konsep）。它们是独立的风格或完整创作工作流，可在本期组合；不得将组合相乘登记，开头、过渡、渲染对象材质和工具也不得虚增为模板。示例 starter 是骨架，不是最终作品；选中后把本期真实语义、文稿、素材、目标尺寸和时长交给完整 Skill 创作。风格方向与 opener 概念均使用 `assets/starter-opener.html`，六种 explainer 各自使用对应 starter；完整画面由上游自主设计，不能将示例替代成品。

阅读上游 `SKILL.md`、`references/anti-ppt.md`，按所选模式读取 `references/explainer.md`、`references/opener-konsep.md`、`references/kartun-panggung.md`、`references/techniques.md` 与 `references/architecture.md`。实际角色 AE 工作流还依赖 `references/ae-bridge-higgsfield.md` 描述的 After Effects 和 Higgsfield bridge；不得假设可用或引入外部服务授权。`references/roadmap.md` 是开发计划，不构成已实现能力。上游示例要求图片及服务选择；本 Job 的素材和服务授权为准，不自动调用外部生成。

## 入口、准备与限制

- 静态 HTML 可通过现代浏览器打开；starter 通过 CDN 加载 GSAP、字体等，可能需要联网。复制所选 starter 到独立 Job 并按原生流程创作；源代码保留原样。预览参数 `?debug=1` 开启调试面板，`?clean=1` 禁止自动播放供导出。
- 上游提供 `scripts/serve.py` 作为本地服务、`scripts/snap.mjs` 拍摄指定时间点、`scripts/export-frames.mjs` 渲染 PNG 序列。Node、Puppeteer 和浏览器仅在使用自动截图/导出时需要，FFmpeg 仅在编码时需要。Puppeteer 是脚本的 ESM 依赖，必须由脚本实际位置可解析；在 Job 的隔离运行目录准备依赖并放置原样脚本副本，或通过现有已验证的包运行时提供依赖，不要只设置 `NODE_PATH` 假定 ESM 可解析。准备过程不得修改 vendor 源码、全局安装或自动发起收费请求。
- 如 `URL="file:///绝对路径/index.html?clean=1" node <原样snap.mjs> <输出目录> 1 3 5`；页面需公开 `window.OPENER.ready`、`W/H`、`seek`，视频素材则还需 `seekFrame` / `clipsReady`。`snap.mjs` 按 `OPENER.W/H` 截指定静帧，不能证明输出视频已接通。
- 上游导出范例为 `URL=http://127.0.0.1:5178/index.html?clean=1 FPS=24 OUT=<帧目录> node <原样export-frames.mjs>`，再用 `ffmpeg -framerate 24 -i <帧目录>/f%05d.png -c:v libx264 -pix_fmt yuv420p <输出.mp4>`。源脚本默认 60 fps，环境变量 `FPS` 可调整；截图视口和裁切硬编码为 1920×1080，`SCALE` 只是设备缩放，不接受 W/H。虽然上游有 1080×1920 的创作说明及动态尺寸静帧工具，原生导出器不能直接输出 1080×1920。约定在 Job HTML 最外层把原生 1080×1920 画布整体静态顺时针旋转 90°，放进 1920×1080 画板；通过原生脚本逐帧导出后，再用 FFmpeg `transpose=2` 将整幅逆时针转回 1080×1920。此方式不缩放、不裁切、不改变时钟，也不修改第三方源码；仍需实际样片验证输出尺寸、完整画面和动作，不能仅凭约定视为通过。
- 上游列有透明 lower third 的创作用途，但脚本截图未启用透明背景，所示 H.264/yuv420p 命令也不保留 alpha。当前没有可证实的透明视频输出路径，不能计入透明 A-roll 贴片候选。父级负责 24 fps 正式时钟、字幕、头像、安全区和实际画面复核。

建议无付费本地样例：在独立 Job 复制 `assets/starter-explainer.html`，以本地 SVG 素材创作连续动作，保持页面暴露 `OPENER`，先用原生 `snap.mjs` 检查多个时间点；以整板转向方案按 1080×1920 / 24fps 导出并检查成片，确认整个画面与原生时序一致。普通制作仍须核对本期实际动作、方向、中文及最终画面；开发样片不代替本期内容验收。

## 父级正式调用

运行环境只在所选渠道需要时，通过唯一依赖清单调用 `scripts/motion_native_runtime.py --project-root <包根> --dependency-id <渠道>` 准备；精确依赖锁随包提供，不在 vendor 或全局安装。缺失的 Playwright 浏览器仅由准备步骤调用官方工具安装到项目运行时，普通检查不下载。Bang 使用已准备的本地 Chrome。来源缺失或改变时停止，不在线换版本。

每项在本 Job 的 `native-inputs` 写计划 brief。`scripts/motion_native_skill_adapter.py` 校验以下字段：`schema_version=1`、`dependency_id`、`job_id`、`template_id`（渠道内原生标识）、`source_binding={aroll_sha256,segment_id,start,end}`、`composition={width:1080,height:1920,fps:24,frames}`、`alpha`、`canvas_transport`、`template_request`、`semantic_goal`、`transcript`、局部 `word_anchors`、`speech`、`materials`、`authorization`、`project_directory` 和 `result_record_path`。文件描述为 `{job_path,sha256,byte_count}`；工程写到 `native-projects`，结果记录写到 `native-inputs`。渲染媒体统一写入工程的 `out/`，实际输入素材置于该目录之外并逐一冻结，包括图片、字体、音频与视频。Barty 使用 `canvas_transport=identity`，Bang 使用 `quarter_turn_cw`。只有 Barty 的 `motion-broll` 可以声明 `alpha=true`。

整表确认前只检查真实输入和匹配；确认后 `run_stage` 返回 `execute_native_skill`，附完整原生入口、所选模板、材料、局部原话/词锚、输出规格及已授权服务。原生 Skill 负责完整创作、选读其参考、必要资产请求、工程代码与原生 QA。新增收费步骤须沿父级已有授权流程，不因接入默认批准。不同候选的风格组合只是当前模板的原生公开选项，不增加模板身份；不开新的用户审批门。

原生制作完成后，使用薄桥的 `capture_render(job_dir, brief_path, argv)` 实际执行原生命令并记录工程和视频；随后正常速度检查真实画面，再用 `publish_completed(..., qa_note=...)` 回传。Barty explainer 的内嵌 `render.mjs` 和 Bang 的 `export-frames.mjs` 均逐字复制到 Job，桥执行前和验收时与固定原文比较。父级不改写渲染时钟、动作或第三方源码。Barty explainer 的原始视频保留；如原生编码标为全范围像素，交付副本仅整理为正式链要求的有限范围 yuv420p，不改画幅、帧数或播放速度。

宿主将实际 HTML 源内容与 `completed` 结果记录加入现有 `semantic_assessments.content_refs`，按真实画面填写现有文字可读性及视觉检查，再回传 realization。既有批准映射冻结审核时的结果字节；正式适配器只消费该结果与对应视频，不再次创作。结果、源码、运行时、语义、alpha 或时钟改变时停止，不替换、不重试、不用路径当前内容冒充已审版本。透明贴片还沿 `overlay_selection` 与 `overlay_alignment` 检查实际模板、词锚和真人叠加用途；规划检查不要求尚未制作的结果，最终检查必须有真实原生产物。

接入验证只使用单独开发样片。现有视频、旧 Job 与已批准素材保持原样。
