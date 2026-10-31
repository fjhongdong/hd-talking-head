# Video Shotcraft 原生接入

渠道 `video-shotcraft` 完整保存上游仓库，固定提交 `1266a3ec4831289c4d893d42dd5102723658039a`。源码、原生目录软链、124 张配方卡、示范实现、完整 Ink Press 模板、工作台和资源均保持原样。原生 150 段样式示范属于卡内变体，不另算模板；当前索引为 124 卡 + 1 完整模板。

完整入口 `skill-development/vendor/video-shotcraft/SKILL.md`。选卡后读取完整原生卡、Gallery 索引和卡内指定的准确 demo TSX；原生配方的动作、用途和已调参数保留。本期文稿、真实素材和品牌输入进入原生单镜头创作流程，不用父级预写编舞，也不将未改示范当本期结果。Ink Press 则读取完整 TEMPLATE.md，按原生多镜头流程执行，不能假称任意短镜头模板。

角色按原卡完整用途和准确示范判定，不由目录名决定。能独立表达语义的场景按固定动作和素材条件进入 B-roll 匹配；依附场景的运镜、转场、节奏和包装保留 component，也不变成透明贴片。完整 Skill 能写代码不授予每张固定卡无限 full_scene 权限。实际资源不足时按当前模板停止，不自动替换。

复用 `scripts/motion_native_skill_adapter.py` 的 schema 2 brief、`native_task`、`capture_render`、`publish_completed` 和正式审核冻结/消费。原生 `@remotion/cli` 固定 4.0.484，运行环境放项目 runtime，不修改 vendor 依赖或全局环境。按需准备：

```bash
python3.12 <skill>/scripts/motion_native_runtime.py --project-root <project> --dependency-id video-shotcraft
```

本期工程在 Job `native-projects/<id>/`；`src/index.ts` 注册 `NativeScene`，使用当前任务 1080×1920、24fps、精确批准帧数，工程 node_modules 链接已准备 runtime。`native_options` 选择当前主卡已有 Gallery style-key，不改变模板计数。原生任务同时交出完整目录，原生可自主选择内部组件，无需父级再匹配或预选。原生 argv：

```text
[node, <runtime.node_modules>/@remotion/cli/remotion-cli.js, render, src/index.ts, NativeScene, out/native.mp4, --codec=h264, --pixel-format=yuv420p, --color-space=bt709, --image-format=png, --muted, --concurrency=1, --browser-executable=<runtime.browser>, --bundle-cache=false]
```

使用原生公开 color-space=bt709 和 PNG 截帧，直接输出 limited-range yuv420p；不另造渲染器或放宽像素格式门禁。`capture_render` 在后续像素/时钟检查前先保存真实原生调用，失败不丢stdout/stderr。输出为无声 H264，原生不支持 alpha；父级保留原声、普通字幕和合成。按原生说明完成关键帧、完整成片和独立终检，再调用已有发布入口冻结实际结果。工作台、发布账号及剪映导出仍按原生用途保留，不因接入后台自动打开或发布。

新制作使用原生公开 `--bundle-cache=false`，避免默认 Webpack 缓存写入作者工程后触发源码变化。作者文件冻结仍完整执行，不把任意 `.cache` 或嵌套 `assets/out` 排除；失败记录保留实际前后差异。旧调用仅按原冻结命令读取，不补参数或重签结果。

新发布结果使用 schema 2。调用 `publish_completed(..., native_usage=[...])`，每项记录 `card_id`、`variant`、`purpose` 和 `implementation_refs`；引用为本次调用已冻结的实际工程文件描述 `{job_path,sha256,byte_count}`。主模板与已选变体须兑现，附属原卡按实际使用记录，组件不增加独立 B-roll 或渠道数量，组合不产生新模板。记录和源码引用不能代替实际画面检查。旧 schema 1 审核结果仅按原冻结链读取，不补写或重签。

完成态语义复核引用本次结果及其全部冻结 `scene_sources`：主场景引用实际内容与动作，注册文件引用真实 Composition／入口，共享样式与动作 helper 引用本片使用的定义。不只引主 TSX 而漏掉其余来源，也不以这些技术引用冒充实际语义和画面已通过。

`timing_requirements` 记录原卡明确要求的动作、hold 及原生帧率。示例总长不作通用最低时长；Ink Press 按原生允许增删的镜头结构及各镜头预算规划，不能压掉必要动作来塞入短窗口。最终校时不改变既有语义匹配结论，复用缓存重新分配。

完整源码的发布正本为包根 source-repositories/index.json 对应的 video-shotcraft.source.part-* 归档，展开 vendor 树不重复进入 release-manifest。run.py prepare 先校验包内 index/归档，再由 prepare_sources 从缺失目录恢复完整源码，逐文件及原始内部软链复核；已有目录不会被覆盖。普通 Job 不联网抓源码、不全局安装，原生 adapter 仍在每次调用时验证完整固定树。
