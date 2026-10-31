# MG Styles 15 原生接入

渠道 `mg-styles-15` 完整保存上游仓库，固定提交 `49052d80bfaf9fa8412cc9710530e5e95a3b8d8c`。15 个风格是 15 个原生模板，不把原片或素材算模板。源码根在 `skill-development/vendor/mg-styles-15`；`mg-styles-15-native-source.json` 校验完整文件树，`mg-styles-15-template-catalog.json` 记录原生提示词、参考工程和渲染器。

上游没有 SKILL.md。完整入口是 README → 所选 prompts/*.md → 对应 demos/<style> → rubric.md；按原生 treatment、cue sheet、关键帧、动效、渲染和自评执行。父级只传已批准语义、原话、素材、授权及规格，不把原片的故事或父级编舞当作本期方案。替换 Creative seed 和输出尺寸/时钟，保留 Signature features。原生 Blender 风格仍完整执行 Blender 制作，不将其降为普通网页模板；缺少 Blender 时明确停止该模板。

沿 `scripts/motion_native_skill_adapter.py` 的 schema 2 brief、`native_task`、`capture_render`、`publish_completed` 和正式消费接口执行。正式阶段、依赖预检和视觉确认均使用同一 `dependency_id`。按需准备：

```bash
python3.12 <skill>/scripts/motion_native_runtime.py --project-root <project> --dependency-id mg-styles-15
```

本期工程放 Job `native-projects/<id>/`；原样复制 `harness/render.mjs`，将工程 node_modules 链接到独立 runtime。原生页面使用 `window.DEMO`、`window.renderAt(t)`、`window.__ready`。交给 `capture_render` 的原生 argv：

```text
[node, harness/render.mjs, scene, --out, out/native.mp4, --w, 1080, --h, 1920, --fps, 24, --duration, <frames/24字符串>, --workers, 1, --noaudio]
```

字体须实际验证目标字面加载成功；document.fonts.ready 或系统已安装不证明指定 face 可用。按原生要求提供字体文件或准确 face 名，加载失败先停当前工程诊断，不接受 fallback，也不把持续等待 __ready 当作正常渲染。

原生 H264 无 alpha，本渠道用于整屏 B-roll，不能透明贴片。父级保留口播、普通字幕和最终合成；无声要求明确覆盖上游配乐输出，不触发新的外部生成。实际输出须经现有文字、语义、画面观察及冻结后消费，启动检查通过不能代替本期出片。

完整源码的发布正本为包根 source-repositories/index.json 对应的 mg-styles-15.source.part-* 归档，展开 vendor 树不重复进入 release-manifest。run.py prepare 先校验包内 index/归档，再由 prepare_sources 从缺失目录恢复完整源码，逐文件及原始内部软链复核；已有目录不会被覆盖。普通 Job 不联网抓源码、不全局安装，原生 adapter 仍在每次调用时验证完整固定树。

整表确认前，现有准备入口只对已选 3d-render 探测真实 Blender 5.1/Cycles；缺失或版本不符即停止该项准备，不安装到全局，也不换成HTML假3D。其他14风格和普通启动不检查Blender；原生已完成且已审结果经原有验证消费时不要求Blender。当前接入不等于本机15风格均已渲染，实际样片仅代表所选风格。
