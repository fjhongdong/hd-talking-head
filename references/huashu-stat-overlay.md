# Huashu 原生单数值贴片

只接入 `alchaincyf/huashu-motion` 的 `talking-head` 模板中单个 `stats` 事件，作为 A-roll 透明贴片。适合金额、数量、百分比或时长的一个确切数值，不用于并列要点、趋势图、无量化结论或 B-roll。它与 `huashu-art-motion` 是不同依赖；不得借用后者的执行身份或验收结论。

## 来源与调用

先读项目内 `skill-development/vendor/huashu-motion/skills/huashu-motion/SKILL.md` 及其 `references/talking-head.md`、`references/contract.md`。当前固定提交为 `5f2608c2e12abcf518f74dde86093b19f7f88603`；源码由既有 `ensure_visual_broll_skills.py --skill huashu-motion` 准备，不修改上游。版本更新仍走统一依赖更新流程，不静默重签已有 Job。

我方依赖 `huashu-motion-native`，入口 `scripts/huashu_stat_adapter.py`，运行检查 `scripts/huashu_stat_runtime.py`；版本 `1.0.0`、渲染器 `HuashuMotion`、执行器 `reference_adapter`。用 `create_adapter(project_root, python_executable, brief_loader, execution_mode=...)`、`create_binding(adapter, brief_bytes, reference_sample)`、`create_artifact_probe(ffprobe_executable)` 接入现有执行器。`brief_loader` 返回冻结的原始 bytes，不能重新序列化。

两条路径必须明确选择，不互相 fallback：

- `native_export` 调用未改的 `om new --template talking-head` → `om fork --size 1080x1920` → `om set` → `om render --transparent --fps 24 --workers 1`。只填公开变量，保留原生计数、进退场及版式；清空模板自带的人名、关键词、章节和音视频。输出原生 MOV 后再规范化 alpha。
- `reuse_mov` 只读四份已冻结资产，核对真实数值、标签、时钟、公开颜色、原生布局、源片绑定和成功调用记录。内容或时长不一致即停止，不能把测试数字 7 当成新内容。它不需要 Node、Chrome 或再次调用原生导出器。

原生路径使用现有 Node 22+、系统 Chrome 和 FFmpeg；模板自带字体，不需要 `drawtext`、系统中文字体或额外 npm 包。公共依赖探针显式使用 `reuse_mov`，只证明已有媒体处理可调用；选择 `native_export` 的工厂会另查固定源码、Node 和 Chrome。缺失或不符时报告，不自动下载浏览器、更换引擎或重做资产。

## 输入与语义

Brief schema 1 的固定字段：

```text
schema_version, source_binding, composition, parent_safe_zone, metric,
layout, style, template_request, upstream, execution_mode, assets
```

`source_binding={aroll_sha256,segment_id,start,end}` 对照当前批准的 A-roll、镜头与剪后时间。`composition={width:1080,height:1920,fps:24,frames,alpha:true}`，帧数必须等于该区间；`parent_safe_zone` 原样取组件的 `render_window.safe_zone`。正式工厂核对批准配方、annotation 层、完整帧窗、源码和本期报告，不接受另一个镜头的安全区或词锚。

`metric={value,prefix,suffix,label,target_frame,hold_frames}`。数值必须是当前台词中的确切事实或明确的假设值，来源与限定词保持一致；不能凭画面需要编数字。值须为有限、JS 安全范围内的整数或小数；原生小数精度不支持绝对值介于 0 与 0.000001 的值。前后缀各不超过 12 字、标签不超过 40 字；这是输入边界，不是美观或可读性保证。

`template_request={semantic_family:numeric_emphasis,information_units:1,numeric_values:[value],numeric_scale:linear}`。使用 `template_id=huashu-motion/talking-head-stat`，`custom_fallback / structural` 如实表示竖屏适配，不冒充完整库资格。`visible_text` 必须等于 `[prefix+数值+suffix,label]`。

制作前在原有 treatment 登记 `overlay_selection`：`intent_relation=numeric_emphasis`、`native_route=huashu-stat`、`visible_action=native_count_up`、`visual_structure=single-metric`，说明为什么本句值得强调这个数值。重复结构继续走现有 `repeat_review`，不靠随机换颜色制造多样性。

## 原生时钟与真实词锚

`target_frame` 是 **原生计数 tween 完成帧**，不是“最终数字第一次可见帧”。原生整数四舍五入可能使最终数字提前出现；不可把两者混称。公开 `stats.at=target_frame/24-0.35`，`stats.hold=hold_frames/24+0.35`。退出起点是 `(target_frame+hold_frames)/24`；至少保留两帧供完整透明退出检查，目标帧不早于 15，保持不少于 24 帧。

Treatment 的 `overlay_alignment` 为该组件记录一个事件：`slot=0 / kind=count_landing / text=完整数值 / basis=current_clause / anchor={index,text}`。锚点必须来自本 Job 已批准的逐词转写，并经当前剪辑映射换算；完成帧与词起点误差最多一帧，不使用其他组件的 0.8 秒容差。报告写入既有 `visual-routing.md` 的“原生贴片实际词锚与时钟”，正式执行前重新核对，不另建第二套词锚表。

该检查只能证明配置的完成帧与词时钟相符；实际可见数字、可读性和退场仍看本期输出。测试算术用的词表不是 Scribe 证据，不写入正式 Job 或批准记录。

## 布局、透明输出与复用

`layout.subject` 只使用原生公开的 `subjectX/subjectW/subjectTop/subjectBottom/cardBottom`；`layout.crop`、`layout.placement` 各为 `{x,y,width,height}`。原生舞台和父画布都是 1080×1920，仅允许固定裁切及等比静态摆放。`style` 只有 `accent/ink/card/statTint` 四个原生色值。按当前真人留白和字幕位置配置，不固化测试样片坐标，不缩小文字掩盖越界。

我方逐帧扫描原生 alpha 的完整动作范围，禁止裁到图形、阴影和退场；换算后的范围须完全位于父级安全区。输出单视频轨 QTRLE/ARGB MOV、24fps、精确帧数、SAR 1:1；随后仍由现有父级合成器负责 A-roll、原声和唯一字幕轨。这里不新增动作、关键帧或时间线。

`native_export` 的 `assets=[]`。成功后保留原始 MOV、原生 portrait HTML、调用记录与来源记录，供同内容复用。`reuse_mov` 的四个 `media_ref` 为 `native-mov/native-config/native-evidence/native-source`，每项仅有 `media_ref/job_path/sha256`；走公共 FD 冻结。

`native-source` schema 1 记录 `source_revision/source_binding/native_sha256/config_sha256/evidence_sha256/recorded_output`。原生 HTML 只允许公开变量默认值、对应文本占位和 canvas 尺寸变化，JS/CSS 结构指纹必须保持固定。证据须含本 pin 的 `native-render` 与 `native-probe` 各一次成功状态且指向同一原始输出；后续独立合成失败不抹掉已完成的原生执行证据。历史资产补作复用关联时明确它是新派生记录，不伪造历史调用或用户批准。

当前已确认数字 7 测试样片的视觉，并已通过既有 MOV 的复用规范化检查。新增一次“1250 条”测试实际经过本包 adapter CLI → 固定原生 `new/fork/set/render` → 透明规范化：输出 6 秒、144 帧，完整动作位于所给安全区；入场采样为 1212、稳定采样为 1250、退场后全透明，文字完整。此结果证明新数值进入了原生生成封装，不是复制旧 MOV，也不是正式 Job 执行器或真实词锚验收。

本次用户明确将真实数值口播对齐留到下一条视频。届时必须使用该片已批准的转写、剪后映射及正式 VisualPlan，完成原有 canary 与真人画面检查；不补造测试词表或继承测试数字的批准。不宣称全库或生产成片已通过。新问题保留失败日志并停下分析，不自动重试、修源码或切换路线。
