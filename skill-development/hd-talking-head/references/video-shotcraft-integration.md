# Video Shotcraft 原生接入

渠道 `video-shotcraft` 完整保存上游仓库，固定提交 `1266a3ec4831289c4d893d42dd5102723658039a`。源码、原生目录软链、124 张配方卡、示范实现、完整 Ink Press 模板、工作台和资源均保持原样。原生 150 段样式示范属于卡内变体，不另算模板；当前索引为 124 卡 + 1 完整模板。

完整入口 `skill-development/vendor/video-shotcraft/SKILL.md`。选卡后读取完整原生卡、Gallery 索引和卡内指定的准确 demo TSX；原生配方的动作、用途和已调参数保留。本期文稿、真实素材和品牌输入进入原生单镜头创作流程，不用父级预写编舞，也不将未改示范当本期结果。Ink Press 则读取完整 TEMPLATE.md，按原生多镜头流程执行，不能假称任意短镜头模板。

目录用途原样保留：运镜、转场、节奏、纯视觉组件只以 component 进入能力库，不独立参加有语义的 B-roll 匹配，也不变成透明贴片。其余卡仍受卡内固定动作和素材条件约束，不因完整 Skill 能写代码就获得无限 full_scene 权限。实际资源不足时按当前模板停止，不自动替换。

复用 `scripts/motion_native_skill_adapter.py` 的 schema 2 brief、`native_task`、`capture_render`、`publish_completed` 和正式审核冻结/消费。原生 `@remotion/cli` 固定 4.0.484，运行环境放项目 runtime，不修改 vendor 依赖或全局环境。按需准备：

```bash
python3.12 <skill>/scripts/motion_native_runtime.py --project-root <project> --dependency-id video-shotcraft
```

本期工程在 Job `native-projects/<id>/`；`src/index.ts` 注册 `NativeScene`，使用当前任务 1080×1920、24fps、精确批准帧数，工程 node_modules 链接已准备 runtime。`native_options` 只能选当前卡已有 Gallery style-key，不改变模板计数。原生 argv：

```text
[node, <runtime.node_modules>/@remotion/cli/remotion-cli.js, render, src/index.ts, NativeScene, out/native.mp4, --codec=h264, --pixel-format=yuv420p, --color-space=bt709, --image-format=png, --muted, --concurrency=1, --browser-executable=<runtime.browser>]
```

使用原生公开 color-space=bt709 和 PNG 截帧，直接输出 limited-range yuv420p；不另造渲染器或放宽像素格式门禁。`capture_render` 在后续像素/时钟检查前先保存真实原生调用，失败不丢stdout/stderr。输出为无声 H264，原生不支持 alpha；父级保留原声、普通字幕和合成。按原生说明完成关键帧、完整成片和独立终检，再调用已有发布入口冻结实际结果。工作台、发布账号及剪映导出仍按原生用途保留，不因接入后台自动打开或发布。

完整源码的发布正本为包根 source-repositories/index.json 对应的 video-shotcraft.source.part-* 归档，展开 vendor 树不重复进入 release-manifest。run.py prepare 先校验包内 index/归档，再由 prepare_sources 从缺失目录恢复完整源码，逐文件及原始内部软链复核；已有目录不会被覆盖。普通 Job 不联网抓源码、不全局安装，原生 adapter 仍在每次调用时验证完整固定树。
