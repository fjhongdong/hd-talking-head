# Overlay Studio 原生要点钉板

这是 `overlay-studio-native` 的条件接入说明。它支持单个原生 `pin-board` A-roll 短要点候选：适合并列或累积信息逐项落板，不用于 B-roll，不替换已验收 B-roll，也不把 Overlay Studio 的其他卡片声明为已接通。

## 接入身份

- 上游 Skill：项目内 `vendor/overlay-studio/.agents/skills/overlay-fx-generator/SKILL.md`
- 固定提交：`e35e1aff9dae3b3addc21f68f3bcd51f95bdc1a8`
- 依赖身份：`overlay-studio-native`
- 渲染器：`OverlayStudio`，producer version `1.0.0`
- 我方入口：`scripts/overlay_studio_adapter.py`
- 我方运行时检查：`scripts/overlay_studio_runtime.py`
- adapter 类型：`ReferenceProcessAdapter`；正式执行器：`reference_adapter`

系统 Chrome 只按当前运行时实测身份记录，不固定写死版本，也不下载 Puppeteer 自带浏览器。缺依赖时由统一准备入口报告并停止；本说明不授权安装或升级第三方源码。

## Brief 与时钟

我方 brief 使用 schema 1，固定字段为：

```text
schema_version, source_binding, composition, doc, layout, parent_safe_zone,
template_request, assets, upstream, execution_mode
```

`doc` 只含一个原生 `pin-board`。`card.start/end` 是秒，`params.times` 是相对 `card.start` 的秒；`inkColor`、`cam` 不是必填。本路线不使用 cam，关闭音效、glow、breath，原生 speed 保持 1。标题、副题为空，当前只接入有独立词锚的条目。不要把父级默认字体配置伪造成原生 `fontSize` 参数。

`source_binding` 使用 `aroll_sha256 / segment_id / start / end`；`composition` 是 `width=1080 / height=1920 / fps=24 / frames / alpha=true`。`template_request` 为 `semantic_family=cumulative_points`、当前条目数量的 `information_units`、`numeric_values=[] / numeric_scale=not_applicable`。原生“要点 n/N”是进度提示，不是口播事实数据。

词锚只读取当前 treatment 的 `overlay_alignment.events`，不在 brief 复制另一套 events；每项使用 `slot`（从 0 起）、`kind=pin_drop`、`text`、`anchor={index,text}` 和 `basis=current_clause|recap`。`overlay_selection` 使用 `native_route=pin-board`、`intent_relation=parallel`、`visible_action=cumulative_pin_drop`、`visual_structure=pin-board`；重复结构继续使用现有 `repeat_review`。此处核对的是原生触发时刻；实际可读帧与入场延迟仍在当前输出检查，不套用历史样片的固定补偿秒数。

布局由当前真人画面和完整动作边界确定：静态 crop 与等比 placement 必须覆盖落板、阴影、退场，完整落在父级安全区内，并避开人物和字幕。不能把样片坐标、`scale=2` 或“两项内容”固化到其他 Job；字体保持原生，不新增字号系统。整体缩放会改变最终显示字号，64px 是阅读起点而非硬下限；不能仅靠缩小通过边界检查，须在实际真人合成中检查可读性与人物留白。

`layout.crop`、`layout.placement` 均为 `{x,y,width,height}`，前者位于原生 1920×1080 舞台，后者位于 1080×1920 透明画布。两者必须等比；导出检查全部帧的可见边界，不能用追踪裁切掩盖越界。

`parent_safe_zone={top,bottom,left,right}` 是从当前已批准组件 `render_window.safe_zone` 取得的派生快照，不是另一套可自由配置的安全区。正式 adapter 入口核对快照与实际组件逐值相等，并核对画布尺寸；缺失或不一致即停止，不补默认值。公共执行器仍冻结同一份 brief 原字节，子进程只读取一次。转换在现有全帧 alpha 扫描后，按实际 crop/placement 计算完整动作的最终范围（保守取整并留 2px 缩放采样余量）；越出父级安全矩形就在编码前停止。单独运行转换只证明符合所给快照，不能代替正式入口核对当前镜头。

## 输出、复用与验收边界

原生 PNG 使用 straight alpha；父级需要时只做无损 QTRLE/ARGB 转换，再由现有合成器叠加 A-roll 原声和唯一字幕轨。`execution_mode` 必须明确为 `native_export` 或 `reuse_png`，不自动 fallback。

执行使用 `create_adapter(project_root, python_executable, brief_loader)`、`create_binding(adapter, brief_bytes, reference_sample)`、`create_artifact_probe(ffprobe_executable)`。`native_export` 的 `assets=[]`，只调用隔离工作目录中的未改原生 CLI；端口冲突则停止，不接管不明服务。`upstream={source_revision,runtime_identity}` 从当前 `overlay_studio_runtime.check_runtime` 取得。

`reuse_png` 不调用导出器。将现有 PNG 原字节按帧序封装为普通 ZIP，只有 `frame_000001.png` 至当前帧数；再复制对应的原生 doc、source.json 和成功导出 result.json 到当前独立 Job。`assets` 分别使用 `native-pngs / native-doc / native-source / native-evidence` 四个 `media_ref`，每项仅有 `media_ref / job_path / sha256`。复用现有公共 FD 媒体冻结合同，不改 Adu/Hypit 的完成态 helper，也不借用其身份。当前复用入口要求文案、原生时钟、源片及区间与原记录完全相同；新内容不能借历史 PNG 继承批准。

开发检查已分别通过 `reuse_png` 复用和 `native_export` 新短文案制作：两条都经过公共执行器 → 父级 A-roll → 原声与唯一字幕的最小合成，并检查安全区、真实词锚和入／中／出画面。新文案检查实际执行固定版本的原生 lint 与导出 CLI，使用系统 Chrome，不改原生动效、第三方源码或已验收成片。结果只证明当前 pin-board 入口及这两种执行方式，不代表当前 Job 已批准，也不扩展为 Overlay Studio 全部卡片、任意内容容量或全片默认样式已验证。遇到运行时、时间、透明度或布局新问题，保留日志并停在当前路由，先分析再决定是否修正。
