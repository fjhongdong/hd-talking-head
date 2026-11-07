# Garden Motion Showreel 与 useAnimations

两套完整官方源码由包内来源归档恢复到 `vendor/garden-skills/` 和 `vendor/react-useanimations/`，生产只在当前 Job 或项目运行时写入。资格样片保存在项目包外，不作为生产模板或默认素材。

## Garden Motion Showreel

- [官方仓库](https://github.com/ConardLi/garden-skills/tree/2b9a89340b70f632d31c0f1c69fce94a7912423e) 固定当前已核对提交。渠道为 `garden-motion-showreel`，模板为 `garden-motion-showreel/<style>`。43 个风格来自原生 `references/styles/INDEX.md` 及对应文件。
- 用于不透明整屏 B-roll。读原版 `skills/motion-showreel/SKILL.md` 和所选风格，在独立 Job 工程使用原生工作流创作。上游决定构图、材质、镜头和动作。涉及画内文案时，以最终竖屏画布中线及人物窗、字幕安全区复核，不能用三维场景原点代替可见文字位置。
- 通过 `scripts/garden_native_adapter.py` 交接原生任务、`capture_render`、`publish_completed`。交接使用可直接读取的原生说明路径，核对已确认的语义行、原话、语义、必须发生的变化与画面任务。用上游 `render.mjs`、`inspect.mjs` 导出并检查 1080×1920、24fps、无声视频。新渲染沿用上游 Playwright 解析，复用已完成片段时核对记录和实际文件即可。
- 工程里实际渲染的素材放在 `assets/` 或对应源码目录，保留同项已授权来源或原生创作来源。`qa/`、`out/` 用于预览和导出。渲染前后核对 Job 工程文件和本地依赖，工程素材使用实文件。需要引用内容时，可以引用实际绘制画面的 HTML、JS 或其他已绑定源码。软质 3D 样片是原生风格创作示例，其余风格按本句要求创作。

## useAnimations

- [官方仓库](https://github.com/useAnimations/react-useanimations/tree/f7af6f53f6f1a97486ad95756b281a34e9f7c670) 固定 3.1.1 的当前已核对提交。渠道为 `useanimations`，模板为 `useanimations/<官方 id>`。300 个图标从官方 `icons/catalog.json` 与原生 Lottie JSON 一一对应。
- 用于真人透明贴片。按本句实际动作匹配图标，在安全区编排。模板仅承诺官方图标动作；母片可配可读的短标签和状态说明，不把排版或文案当成新模板。词锚按实际口播，时窗须容纳所选原生动作。
- `scripts/useanimations_native_adapter.py` 通过原样官方图标数据和 [官方建议的 Lottie 播放器](https://useanimations.com/lottie-icons#web-lottie-web) 定帧输出无声 1080×1920、24fps ProRes 4444 透明层，由母片合成。保留原生循环和单次播放。用切换或悬停图标呈现两个状态时，标签对应原生起止含义，第二个口播锚点触发原生过渡并预留完整动作时长。渲染检查真实图标是否可见、是否有变化，独立于卡片底色和文案。

同次能力库构建共用一份原生候选目录。中文动作标签补充在已核实的原生图标上，例如纸飞机的「发送消息」和来电图标的「电话响了」。标签用于召回与排序，继续在全部合格候选中先最大化渠道、再最大化模板，最后校验时间。
