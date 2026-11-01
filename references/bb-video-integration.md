# BB Video 完整原生接入

渠道 `bb-video` 固定上游 `BubbleBrainBB/BB-Video` 的提交 `a21025a19d382b066ff354d877919be9d6863f97`。完整仓库原样保存在 `vendor/bb-video`，包含 Skill、30 个原生风格、runtime、starter、资源与官方示例；不修改、抽取或重写第三方实现。来源记录为 `bb-video-native-source.json`，模板入口为 `bb-video-template-catalog.json`，语义标签继续由统一 `motion-capability-index.json` 管理。

## 身份和选型

统一为一个渠道、30 个原生风格模板，模板身份 `bb-video/<style>`。explainer／promo、quick／手写工程、组件动词、主题和本期项目都不增加模板数量。模板之间不另设固定优先级；选库时的美观评估不改变[统一的一次匹配与联合分配](native-motion-call-contract.md#身份与一次匹配)。贴片和 B-roll 仍各自从语义规划，分配后再检查时长。

本渠道原生视频不含 alpha，仅进入不透明 B-roll 候选，不进入真人透明贴片。各风格按原生用途及素材条件匹配；例如 `parable` 的 15–45 秒完整叙事要求不能靠截出几秒规避。其他风格的示例片长不作为统一最低时长。

## 完整原生创作

读取 `vendor/bb-video/skills/bb-video/SKILL.md`、所选 `styles/<style>/STYLE.md`，再按原生分工读取 explainer／promo 的 GUIDE 及其所需参考。先完成原生事实、文稿、分镜与自查流程，再交真实工程和结果；只运行渲染器不等于调用完整 Skill。

父级沿[共同调用合同](native-motion-call-contract.md)传入批准语义、材料、段内原声与精确词锚、1080×1920／24fps／整数帧数，以及本镜真实头像和字幕安全区。原生自主设计构图、角色、材质和动作；父级不预写关键帧或统一套卡片布局。正文不新建配音，不重复调用 TTS。

本句已有的输入主体可以先建立，第一条有声字幕出现时应已有可辨主题。词锚约束关键动作、结果和状态变化，不把每个名词的发声时刻当成现有主体最早可见的时刻；例如已有表格可以从开场呈现，圈选和提取仍跟随对应原话。不能先留空场再等名词出现，也不能提前后文结果。

使用原生 `explainer/scripts/new.mjs` 或 `promo/scripts/new.mjs` 在 Job 内创建本期工程。复制来的原生 `lib/` 保持原样，主题创作写在本期 `index.html` 及自有场景文件；vendor 内不写项目、输出或安装目录。公开布局参数只用于本次任务，不能改第三方来满足字形、时序或布局验收。

## 原生字幕、片尾与输出

父级负责唯一普通字幕、原口播、头像和编号。关闭原生音轨不会关闭画面里的字幕，须使用原生公开参数选择真实无字幕路线：

- 原生 `PROMO.compose` 可以指定本期 `duration`、`tail:0`、`captions:false`、`chapters:false`。
- 有旁白时间线时，白板／孔版／水墨的 kit 会按 `F.voiced` 开启内部画板字幕；外层 `captions:false` 不会覆盖它。需要时使用已有 `WB/RISO/INK.board({T,captions:false,chapters:false})` 等原生公开接法。
- `PROMO.film` 的 quick explain 会附加默认片尾，且不透传所有上述开关。不要把它作为所有短 B-roll 的统一入口，不压缩完整叙事来迁就短时窗。

关闭普通字幕不删除承载本句语义的图内标签。实际文字仍须在原生制作后绑定真实区域和阅读窗，并通过原有验收。

原生渲染 argv 使用对应 explainer 或 promo 的原始入口：

```text
[node, <原始render.mjs>, <本项工程绝对路径>,
 --aspect, 9:16, --fps, 24, --from, 0, --to, <frames/24字符串>,
 --no-audio, --no-bgm, --workers, 1, --out, native.mp4]
```

`--out` 只传文件名，真实媒体为 `<本项工程>/out/native.mp4`；不要再加一层 `out/`。显式 `from/to` 既控制真实整数帧窗，也避免整片导出附带输出改写作者工程。最终调用通过现有 `capture_render` 捕获真实来源、工具、输入、命令和输出，再经 `publish_completed` 和正式阶段审核冻结／消费。不使用 `--force`、`--draft` 或字体 fallback 参数掩盖失败。原生静帧使用其公开 `--stills`，实际检查不能冒充连续观感或听感。

## 环境、来源分发与验收

BB 使用 Node 内建 WebSocket 和原生 Chrome CDP，无 npm 运行依赖。沿现有 `motion_native_runtime.py --project-root <project> --dependency-id bb-video` 检查 Node ≥22.4、真实 Chrome、FFmpeg 和 FFprobe，传递实际 `CHROME_PATH`；不伪造 package-lock，不安装 Puppeteer，不改变全局环境。字体及部分可选三维库仍可能联网，不能据此宣称离线；原生字体和资源检查照常执行。

完整源码的分发正本在 `archives/sources/index.json` 对应的 `bb-video.source.part-*`。准备入口可从缺失目录恢复固定完整树；已有目录不覆盖。展开的 vendor 不重复打包，源记录及逐文件核验沿现有机制执行。

接入样片放完整包外。用真实口播及对应词钟，沿现有阶段派发、原生制作、结果审核冻结、正式组件消费和父级合成完成代表性验收；常规场景及画板字幕路线分别覆盖。样片是明确标记的开发夹具，不冒充用户正式视频批准，不放宽生产候选完整性或多样化规则。一条样片只证明该次调用和结果，不宣称30种风格的所有主题均已视觉通过。现有成片、旧任务和历史模板资格保持原样。
