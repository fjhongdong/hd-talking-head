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

渲染器从场景读尺寸、时长和透明状态，fps 接受数字或分数，默认 30000/1001，固定四个子帧。非透明为 H.264/yuv420p；透明以 `yuva444p10le` 编码参数生成 ProRes 4444，应使用 `.mov`。FFprobe 可将实际解码格式报告为 `yuva444p12le`；探针和两级消费检查如实接受这两种精确透明格式，不将 12 位伪报为 10 位，也不重编码原生素材。检查关键静帧、过渡帧、最终真实画面及文字；无需生成旧视频来验证。上游另提供 `inspect_video.py`、`words.py`、`composite.py` 和 `make_pages.py`，需要时按其原生合同在 Job 内调用。

## Explainer 原生调用

对应 SKILL 中的渲染代码读取自创 HTML 的 `window.VIDEO={w,h,duration}` 和 `window.seek(t)`，使用 `node render.mjs page.html out.mp4 [fps] [subframes] [workers]`，也支持 `node render.mjs page.html sheet.png --stills 0.5,1.2,3`。上游公开横版 1920×1080 和竖版 1080×1920；示例草稿 30fps、最终 60fps。原生编码是 H.264/yuv420p，不支持透明输出。创作时严格依据真实产品资料，不编造数据；源文件、字体和合成音轨均在 Job 内处理。具体细节以对应完整 SKILL 为准。

## 依赖与最小样片建议

本接入锁定的 Playwright 需要 Node ≥20，另需 Python 3、ffmpeg/ffprobe、Playwright 和 Chromium；motion-broll 视频检查还需 numpy，透明面板需要 ffmpeg `prores_ks`。将 Node 依赖安装到包内指定运行时，将 Python 依赖放隔离环境；原生 `setup.sh` 包含 `pip install --user` / `--break-system-packages`，不应直接运行以免改动用户环境。Playwright 浏览器也应使用受控路径。Explainer 的 Playwright、Chromium、ffmpeg 同理，不需调用收费服务。

推荐本地无付费样片：在独立临时 Job 使用 `examples/opus-aoe2/01-opus-drop.html` 经原生 build、beats 和 render 执行一次，检查实际画面、时长、画幅和编码。示例内容仅用于试运行，不得作为当前任务真实事实或修改已有视频。普通制作仍需检查本期实际语义、完整动作、中文和最终画面，不复用开发样片的内容结论。

## 父级正式调用

两渠道共用[完整原生调用合同](native-motion-call-contract.md)。该页是当前任务交接、原生选项、制作后文字验收、当前项返修、环境与正式消费的唯一共同说明；本页保留该渠道的原生用法和输出边界。
