# 每任务工作区与用户资料合同

每个新视频任务都先创建独立 Job 根目录和完整子目录，且必须发生在任何分析、下载、生成或渲染之前。Job isolation 保持工作流字段边界、路径约束、记录一致性、失败恢复和产物一致性；新任务不复用旧 Job，当前任务的中间产物不写到 Job 外。

## 创建与目录

正式流程优先运行 Skill 自带的 `scripts/initialize_video_job.py`。它先调用 `create_job_workspace.py` 创建独立 workspace 和 `00-user-provided`，再创建 `full-v2` workflow，最后只在 `job-context.json` 指向的权威 `job_dir` 中创建十二阶段目录、`manifests`、`qa`、`cache` 和 `tmp`。不得在 workspace 顶层再创建一套重复输出树。

初始化前核验发布包及真实运行时，冲突时不复制用户输入。workspace 的 `job-context.json` 固定绑定实际 Python、项目路径、模块哈希、合成器版本与 `skill_release`，不能手工改写来迁移。环境草稿、预检和批准只写到权威 job_dir 的 `manifests/provider-config.json`、`dependency-preflight.json`、`setup-approval.json`。相同输入在另一个 workspace 中也属于另一个 Job，不能沿用批准。

`scripts/create_job_workspace.py` 是通用资料导入底层；只有不使用本项目状态引擎的适配器才直接调用它的顶层输出目录模式。当前适配层可以改变父目录，但不能合并不同 Job 或省略职责目录。

`00-user-provided/` 固定包含：

- `video/`：用户提供的口播、录屏、官方片段或参考视频。
- `images/`：人物、产品、界面、场景和风格参考图。
- `audio/`：独立音频、配音或音效参考。
- `documents/`：文案、PDF、网页存档和其他资料。
- `material-index.json`：本 Job 的唯一素材索引。

导入只复制；不得移动、改写或删除用户原文件。记录原始名称、媒体类别、Job 内相对路径、字节数、SHA-256 和素材 ID。相同哈希只保存一份资产，但保留每个来源记录。路径必须解析在当前 Job 内，软链接不记为稳定输入。

## 内联文案与初始化恢复

文案文件、`--script-text`、`--script-stdin` 三选一。聊天文案可直接调用：

```python
job, context = initialize_video_job(
    jobs_root, title, video_path,
    script_text=full_script_text, project_root=project_root,
)
```

不要求先创建 Job 或手工临时文案文件。初始化器在尚未发布的 workspace 内保存 UTF-8 原文（不删首尾空格、不改换行），以 `inline-script.md` 记入素材索引；内容哈希相同则复用已有资产并保留来源记录。长文案走 stdin；宿主用参数数组与输入流传值，不将文案插入 shell 命令，以免引号或 `$` 被解释。

复制完成后校验导入文件 SHA-256。资料索引和 `initialization.json` 一同发布，后者绑定原始输入、素材索引哈希、Python/运行时/Skill 身份及 workspace 路径。只有 workflow 和全部目录就绪后才原子写入 `job-context.json`，最后将初始化状态标记为 `ready`。

若已经返回或错误中列出了 workspace 路径，后续初始化失败时只执行：

```bash
python3 <skill>/scripts/initialize_video_job.py \
  --resume-workspace <absolute-workspace>
```

可以显式附加原项目的 `--project-root`，不得同时传新视频、文案、标题或资料。使用原 Python；恢复不会自动重新签署 runtime/release 身份，不运行预检、生成、渲染或批准阶段。成功返回原 context，继续正常预检或最早未完成阶段，不重复已批准工作。

- workflow 尚未创建：校验已导入资料后在原 workspace 创建；不再访问原件路径。
- workflow 已提交、context 尚未写入：加载原 workflow，保留 revision 和阶段状态，仅补完整目录与 context。
- context 已提交、`ready` 标记写入失败：比对原 context，不覆盖，仅完成标记。
- 已 `ready`：只能加载既有 workflow；丢失/冲突 context 或 workflow 时停止，不重建已批准身份。
- 空的未提交 workflow 目录：只移除这个确定为空的目录后重建。非空事务残留、损坏记录、软链接、身份变更均保留并停止，交给对应状态引擎恢复/明确迁移。
- 导入尚未原子发布时普通异常会清理本次未发布目录；强制杀进程留下的 `.building` 目录不是可恢复 Job。不得据此自动批准、合并到其他 Job 或覆盖现有资料。

恢复使用 POSIX 文件锁（当前 macOS/Linux 运行时），并发恢复会明确拒绝；锁随进程退出释放，不要求删除锁文件。旧 Job 没有 `initialization.json` 时不得事后伪造，仍按原状态与明确迁移流程处理。恢复记录只用于初始化，不替代 workflow，也不是资料变更入口。

## 索引与复用

`material-index.json` 是唯一素材索引。`content_analysis` 可以在同一索引中追加实体、人物、组织、主题、事实、时间段、视觉用途和审核状态；下游不得重新扫描全部用户资料或另建冲突索引。

新补资料采用追加导入：先哈希去重，再增加 material 记录。已存在且哈希一致的资产直接复用，不重新复制、转码或生成。

## 索引与同级语义候选

```broll-source-policy
- `local_material`
- `official_material`
- `code_generated`
- `external_stock`
- `ai_generated`
kind_priority: none
selection_mode: none | single | hybrid
semantic_role_source_separation: required
quota: none
cross_kind_replacement: forbidden
```

`material-index.json` 负责本地资料记录，但不设置来源排名。每段先确定 `semantic_role`，再对五类同级候选按语义匹配、内容真实性、原生 9:16、可读性、媒体质量和来源记录评估。然后选择 `none`、`single` 或 `hybrid`。

- `local_material` 绑定 `material_id`、Job 内路径与 SHA-256。
- `official_material` 绑定 publisher、URL、本地 snapshot、获取时间与 SHA-256。
- `code_generated` 绑定依赖 Skill 的 `dependency_id`、`entrypoint`、`producer_version` 与 `invocation_record`。
- `external_stock` 绑定 provider 素材 ID、作者、素材页、Job 内文件、许可记录与 SHA-256。
- `ai_generated` 绑定 provider、精确模型、endpoint、prompt 哈希、generation ID 和媒体 SHA-256。

未选候选记录中性原因，例如语义不匹配、内容记录不完整、质量不足、尺寸不合适或邻近镜头重复。这些记录不改变五类同级关系，也不触发跨类替换。

## 已有参考字幕的只读检索

检索参考视频时先读取本 Job 的 `00-user-provided/material-index.json`。已有字幕必须作为独立资料导入，取得视频与字幕各自的 active `material_id`；用明确的用户关联或可核对的来源记录确定二者关系，不能按同名、目录顺序或语言猜配。关联不明确时只询问缺失的关联，不重问已批准内容重点。

在权威 `job_dir/manifests/` 下保存本次轨道选择文件，例如 `reference-tracks.json`。该文件只是检索输入，不是素材索引或人工批准记录，精确格式为：

```json
{"tracks":[{"language":"en","material_id":"<字幕素材ID>","format":"srt"}]}
```

每项只允许 `language`、`material_id`、`format` 三个非空字符串，format 为 `srt` 或 `vtt`。language 要与实际字幕一致；指定语言必须唯一匹配，`zh` 不自动匹配 `zh-CN`。选择文件上限 64 KiB，字幕上限 16 MiB。普通 WebVTT 支持 cue identifier/settings，但时间映射及 STYLE/REGION 块不支持，不能删掉未知块后假装已正确解释原时间轴。

```bash
PYTHONPATH="<project>" <python> -m edit.hd.tools.cli search-reference \
  --workspace "<workspace>" --material-id "<视频素材ID>" \
  --tracks "<job-dir>/manifests/reference-tracks.json" \
  --language en --query "<待定位的原文短语>"
```

这是只读字面检索，不执行 ASR、上传、下载、修改索引或审批。输出 `material` 与 `caption_material` 保留两份来源身份，`matches` 保留不同时间出现的相同文本，`start/end` 是参考字幕自身的源秒数，不是口播成片时码。`precision=segment` 不代表逐词对齐；`precise_cut_eligible=false`，选用前需看片核对，不能直接当成精确剪点。

`source_approval=not_asserted` 表示没有自动认证官方身份或字幕与视频的对应关系；官方来源和引文支持关系仍在既有素材审核中核对。没有匹配时如实报告，不能编造时码；语言缺失／重复、素材撤回、文件变化或 exit 2 时停止并报告，不换语言、换素材或直接读旧结果绕过。

`--workspace` 模式只支持已导入的本地字幕；无字幕时使用下方已批准 Job 的本地转写流程。`search-reference` 始终不保存缓存、不执行识别，也不取代正式素材使用回执。

### 保存参考字幕报告

本次环境预检及配置已经批准后，需要保留解析结果时调用：

```bash
PYTHONPATH="<project>" <python> -m edit.hd.tools.cli cache-reference \
  --job "<job-dir>" --material-id "<视频素材ID>" \
  --tracks "<job-dir>/manifests/reference-tracks.json" --language en
```

`--job` 是 `job-context.json` 指向的权威 `job_dir`，不是 workspace。输出为 `path` 与 `sha256`；报告保存在 `job_dir/cache/reference-transcripts/<视频素材ID>/<报告SHA256>.json`。它保存完整字幕报告，不是某一次查询的 matches；相同标题不合并不同素材ID。

下次保留同一字幕结果仍调用相同命令：入口重新加载 Job、检查启动批准、核对两份当前 active 素材及字幕字节，内容相同才复用原文件，不重新覆盖。字幕、语言或素材身份变化会产生不同内容身份；旧文件保留但不能代替当前核验。没有绕过源资料的离线入口；不能把缓存路径直接当作已批准来源或精确剪点。

启动未批准、素材撤回、软链接、已有缓存内容与其哈希命名不符或 exit 2 时停止并报告。不要删除冲突缓存再重试，不手改审批、索引或哈希，不因文件存在就跳过检查。有字幕的分支不转写；两种分支均不上传、不推进 workflow，也不补造素材使用回执。

### 无字幕参考视频的本地转写与检索

仅在没有可用字幕、素材为当前 active 音频或视频，且本 Job 的 `reference_asr` 已通过预检与配置确认时使用。配置格式见 [依赖预检合同](dependency-preflight.md)。当前支持本地 `whisper.cpp`，禁止上传；环境变量只是程序/模型位置，不是授权。沿用本次已批准配置，不新增人工门，不重审已批准文案重点。

无字幕时轨道选择文件明确写为 `{"tracks":[]}`，不要伪造字幕 ID。先执行上面的 `cache-reference --job ... --language en`：空 tracks 才进入本地 ASR；非空 tracks 即使损坏或语言不匹配也只报错，不能静默回退识别。语言为明确的 2–3 位小写代码，实际支持由所选模型决定，不自动检测或翻译。

首次成功保存报告及 request 指针，后续相同素材、语言、配置和运行时身份复用缓存，不重复识别。源文件、模型、程序和批准状态在调用前后重新核验；身份变化不能沿用旧结果。报告上限 16 MiB，失败不发布成功指针，可能保留尚未被指针引用的报告；不手工把它提升为可用缓存。

定位已有转写使用同一个检索命令的 Job 模式：

```bash
PYTHONPATH="<project>" <python> -m edit.hd.tools.cli search-reference \
  --job "<job-dir>" --material-id "<视频素材ID>" \
  --tracks "<job-dir>/manifests/reference-tracks.json" \
  --language en --query "Hello"
```

`--job` 与 `--workspace` 二选一。空 tracks 的 Job 检索只读现有 ASR 缓存；缺缓存时停止并说明需先转写，不隐式运行 `cache-reference`。非空 tracks 的 Job 检索读取当前字幕。每次仍核验当前资料与批准运行时，因此不是脱离源资料的离线搜索。

ASR 报告含 `method=local_whisper_cpp`、模型和素材身份、`raw_output_sha256`、`precision=word`；raw SHA 是识别输出摘要，不是保留的原始输出文件或来源认证。命中的 `start/end` 仍是参考资料源秒数，`precise_cut_eligible=false`。当前按单条 cue 做大小写不敏感字面匹配，不跨词条拼接短语、不做语义搜索；未命中不能推断原视频没有该内容。仍须试听和核对官方出处，再决定引用或剪点。

## 变更与精准失效

新 Job 的十二个阶段都发布权威 `material-usage.json`；该回执以 `material_id` 和 SHA-256，以及 `consumer_id + binding_path + artifact_paths` 证明使用范围，无引用的阶段也发布完整空声明。依据当前 revision 的回执与项目运行时 DAG，系统计算最早修订阶段、受影响 segment、需重建产物和可复用产物。

已使用资料的替换/撤回已支持确认后的精准修订：媒体重建只失效引用该资产的 visual segment，`artifact_scope` 保留受影响视觉 segment，支持 `segment-inputs` 的运行时复用其他已批准媒体字节。状态引擎仍会将最早修订阶段及其下游阶段进入重审；精准媒体复用不等于自动保留下游人工批准。旧 Job 缺回执时 fail closed，旧 Job 不补造回执。完整规则见 [权威素材使用回执与变更事务](material-usage-contract.md)。

### 唯一资料变更入口

使用 `scripts/manage_user_materials.py`；不要把修改后的原路径覆盖到已导入文件，也不要直接编辑 `status` 或哈希。

```bash
python3 <skill>/scripts/manage_user_materials.py --workspace <workspace> \
  plan append --operation-id add-stanford-video-01 --source <absolute-video>

python3 <skill>/scripts/manage_user_materials.py --workspace <workspace> \
  plan replace --operation-id replace-portrait-01 \
  --material-id <existing-material-id> --source <absolute-image>

python3 <skill>/scripts/manage_user_materials.py --workspace <workspace> \
  plan withdraw --operation-id withdraw-photo-01 --material-id <existing-material-id>
```

计划 JSON 返回 `plan_hash`、索引/工作流/新素材哈希、`direct_references`、`affected_stages`、`earliest_stage`、`artifact_scope`、`reused_artifacts`、`rebuild_artifacts`、`required_human_gates`、`unverified_stages` 和 `blockers`。计划不复制文件、不改 workflow、不增加 revision。回执缺失、生产者未知、revision 或哈希不符时不从目录推断“未使用”，而是返回 `material_usage_unverified` 阻断项。

由宿主将完整计划 JSON 原样保存在权威 `job_dir/manifests/` 下，展示受影响范围；只执行用户已经明确要求的追加/替换/撤回，不为此重复封面、重点词或配置确认。随后执行：

```bash
python3 <skill>/scripts/manage_user_materials.py --workspace <workspace> \
  apply --plan <absolute-plan-json> \
  --confirmed-plan-hash <the-exact-human-approved-plan-hash>
```

也可从当前解释器通过项目桥接或唯一 Skill 导入：`plan_material_change(workspace, operation, operation_id=..., source=..., material_id=...)` 返回完整计划，`apply_material_change(workspace, plan, confirmed_plan_hash=...)` 执行；`append` 不传 `material_id`，`withdraw` 不传 `source`。

### 哪些变更现在可以执行

- **追加：** 可随时导入为新的候选资料。相同 SHA-256 复用资产文件，每个来源有独立 material ID；不自动选入画面，不重新下载/转码，不重置任何阶段。即使已有封面或样片，也继续保留。
- **尚未使用的替换/撤回：** 在确认计划后直接更新索引，`workflow_action=preserve`。原口播和文案的输入哈希受保护，不能从此入口替换或撤回。
- **已有引用：** 展示所有直接 consumer、最早修订阶段、受影响镜头和下游重审范围。用户确认精确 `plan_hash` 后，`workflow_action=revise`，事务提交索引并调用一次 `state.revise`。未变镜头媒体可依视觉修订复用合同继续复用，但受影响及下游阶段仍须重审。
- **覆盖不完整：** 旧 Job 或当前回执不可验证时返回 `material_usage_unverified` 并在任何写入前停止。展示未核清阶段，由人工选择更早修订点；不补造回执或自动新建任务绕过。
- **已撤回/已替换的 ID：** 后续封面读取及 Skill 管理任务的本地 B-roll 解析会拒绝，即使旧复制文件仍在。新绑定必须选择新的 active ID；历史裸运行时不自动迁移，不将该 gate 外推为所有旧任务都有完整引用验证。

### revision、失败与恢复

资料索引使用独立的 `material_revision`，每次成功提交递增，`changes` 中同时保存操作 ID、计划 ID 和结果。无已使用产物的变化不改 `workflow_revision`，不重新批准已有阶段；替换保留原记录和 SHA，将它标为 `superseded` 并写 `replaced_by`，新增记录不照搬旧资料的语义注释。撤回仅标为 `withdrawn`，不删除原件或导入字节。其他记录上的实体、主题等注释原样保留。

同一操作重试必须复用原完整计划和 `operation_id`。如果索引已提交，即使原件移走，也返回已提交结果，不多复制一份、不增加 revision。新请求使用新操作 ID；计划对应的索引、workflow、新素材或现有草稿改变时，旧计划停止，重新读取影响后再处理。

新资产先流式复制并验证，再独占发布，最后原子提交索引及回执。事务固定为 `prepared` → `material_committed` → `workflow_revised`。索引提交前失败不发布 material 记录；可能保留已校验的未索引资产，原计划重试只复用匹配的字节，不覆盖冲突文件。索引提交后报错通过事务回执继续同一 `operation_id`；成功重放不重复 `state.revise`。强制杀进程留下的 `.importing` 文件不自动当成完整素材，也不批量删除。

资料操作使用 POSIX 文件锁，互斥其他资料变更。**操作期间暂停同一 Job 的 runner 和索引注释写入**；旧 runner 不使用这个锁，不声称存在跨索引/工作流的数据库事务。入口在复制前后复核身份，不能靠并发运行来验证或绕过批准。旧 Job 缺初始化记录或 runtime/release 身份变化时停止，不自动迁移、重签或刷新发布清单。
