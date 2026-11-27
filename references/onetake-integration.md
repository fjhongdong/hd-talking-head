# OneTake 原生 B-roll 接入

正式来源为 `vendor/onetake`，固定官方提交 `4e024be4c6c696b260f39a35aee6bd56d303b679`。完整源码由 `archives/sources/index.json` 登记并核对；Python 和浏览器在包内 `runtime/onetake-python312`、`runtime/onetake-browsers` 准备。

只有一个正式身份：渠道 `onetake`，模板 `onetake-reviewed-scene`，候选 `onetake:onetake-reviewed-scene`。它代表完整原生创作流程，不把每个动作、配色或本期场景另算模板。

## 使用范围与原生创作

适合把产品操作、界面反馈、文字与容器的连续变化做成因果明确的整屏 B-roll。例如点击按钮后原容器展开为结果、同一对象变形成后续画面、镜头沿同一界面推进。需要产品证据时使用本期真实截图或素材；不能把自绘界面当作产品实际运行记录。

宿主收到统一入口的 `prepare_template_inputs` 后，完整读取 `vendor/onetake/SKILL.md` 及当前任务所需的原生参考。基本创作阅读包括 `references/composition.md`、`references/motion-library.md`、`references/rhythm.md`。有参考视频时按原生流程分析；保留用户已经确定的概念、真实内容和整表选择。没有现成概念时执行原生构思，导演设计由 OneTake 完成。已有本期确认不重复请求批准。

遵循原生的节奏、承接、可见因果与确定性时间函数。引用原 `lib/motion.js`，不另写一套运动曲线；原模板与 gallery 用于技术参考，不把 motion-web 的固定故事当作所有主题的默认画法。字体和素材保存在本期场景内。按 1080×1920、24fps、已确认帧数首次设计，避开父级圆窗及字幕安全区。动作、末态停留和阅读时间须适配本期词钟。

本期交付为无声、不透明整屏 B-roll。原声、普通字幕、编号与最终合成由父级处理。需要的画面不足时先完成原生设计，不以缩小整段横屏样片或标签切换替代本期动作。

## 从创作到冻结输入

沿现有 authored-scene 协议：先在本期 Job 内制作，再冻结 `brief.files`，交回 `realization.director_brief` 和 `realization.treatment`。不建立第二套结果协议。

brief 使用 `scripts/upstream_scene_adapter.py` 的 OneTake 分支。字段为：

- `schema_version=1`、`dependency_id=onetake`。
- `source_binding`、`template_request`、`composition` 沿现有协议记录本期来源、语义请求与实际 24fps 时钟。
- `creative_handoff` 仅有 `transcript`、`semantic_goal`、`required_change`，分别原样取已确认语义项的 `quote`、`semantic`、`visual_task`。
- `files` 冻结本期 `index.html`、原字节 `motion.js`、`workflow.json` 及实际用到的素材、字体和脚本；每项含 `media_ref/job_path/scene_path/sha256`。
- `workflow_media_ref` 指向现有 workflow 记录。

沿用现有 workflow 的 `dependency_id/upstream_commit/instructions/concept/beat_sheet/upstream_features/qa`。记录实际读取的指引、采用的概念、节奏和承接，以及实际使用的原生功能；不额外要求 TREATMENT 文件。QA 只写实际检查过的画面，不能预填通过。冻结绑定调用 `create_binding(adapter, brief_bytes)`；正式 adapter 会再核对同一语义、模板、素材与帧钟。

场景暴露原生 `window.__ready`、确定性的 `window.__seek(t)`、`window.__meta.dur`。`dur` 与已确认片段秒数一致。正式执行器调用原 `scripts/render.py`，公开参数指定 `--width 1080 --height 1920 --fps 24 --dur <秒数> --workers 1`，保留默认 180°快门，不传音轨。最后只复制原视频流并写明 SAR 1:1，不改动作、不变速。

## 当前验证范围

当前固定版本已完成两条独立原生技术样片：官方 gallery 的 morphRect 原例与仅改变外层静态布局的竖屏例，均为 2 秒、24fps、48 帧、180°快门、无声、BT.709，页面无错误。竖屏输出为 1080×1920。它们验证原生入口和运行环境，不代替每个新主题的实际画面检查；正式新 Job 继续使用既有审批、素材冻结与执行器保护。
