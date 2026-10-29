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

两渠道共用[完整原生调用合同](native-motion-call-contract.md)。该页是当前任务交接、原生选项、制作后文字验收、当前项返修、环境与正式消费的唯一共同说明；本页保留该渠道的原生用法和输出边界。
