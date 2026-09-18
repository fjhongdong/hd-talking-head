# 权威素材使用回执与变更事务

本合同在用户追加、替换或撤回 Job 资料时加载。它不重做内容理解、封面方向或已批准镜头；它只根据当前工作流的权威回执计算影响。

## 阶段回执

新 `full-v2` Job 的每个阶段在进入 `ready_for_review` 时都将 `material-usage.json` 加入正式 artifacts。回执绑定 `job_id`、`stage_id`、`stage_revision`、`stage_input_sha256`、生产者和完整声明标志 `complete_reference_declaration=true`。

每条引用必须包含 `material_id`、`material_sha256`、`consumer_kind`、`consumer_id`、`binding_path` 和实际受影响的 `artifact_paths`。无用户资料消费的阶段发布空 `references`，不省略回执。路径越界、产物未登记、生产者未知、revision 不一致、资料哈希变化或声明不完整时整份拒绝。发布失败不留下可被工作流认可的半成品回执。

配乐及许可由 preview/delivery 发布 `consumer_kind=background_music` 引用，分别绑定 `/plan/music` 与 `/plan/license`。仅这类资料改变时，沿现有 DAG 修订 preview 和 delivery，不重做上游批准内容；音乐不是视觉 segment，不创建假的 `artifact_scope`。

消费阶段按当前版本核对已批准的完整产物集合。素材回执是溯源附件，不是封面图片或音视频输出；已登记的回执必须校验文件哈希、阶段绑定和完整声明，不能因业务输出数量未变而拒收，也不能允许任意额外登记产物。集成测试应使用上游实际发布的产物集合，不能用省略回执的旧夹具代替新版链路。

旧 Job 不补造回执，也不改变其版本的产物集合；不从文件名或目录反推“没有使用”。缺少完整声明时标记 `material_usage_unverified` 并 fail closed，由人工选择较早修订点。

## 只读计划

`scripts/manage_user_materials.py ... plan` 只读素材索引、workflow 和当前 artifacts，返回 `direct_references`、`affected_stages`、`earliest_stage`、`artifact_scope`、`reused_artifacts`、`rebuild_artifacts`、`required_human_gates` 和 `blockers`。依赖从项目运行时 `state.dependencies_for` 计算，Skill 不维护第二份 DAG。

`plan_hash` 覆盖源文件身份、素材索引、workflow revision、直接引用、影响阶段、产物划分和人工门。计划期间不复制新资料、不改 workflow、不增加 revision。宿主必须完整展示计划并得到本次人工确认，再传入逐字匹配的 `confirmed_plan_hash`。

## 事务应用与恢复

`apply` 仅接受当前工作区、当前 workflow/index 与精确 `confirmed_plan_hash`。事务回执使用三个阶段：

1. `prepared`：在受管临时路径流式复制并重算媒体身份。
2. `material_committed`：原子发布新 material/asset 与变更回执；旧字节保留，旧 ID 标记 `superseded` 或 `withdrawn`。
3. `workflow_revised`：对已使用的 replace/withdraw 恰好调用一次 `state.revise(job, earliest_stage, reason, artifact_scope)`，记录修订前后 revision。

`append` 保持 `workflow_action=preserve`。使用中素材的 replace/withdraw 使用 `workflow_action=revise`；主视频与主文案输入继续拒绝此类变更。同一 `operation_id + plan_hash` 可在复制失败、索引提交失败、revise 失败或进程中断后重放；已完成事务重放不增加第二份素材或 revision。任何源文件、索引、workflow 或确认哈希变化时零写入停止。

`artifact_scope` 精确指定受影响的视觉 segment，支持 `segment-inputs` 的运行时可复用其他已批准媒体字节。状态机仍会将 `earliest_stage` 及依赖的下游阶段进入重审；精准媒体复用不等于自动保留下游人工批准。
