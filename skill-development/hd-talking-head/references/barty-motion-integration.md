# Barty motion-graphics 原生来源与接入约定

源码固定为 `Barty-Bart/motion-graphics` 的 `3d83d987d658601d8a1269eb691622bdcd427335`，位于包根 `skill-development/vendor/barty-motion-graphics/`。全部跟踪文件及 SHA-256 见 `barty-motion-native-source.json`。MIT 代码许可、Geist 字体及音效许可分别见源码中的 LICENSE 和对应说明；使用外部音乐或素材时核对其许可。

## 视觉工作流与边界

- `motion-broll`：依据视频、文字及时间规划，逐条创作一体连续变形的 HTML 片段；可以是全画幅或透明面板。示例六个片段是学习参考，不单独计模板。`engine`、`templates/compare.html`、`templates/viewer.html` 是构建、渲染和审阅工具，不是独立创作模板。
- `explainer-default`：45–90 秒产品界面演示，默认 60 秒；`explainer-engaging`：10–30 秒单镜头流程故事，默认 12 秒循环；`explainer-high-energy`：12–20 秒节奏化宣传，默认 15 秒。三者是不同的完整原生创作流程，而非填字预制组件。都需先按对应 SKILL 创作时间驱动 HTML，并将其 SKILL 末尾完整的 `render.mjs` 代码原样保存到 Job 工作目录。具体调用位置保存于 `barty-motion-template-catalog.json`，标签由统一能力索引维护。
- `object-separation` 是 SAM 2.1 人物或对象分离流程，`sound-effects` 是音效与混音流程；均不是新视觉动效模板。前者需本地模型下载、虚拟环境及计算资源，后者需 Python 依赖和音源许可；不得自动启动或下载。
- 上游互动和审阅步骤服从本项目已确认的整表审批及交付合同；不得自行增加审批或绕过既有授权。不要将辅助脚本、示例、形态状态或主题变成新的模板身份。

## motion-broll 原生调用

`$SKILL` 指上述来源中的 `skills/motion-broll`；工作路径必须是本 Job 目录。先阅读 `SKILL.md`、`reference/engine-api.md` 及示例，根据已批准的逐句语义与设计写片段。`M.scene` 的 `W`、`H`、`T` 设置画布与秒数，`bg:null` 设置透明背景；原生建议短全幅约 3–10 秒，面板可较长，不能把建议下限当成渲染器硬编码限制。素材帧率和画幅需要匹配；口播 SRT/VTT 词时间只是估计。

```bash
python3 "$SKILL/engine/build.py" "$JOB/dist" "$JOB/clips/clip.html"
NODE_PATH="$RUNTIME/node_modules" node "$SKILL/engine/beats.js" "$JOB/dist/clip.html" "$JOB/check.png" 0.4 1.2 2.1
NODE_PATH="$RUNTIME/node_modules" node "$SKILL/engine/render.js" "$JOB/dist/clip.html" "$JOB/clip.mp4" 24
```

渲染器从场景读尺寸、时长和透明状态，fps 接受数字或分数，默认 30000/1001，固定四个子帧。非透明为 H.264/yuv420p，透明为 ProRes 4444/yuva444p10le，应使用 `.mov`。检查关键静帧、过渡帧、最终真实画面及文字；无需生成旧视频来验证。上游另提供 `inspect_video.py`、`words.py`、`composite.py` 和 `make_pages.py`，需要时按其原生合同在 Job 内调用。

## Explainer 原生调用

对应 SKILL 中的渲染代码读取自创 HTML 的 `window.VIDEO={w,h,duration}` 和 `window.seek(t)`，使用 `node render.mjs page.html out.mp4 [fps] [subframes] [workers]`，也支持 `node render.mjs page.html sheet.png --stills 0.5,1.2,3`。上游公开横版 1920×1080 和竖版 1080×1920；示例草稿 30fps、最终 60fps。原生编码是 H.264/yuv420p，不支持透明输出。创作时严格依据真实产品资料，不编造数据；源文件、字体和合成音轨均在 Job 内处理。具体细节以对应完整 SKILL 为准。

## 依赖与最小样片建议

Node 18+、Python 3、ffmpeg/ffprobe、Playwright 和 Chromium；motion-broll 视频检查还需 numpy，透明面板需要 ffmpeg `prores_ks`。将 Node 依赖安装到包内指定运行时，将 Python 依赖放隔离环境；原生 `setup.sh` 包含 `pip install --user` / `--break-system-packages`，不应直接运行以免改动用户环境。Playwright 浏览器也应使用受控路径。Explainer 的 Playwright、Chromium、ffmpeg 同理，不需调用收费服务。

推荐本地无付费样片：在独立临时 Job 使用 `examples/opus-aoe2/01-opus-drop.html` 经原生 build、beats 和 render 执行一次，检查实际画面、时长、画幅和编码。示例内容仅用于试运行，不得作为当前任务真实事实或修改已有视频。普通制作仍需检查本期实际语义、完整动作、中文和最终画面，不复用开发样片的内容结论。

## 父级正式调用

运行环境只在所选渠道需要时，通过唯一依赖清单调用 `scripts/motion_native_runtime.py --project-root <包根> --dependency-id <渠道>` 准备；精确依赖锁随包提供，不在 vendor 或全局安装。缺失的 Playwright 浏览器仅由准备步骤调用官方工具安装到项目运行时，普通检查不下载。Bang 使用已准备的本地 Chrome。来源缺失或改变时停止，不在线换版本。

每项在本 Job 的 `native-inputs` 写计划 brief。`scripts/motion_native_skill_adapter.py` 校验以下字段：`schema_version=1`、`dependency_id`、`job_id`、`template_id`（渠道内原生标识）、`source_binding={aroll_sha256,segment_id,start,end}`、`composition={width:1080,height:1920,fps:24,frames}`、`alpha`、`canvas_transport`、`template_request`、`semantic_goal`、`transcript`、局部 `word_anchors`、`speech`、`materials`、`authorization`、`project_directory` 和 `result_record_path`。文件描述为 `{job_path,sha256,byte_count}`；工程写到 `native-projects`，结果记录写到 `native-inputs`。渲染媒体统一写入工程的 `out/`，实际输入素材置于该目录之外并逐一冻结，包括图片、字体、音频与视频。Barty 使用 `canvas_transport=identity`，Bang 使用 `quarter_turn_cw`。只有 Barty 的 `motion-broll` 可以声明 `alpha=true`。

整表确认前只检查真实输入和匹配；确认后 `run_stage` 返回 `execute_native_skill`，附完整原生入口、所选模板、材料、局部原话/词锚、输出规格及已授权服务。原生 Skill 负责完整创作、选读其参考、必要资产请求、工程代码与原生 QA。新增收费步骤须沿父级已有授权流程，不因接入默认批准。不同候选的风格组合只是当前模板的原生公开选项，不增加模板身份；不开新的用户审批门。

原生制作完成后，使用薄桥的 `capture_render(job_dir, brief_path, argv)` 实际执行原生命令并记录工程和视频；随后正常速度检查真实画面，再用 `publish_completed(..., qa_note=...)` 回传。Barty explainer 的内嵌 `render.mjs` 和 Bang 的 `export-frames.mjs` 均逐字复制到 Job，桥执行前和验收时与固定原文比较。父级不改写渲染时钟、动作或第三方源码。Barty explainer 的原始视频保留；如原生编码标为全范围像素，交付副本仅整理为正式链要求的有限范围 yuv420p，不改画幅、帧数或播放速度。

宿主将实际 HTML 源内容与 `completed` 结果记录加入现有 `semantic_assessments.content_refs`，按真实画面填写现有文字可读性及视觉检查，再回传 realization。既有批准映射冻结审核时的结果字节；正式适配器只消费该结果与对应视频，不再次创作。结果、源码、运行时、语义、alpha 或时钟改变时停止，不替换、不重试、不用路径当前内容冒充已审版本。透明贴片还沿 `overlay_selection` 与 `overlay_alignment` 检查实际模板、词锚和真人叠加用途；规划检查不要求尚未制作的结果，最终检查必须有真实原生产物。

接入验证只使用单独开发样片。现有视频、旧 Job 与已批准素材保持原样。
