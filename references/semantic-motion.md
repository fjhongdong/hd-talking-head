# 语义动效规划接口与执行边界

在 `visual_direction` 需要设计动作依赖时读取本文件。复用已批准的内容提炼，不新增确认阶段，不重写关键词。六类动作均提供严格规划校验。RelationMotion 与五类 SemanticState（`replacement`、`threshold`、`delay`、`hierarchy`、`feedback`）均已完成双输入正式资格、逐态像素与动作顺序验证、发布和登记；五类 SemanticState 还绑定了用户批准的 25 秒头像合成样片。普通 Job 只有在路由命中对应已登记模板、语义家族匹配且当前 ShotRecipe 绑定完整时才能执行；登记不替代当前 Job 的人工 canary 门。

```semantic-motion-status
relation_motion: registered
semantic_state: registered
production_policy: registered_templates_only
```

## 调用

使用当前项目的兼容运行时，显式指定项目根并使用本次确认的 Python。Agent 在现有规划调用中执行：

```python
from edit.hd.tools import state, semantic_motion

job = state.load_job(job_dir)
report = semantic_motion.plan_motion_for_job(job, draft)
assert report["execution_status"] == "planning_only"
```

入口重新加载磁盘状态并调用现有 `load_approved_content_analysis`，核验内容地图及批准状态，返回 `content_analysis_sha256`。它不写文件、不改变阶段、不生成媒体。若要保存规划草稿，仍使用当前 Job 的视觉规划目录，不存入 Skill；草稿不等于正式配方。

纯函数 `build_motion_plan(draft, approved_items=items)` 只适合内部校验和测试，不能把自行构造的 items 当成人工批准。`active_action_ids(report["plan"], frame)` 只接受已校验计划，用于检查半开区间，不是动画播放器。

## version=1 的严格输入

所有下列字段必填，不接受额外字段：

- 根：`version`（整数 1）、`content_item_id`、`source_text`、`family`、`meaningful_change`、`subjects`、`actions`、`duration_frames`、`read_window`、`exit_window`。
- `content_item_id` 绑定现有批准条目；`source_text` 与其原文逐字一致。未知或 unsupported 条目拒绝；`needs_user_decision` 仅沿用现有内容门的批准，不提升为已证实事实。
- `meaningful_change`：本镜头表达的变化，不得为空。语义贴合程度仍需人工检查。
- 每个 subject：`id`、`label`、`initial_state`、`final_state`（非空单行字符串）、`preserve`（布尔值）。ID 唯一且必须被动作引用。
- 每个 action：`id`、`operation`、`subject_ids`、`start_frame`、`end_frame`、`depends_on`。主体与依赖均为唯一 ID 列表；依赖不得引用自己、后续动作或未知动作。
- `read_window`：`start_frame`、`end_frame`、`minimum_frames`。最后一个动作完成后才能阅读，实际阅读长度不得短于显式指定的最小值。
- `exit_window`：`start_frame`、`end_frame`。开始等于阅读区间结束，结束等于 `duration_frames`。

时间都是当前组件的本地整数帧，区间 `[start_frame,end_frame)`；不得使用绝对口播时码、布尔值、小数、负数、NaN 或越界帧。当前输出仍为 24fps。此接口不改原音频主时钟，也不自动延长镜头。

## 六种三阶段规划语法

| family | 必须按顺序执行的 operation |
| --- | --- |
| relation | reveal_sources → draw_connections → reveal_hub |
| replacement | establish → replace → compare |
| threshold | establish → cross_threshold → raise_threshold |
| delay | establish → wait → realize |
| hierarchy | establish → reveal_layers → resolve |
| feedback | establish → produce → feedback_return |

当前版本恰好三个粗粒度动作，每个后续动作必须依赖前一个，且开始不得早于依赖结束；不支持任意并行动作图。关系图若还有独立输出、结论和底部总结，仍需遵守路由合同，不得将这三个阶段冒充完整五时态实现。

`preserve=true` 要求初态等于终态，且只允许被 `establish / compare / wait` 引用。例如“替换机器但布局不变”，布局不能作为 replace 的目标。这里只验证声明，不证明像素位置真的保持不变。

返回 `check_frames` 包含初帧、各动作完成边界、阅读开始、退出前、最后可见帧 N−1 和下一边界 N。N 是下一镜头边界，不得拿它当当前视频的可解码帧。

## 渲染接入与登记边界

`validate_shot_recipe_v2` 仅对完整原生 RelationMotion 或五类 SemanticState 身份接受 `invocation_record.semantic_motion`，并检查模板身份、对应 family、完整规划、内容哈希和帧窗一致性；其他正式入口携带该字段仍拒绝。真实 adapter 每次执行仍须核验当前 Job 批准、模板登记和输入绑定。不得删除该字段后继续并声称按新计划渲染；也不得用旧模板固定时长比例假装消费了它。五类 SemanticState 只在当前语义精确命中其 family、容量与当前内容 QA 都通过时进入普通 Job 候选池。

## 不透明素材的退出所有权

RelationMotion 的 H.264 素材必须保持正常亮度。不可在 HTML 中降低整页 opacity 后编码为不透明视频：这会把网页底色烘焙进退场帧，外部再淡出也无法还原干净画面。

开发接口中，`artifact_alpha=1` 表示素材保持不透明；`compositor_alpha` 仅描述最终合成的退出进度，不表示素材已执行退出。正式 `segment_render` 在头像叠加之后，把整段画面按已批准 `exit_window` 混合到同一局部时钟的 A-roll；退出首帧保持完整海报，最后一个实际编码帧回到 A-roll。FFmpeg `blend` 的 `N` 从 1 开始，必须以 `N-1` 对齐零基帧计划。不可只验证末帧而遗漏退出起点。

当前实现限单组件、全镜头帧窗、base 层、`bottom_window`，退出至少两帧并结束于镜头边界；混合组件、子帧窗和其他出镜方式不得静默套用。若需要扩展，先明确整组退出合同，再实现与验证。验证时分别检查素材原帧和头像合成后的退出起点、中点、末帧，并用随时间变化的 A-roll 检查同步；素材 MP4 末帧不再作为“已淡出”的证明。

规划接口本身不证明字体、美观、空间避让或真实动作顺序。当前六类已登记实现另有 adapter/renderer 消费证据、双输入真实渲染、逐态像素检查与人工 canary 记录；源码、结构合同或证据任一变化都必须重新资格验证，不得沿用当前登记身份。维护者不重签旧 Job，不修改历史资格证据来掩盖变化。
