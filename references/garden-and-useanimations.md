# Garden Motion Showreel 与 useAnimations

两套完整官方源码由包内来源归档恢复到 `vendor/garden-skills/` 和 `vendor/react-useanimations/`，生产只在当前 Job 或项目运行时写入。资格样片保存在项目包外，不作为生产模板或默认素材。

## Garden Motion Showreel

- [官方仓库](https://github.com/ConardLi/garden-skills/tree/2b9a89340b70f632d31c0f1c69fce94a7912423e) 固定当前已核对提交。渠道为 `garden-motion-showreel`，模板为 `garden-motion-showreel/<style>`。43 个风格来自原生 `references/styles/INDEX.md` 及对应文件。
- 用于不透明整屏 B-roll。读原版 `skills/motion-showreel/SKILL.md` 和所选风格，在独立 Job 工程使用原生工作流创作。上游决定构图、材质、镜头和动作。涉及画内文案时，以最终竖屏画布中线及人物窗、字幕安全区复核，不能用三维场景原点代替可见文字位置。
- 通过 `scripts/garden_native_adapter.py` 的原生任务交接、`capture_render` 和 `publish_completed`。用上游 `render.mjs`、`inspect.mjs` 导出并检查 1080×1920、24fps、无声视频，绑定当前已确认词窗与实际结果。软质 3D 样片是原生风格创作示例。其余风格按本句要求创作和验收。

## useAnimations

- [官方仓库](https://github.com/useAnimations/react-useanimations/tree/f7af6f53f6f1a97486ad95756b281a34e9f7c670) 固定 3.1.1 的当前已核对提交。渠道为 `useanimations`，模板为 `useanimations/<官方 id>`。300 个图标从官方 `icons/catalog.json` 与原生 Lottie JSON 一一对应。
- 用于真人透明贴片。按本句实际动作匹配图标，在安全区编排。模板仅承诺官方图标动作；母片可配可读的短标签和状态说明，不把排版或文案当成新模板。词锚按实际口播，时窗须容纳所选原生动作。
- `scripts/useanimations_native_adapter.py` 通过原样官方图标数据和 [官方建议的 Lottie 播放器](https://useanimations.com/lottie-icons#web-lottie-web) 定帧输出无声 1080×1920、24fps ProRes 4444 透明层，由母片合成。核对原生 ID、实际词钟、尺寸、可见区域与透明像素。
