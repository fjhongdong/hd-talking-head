# 阶段执行与续做

正式制作只使用 `scripts/run_stage.py`。它调用现有十二阶段函数，不负责新建模型、生成语义判断或改变 Job 配置。通过已准备的 `project_python.py` 运行；不再使用旧 `run_video`、`auto_advance`、`quick_cover` 或逐段改写计划的 `build_native_visual`。

## 执行当前阶段

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/run_stage.py --job-context <workspace>/job-context.json
```

省略 `--stage` 时读取最早未完成阶段；显式指定时仍须满足现有依赖。已批准阶段无新输入时核验并复用；要改变输入，先用现有 `state.revise` 明确修订，再执行。`needs_revision` 可以继续调用原 runner；`blocked` 保留当前原因，按原恢复入口处理。`ready_for_review` 返回已有候选和当前 revision，不重新生成。

配置和运行时身份沿用当前 Job。只有预检过期或尚未绑定新批准视觉计划时自动复检，不重写配置批准；模型、费用、项目或源码身份变化仍走原确认或迁移入口。所有阶段只处理本期 Job，不迁移其他视频。

`visual_direction` 的 treatment 还须包含当前剪后口播的 `beat_sheet`。字段与真实词引用见[确认前的逐句盘点](visual-quality-contract.md#确认前的逐句盘点)；准备 helper 不自动代替该设计工作。确认入口检查完整性并在原路由表显示合并依据，不能只凭 B-roll 占比提交长镜头清单。

## 显式输入

`--input-json` 用于以下阶段的已完成创作输入；相对媒体路径均相对当前 `job_dir`，命令行 JSON 文件本身应传绝对路径。

| 阶段 | JSON 字段 |
| --- | --- |
| `content_analysis` | `analysis`，按内容分析合同的完整对象 |
| `cover_direction` | `direction`；本期完整预览另用 `direction_preview` |
| `cover` | `image`、`prompt`，直接绑定已确认的完整带字图片，不重画或缩放 |
| `preview` | 仅本期明确覆盖默认开场或配乐时传 `opening`、`music` |

`inspect`、`edit_structure`、`subtitles`、`delivery` 直接消费此前批准的正式产物。

口播清理先绑定真实转写：

```bash
<python> <skill>/scripts/run_stage.py --job-context <ctx> --stage speech_cleanup \
  --video-use-result <workspace>/edit/transcripts/<source>.json \
  --invocation-json <真实调用记录.json> --cleanup-plan <清理方案.json>
```

调用记录沿用真实进程的 `entrypoint`、`exit_code`、源视频和结果摘要。没有记录就说明缺口，不拼造成功、不重新收费识别。只完成转写时可先不传 `--cleanup-plan`；随后在同一阶段传入清理方案，继续复用转写。已完成清理提案要修改时先明确修订。`edit_structure` 单独执行，不在转写入口里顺带剪辑。

视觉计划先接收已完成内部语义检查的草稿，从启用组件的 bindings 读取本次依赖，完成所选能力准备及实际入口绑定检查后，才发布待用户确认的完整视觉路由表。准备失败保留原资料，当前新列表不会进入待确认状态。若包含生图或生视频，入口先在独立 `07-visual-confirmation/rN-id/` 冻结 proposal 和 `generation_plan.steps`，再发布整表；不得先生成媒体再补报审：

```bash
<python> <skill>/scripts/run_stage.py --job-context <ctx> --stage visual_direction \
  --director-brief <director-brief.json> --treatment <treatment.json> \
  --reviewed-visual-text <reviewed-visual-text.json>
```

原生代码组件可用 `compose_visual_plan.py` 准备；它输出 `native-inputs/draft-<id>/` 内的 Job 相对路径。`visual-routing.md` 必须覆盖剪后时间线上的全部贴片和 B-roll，每行包含开始/结束、类型、剪后原话与语义、tags、具体模板及实际来源。先由语义生成 tags，再由能力库检索模板；不得用屏显 labels 代替 tags。`visual_text_draft` 指向 `visual-text-draft.json`，状态为 `pending_review`，只列出待审屏显和候选原文依据。它不能作为 `--reviewed-visual-text` 输入。宿主对照当前 director 草稿和已批准内容逐条检查；删除越义文字或完成合理转述的语义复核后，另存正式记录：

```json
{
  "content_analysis_sha256": "<当前已批准内容分析的摘要>",
  "entries": [{
    "segment_id": "<当前镜头ID>",
    "text": "<已实际审阅的屏显文字>",
    "source_ref": "item:<该镜头选中的内容项ID>",
    "source_quote": "<该内容项的完整原文>",
    "reason": "<本次改写为何没有新增或改变事实>"
  }]
}
```

正式记录只使用上述字段，不复制草稿的待审状态或候选来源列表，不由脚本预填“已审通过”。已有原文及关键词的直接引用可由现有内容检查确认。视觉方向阶段向用户展示并确认整张 `visual-routing.md`；这一次确认覆盖整片贴片、B-roll、tags、具体模板、图片/视频渠道和生成步骤，不再增加逐条确认或后续成片确认。确认后的同一次 `visual_direction` 续做只返回具体宿主 tool actions，输入可包含：

```json
{
  "generation_results": [
    {"action": "<原 action>", "response": "<真实规范响应>", "queried_task_ids": ["<真实任务ID>"]}
  ],
  "realization": {
    "director_brief": "<native-inputs/realized-.../director-brief.json>",
    "treatment": "<native-inputs/realized-.../treatment.json>",
    "reviewed_visual_text": "<可选路径>",
    "host_qa_note": "<实际检查结果>"
  }
}
```

原确认目录中的 proposal、director 和 treatment 保持原样；实际媒体绑定写入新的 realization 文件。`prepare_template_inputs` 是宿主内部工作，不是用户确认步骤。宿主按已选模板的原生准备入口，将真实图片或视频写入 brief；直接 AI B-roll 使用 `generated_media.record_from_queue` 保存实际观察、当前口播时窗和源片摘要，并用 `prepare_binding` 生成绑定。

修订某枚原生 brief 后，须同步该组件的实际 binding、`skill_selection.beats[].binding_snapshot`、场景路径、引用摘要及源码摘录，并在重新发布提案前调用已有 `broll_skill_selection.validate_selection`。源输入已经具备时，还须调用 `motion_capabilities.check_offline_plan` 检查当前源码证据与语义引用，不能把摘录仍指旧代码的提案留到正式编译才发现。不得只改 director 的 brief 摘要，等用户确认后才发现选型快照仍指旧输入；也不得放宽完整绑定比对。未改动组件保留原绑定与媒体。

默认执行器按已确认的 brief 内容摘要读取 Job 内 JSON，不要求文件必须名为 `brief.json`。自定义名称与分版本目录同样须精确匹配摘要，并通过适配器原有的结构、时窗和来源检查；不能按相近文件名替代缺失输入。

未来图输入使用 `{"$step":"image-step","output":0}`，不得填写不存在的未来文件摘要。宿主实际完成生成后才写入真实媒体和哈希，再构造后续视频请求；模板内部生图、生视频与直接 B-roll 共用启动时确认的渠道。没有生成步骤的已确认素材直接沿原编译入口执行。

自动 `treatment.json` 同样是候选资料：`semantic_assessments` 初始为 `needs_review`，Skill 比较和 assignments 只是待审选型。宿主检查引用原声、实际场景和候选比较理由，修正不实或通用填充理由后，才将实际通过的组件记为 `pass`。未审语义由现有正式发布检查阻断；不把离线输出 `needs_review` 当作审阅完成。

每个原生 beat 显式提供 `tags` 和 `content_item_ids`；`tags` 是从剪后语义得出的检索短语，`labels` 才是屏显文字。其他准备入口在现有 treatment 的 `motion_queries` 为每个视觉组件（包括直用素材）记录一条 `{ "segment_id": "seg-001", "component_id": "native-visual", "tags": ["并列要点", "层叠出现"] }`。查询必须完整、唯一，包含非空的实际语义标签；直用素材只校验标签完整性，模板栏写“素材直用（无动效模板）”，素材编号放在来源栏。选中动效模板须由这些 tags 按实际用途召回；开始/结束、语义、原话和模板身份从当前计划及批准的剪后词表派生，不再另填一套。

B-roll 校准必须对应最终量化窗口，按校准器输出的三位小数起止时间精确匹配；相邻窗口不互相替代。

编排辅助入口读取 `05-speech-cleanup/word-transcript.json` 的校对正本，并按正式 `timeline-map.json` 映射剪后词锚；不得回读 `report.json` 的原始识别文字覆盖已完成的校对。正本缺失时停止，不补用旧文本。

其他来源继续使用各自已接通的准备入口，最终提交相同的视觉草稿合同。没有可执行绑定时停在资料准备，不把来源改标成代码动效。

正式编译在发布前统一检查密度、词锚、来源和保留内容。`preview`、`delivery` 可继续传同一 `--treatment`，以复核已说明的无 B-roll 区间；比例说明不豁免默认下限。

`visual_canary`、`visual_assets` 只为实际选中的依赖组装适配器。原生代码组件、用户素材、官方资料、素材库及完成记录中的 AI 图片/视频使用包内默认工厂；图片与视频按各自组件绑定，混用时不会共用错误的媒体类型。直用素材保留原件和原尺寸，另存 PNG 或无声规范视频；按已确认时窗合成，不重复获取或生成素材。未知执行绑定在整表发布前报告缺口。

局部视觉返修时，canary 自动采用本次 `artifact_scope` 中的受影响镜头，避免重做未变样段；也可通过 `input-json.segment_ids` 指定本次待检查镜头。正式资产仍按逐段输入身份复用其余媒体。

清单和成片编号共用 `visual_confirmation.approved_numbered_rows(job)`，按本期已确认 proposal 的冻结行序定位 `row_id`，不从当前稿件各自排序。最终合成在对应帧窗右下角叠小编号，时间统一加 `opening.body_offset_frames`；封面与空档不显示。编号图集和时窗随现有 preview 产物、报告与哈希登记，交付直接沿用带编号的正式预览。

待审 proposal 的反复修订须保留上一代 `07-visual-direction` 的发布 lineage。proposal 文件不能代替正式目录的覆盖依据；也不能将旧正式目录放进会在原子交换时失效的 ACTIVE 引用后直接发布。恢复现存 Job 时，先核对引擎保留快照与旧目录，再用现有状态 API 将旧发布身份移入 lineage，并保留原 proposal 与真实用户批准，不重签确认。

宿主已有专用适配器仍可显式传入 `execute_stage(..., component_adapters=...)`，或通过 `--adapter-factory <当前Job工厂.py>` 提供 `create_adapters(job, project)`。正常支持的来源无需另写工厂；工厂只组装已接通入口，不替换来源、不批准阶段。

提交视觉清单前，另行汇总贴片与 B-roll 的数量、覆盖时长和未使用的真人重点；贴片重点须对应提问、原因、转折、对照或结尾语义，未做贴片的重点写明保留真人理由。该汇总用于检查两类画面是否分别覆盖，不设固定贴片配额，也不能用 B-roll 比例替代贴片检查。

## 宿主审阅后推进

每次执行返回 `job_id`、`job_dir`、`stage`、`status`、`revision` 和实际 `artifacts`（包含路径、文件摘要和字节数）。机器校验后，宿主仍检查这些实际产物的画面、原声、字幕及语义。通过后，将刚审阅候选返回的 `job_id`、`job_dir`、`stage`、`revision`、完整 `artifacts` 原样放入本次 QA JSON，再补充检查结果：

```json
{
  "job_id": "<本次任务ID>",
  "job_dir": "<入口返回的实际任务绝对路径>",
  "stage": "visual_canary",
  "revision": 17,
  "artifacts": [{"path": "<实际产物相对路径>", "sha256": "<实际文件摘要>", "bytes": 123}],
  "passed": true,
  "note": "填写本次实际检查结果，不复制示例作为验收"
}
```

```bash
<python> <skill>/scripts/run_stage.py --job-context <ctx> --stage visual_canary \
  --review-json <本次实际QA.json>
```

`speech_cleanup` 的返回还包含实时 `cleanup_checks`。宿主核听后剪除口误并重建提案；残留的必要强调或呼吸，在同一 review JSON 填 `speech_cleanup_resolutions: [{"candidate_id":"返回的实际ID","decision":"keep","reason":"核听后的具体保留原因"}]`。必须覆盖每一剩余候选；无候选则省略。不增加用户逐项确认。

视觉 canary、assets、preview 的返回含 `motion_readability`。`fail` 先修对应镜头；`needs_review` 由宿主按[实际文字检查](motion-text-readability.md)填写 `motion_readability_resolutions` 的真实帧和文字框，不靠自由 QA note 放行。该检查覆盖全部实际动效，最终交付会再次拒绝未决项。

示例中的占位符、revision 和字节数都不能照抄。入口先核对被审任务、revision 和完整产物身份，再保存本地 QA 并调用原阶段批准；不为旧记录补上当前任务身份。`cover_direction`、`cover`、`visual_direction` 在同一 JSON 提供本次真实 `user_confirmation`。整表确认时使用 `--stage visual_direction --review-json <整表确认.json>`；入口自动记录 `approval_scope=visual_plan_and_delivery`，保存在 `manifests/local-qa-visual_direction-r<revision>.json`。随后宿主继续内部制作，不向用户逐阶段重复提问。

`review_required=user` 表示需展示当前封面或完整视觉表；`review_required=host` 表示宿主自己核对后继续。后续 canary、visual_assets、subtitles、preview、delivery 均为后者。交付 QA JSON 沿用同一组真实任务/产物字段及 `note`，无需 `user_confirmation` 或重复填写最终视频摘要；入口从已核对的 artifacts 取得成片身份，调用 `approve_plan_delivery` 写入 `plan_authorized` 完成记录，引用真实整表批准来源。该记录表示已制作交付，不表示用户看过并验收成片。

已批准阶段再次调用不会重做。十二阶段均批准后，仍由 `audit_job_completion.py` 核实正式完成，不以阶段列表代替最终交付回执。
完成检查返回 `inconsistent` 时，阶段入口也返回非零退出码；JSON 保留具体检查结果。其他完成状态的退出规则沿用独立检查入口，退出码为零本身不代表 `formal_complete`。

### 封面及独立素材的渠道入口

`run_generation.py --project-root <project> --job <job-dir>` 提供 `prepare / add / next / record`。`prepare` 用 `--purpose image|video --request-id <id> --arguments-json <参数文件> [--input-files-json <输入身份文件>]` 返回本 Job 选定渠道的请求；按当前 `manifests/generation-channels.json`，每个 purpose 必须声明 `model_binding`：`mode=argument` 时将已选模型写入参数并在不匹配时拒绝，`mode=fixed` 时不注入 `model`，服务管理的模型标识必须来自真实工具。最终生成记录以实际提交身份为准。参考输入声明 `reference_mode=local_path|upload`；`upload` 由宿主先执行声明的真实上传 action，将原始响应和上传回执回传，再用上传结果替换逻辑请求中的冻结本地路径提交生成，不新增确认门，并保留后续复用的上传结果。

`add --plan-json <requests文件> --plan-sha256 <摘要> --user-confirmation <本次真实确认>` 登记封面等已确认批次。`next --request-id <id> [--account-limit <当前账号并发上限>]` 返回 submit/query/wait 或 upload action；宿主执行真实工具，将原 action 与规范结果分别保存，再用 `record --action-json <原action> --response-json <真实结果>` 回传。规范结果包含 `status`，异步结果包含真实 `task_ids`，完成结果包含 `artifacts: [{"type":"image|video","path":"<真实文件>"}]` 或真实媒体 URL。源文件保留，结果复制到 Job。视觉表内的步骤直接由 `run_stage.py` 登记和续做，不走再次确认的 `add`。

视频宿主先保存供应商原始文件和原始响应。需要格式处理时另存同宽高比的规范文件；不覆盖原件、不变速、不随意裁切。规范文件路径、来源和处理链见下方统一示例。

规范响应的处理后视频示例：`{"type":"video","path":"artifacts/normalized.mp4","source":{"path":"artifacts/provider-original.mp4"},"processing":"24fps silent H.264 yuv420p; aspect ratio preserved"}`。`record` 入口分别复制并保存原片与规范片，`source` 落盘为含 `path`、`sha256`、`bytes` 的身份；completed record 保留 `generation.source_media` 与 `generation.processing` 的关系。原片已合格时只写其 `path`，不添加虚假的处理来源。可选顶层 `provider_response` 仅保存真实供应商返回，provider 原始响应仍单独保存，规范 response 不得冒称 raw response。`upload` action 发出后，下一次 `next` 返回 `blocked` 与 `input_upload_pending`，等待宿主用原 upload action 和原上传 response 走现有 `record/generation_results` 回传，避免重复上传。

### 确认前的头像编排与固定编号

`run_visual_direction` 在准备所选依赖前安排整组头像。返回 `prepared=false`、`needs_visual_preparation=true` 及 `actions` 时，宿主在当前任务内按目标时窗准备原生输入、完整引用、阅读窗和真实采样，再次提交草稿。此返回不表示阶段完成；不要进入确认、生成或后续阶段，也不要向用户新增确认。空间不足、原生能力不支持安全保持时先调整本次草稿。无未决动作后，入口另存规范稿并按原流程准备依赖、检查、冻结proposal。确认准备的独立完整性门也拒绝直接提交的缺项草稿。

新proposal中的 `numbering` 保存全部 `row_id → number`，包含已删除项目；活动项目以 `rows` 为准。局部返修保留 `segment_id:component_id`，新增组件使用新ID及从未用过的新号。首次引入时只继承此前真实批准清单的冻结编号，不改写旧proposal。清单、稀疏编号图集与成片共用映射；重叠时窗的角标分行，半开帧窗相接时复用位置。底部安全区容不下时明确停止，不缩小字号或覆盖正文。

### 当前媒体的实际画面复核

新proposal冻结 `visual_review_policy=visual-review-v1`。canary、assets、preview 返回的 `visual_review` 是待检查义务，列出计划身份、实际媒体引用、逐组件 `row_id`、可见意图及文件内播放时窗，不是已检查结论。

宿主实际播放对应片段后，在同一review JSON加入 `visual_review`：沿用实际 `policy_version`、`stage`、`plan_ref`，`observations` 每项包含 `row_id`、`media_ref`、数值秒区间 `playback_window`、具体 `conclusion`，以及真实的 `size_position_clear`、`unobstructed`、`semantics_clear`。必须覆盖当前所有待查组件；回放区间完整包含义务时窗且位于实际媒体内。canary/资产使用段内时钟，preview包含正式封面偏移。不得把抽帧、解码、代码存在动画或待查列表复制为“已播放”。

不改现有 `motion_readability_resolutions`：OCR硬失败仍需修正，低置信仍须真实量框。画面观察和文字检查同时通过后才内部批准。交付消费者再次核对当前preview回执，直接调用状态批准不能绕过。新要求不追溯追加到旧已批准proposal，创建新修订清单时才启用。
