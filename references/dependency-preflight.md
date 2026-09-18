# 依赖预检、确认与安装合同

每个新视频 Job 都要运行本合同，检查运行时、项目 runner、必需 Skill、参考项目，以及由 `visual_direction` 草案或已冻结配方触发的能力。预检只读取当前状态；安装、插件变更、账号连接和 provider 调用仍按既有人工确认门执行。

**目录存在不等于能力可执行。** 报告统一记录以下字段：

- `selected`：静态必需项，或被本 Job 明确配置、当前 `visual_direction` 草案 / 已冻结 ShotRecipe v2 选中的条件项。
- `configured`：存在配置，但不代表账号已认证。非空 API key 只能到此级别；`false/0/no/off` 不算已配置。
- `connected`：宿主明确声明连接已验证，记录 `connection_evidence=host_declaration`；不是预检脚本自行完成的联网认证。首次请求前仍需真实连接证据，不得为了通过检查将环境变量设为 true。
- `callable`：命令版本检查、实际模块/API 导入或登记的执行探针成功。只存在 `SKILL.md`/入口文件记为发现，不升级为可调用；也不代表完整渲染成功。
- `bound`：binding probe 返回的 `dependency_id / entrypoint / producer_version / adapter_identity` 与批准配方及 manifest 逐字一致。
- `entrypoint` / `version`：来自当前批准代码组件，并由 probe 对实际入口和依赖版本复核；命令依赖则来自本机版本检查。

五类 B-roll 来源仍按语义平等选择。预检只判断所选能力能否执行，不建立来源优先级，也不把 external stock 或 AI 当成其他来源的替补。

## 1. 唯一清单与两次检查

在新建 Job 前先运行 `scripts/verify_skill_release.py`；包身份与附件缺失是发布问题，不得误报为用户的第三方插件缺失。初始化入口已强制执行此检查，恢复旧 Job 时也要核对 `job-context.json` 中的 release 身份。详见 [发布与调用合同](release-contract.md)。

静态事实源是 `references/dependency-manifest.json`，不得在聊天中维护第二份列表。初始化后先写 `manifests/provider-config.json` 草稿，再用选定的同一个 Python 预检。下文 `<python>`、`<workspace>`、`<job>` 分别是解释器绝对路径、初始化返回的 workspace 和 job_dir：

```bash
<python> <skill>/scripts/dependency_preflight.py \
  --manifest <skill>/references/dependency-manifest.json \
  --project-root <full-v2-project-root> \
  --reference-root <project>/参考项目/B-roll开源方案 \
  --job-context <workspace>/job-context.json \
  --output <job>/manifests/dependency-preflight.json
```

`visual_direction` 批准后，直接读取正式 schema-v3 `visual-plan.json`。预检先调用项目正式 `validate_visual_plan`，再逐段调用 `validate_shot_recipe_v2`；完整合同通过后才从 `segments[*].shot_recipe` 提取绑定：

```bash
<python> <skill>/scripts/dependency_preflight.py \
  --manifest <skill>/references/dependency-manifest.json \
  --project-root <full-v2-project-root> \
  --reference-root <project>/参考项目/B-roll开源方案 \
  --visual-plan <job>/07-visual-direction/visual-plan.json \
  --job-context <workspace>/job-context.json \
  --output <job>/manifests/dependency-preflight.json
```

缺字段、identity 不一致、非法 component、旧视觉 Job 或旧配方都会返回明确停止状态。只支持 VisualPlan schema v3 与 ShotRecipe v2，不兼容旧 visual Job。未选 `code_generated` 时，Node.js、npm、html-video、hyperframes、`hd-talking-head-local-canonical` 与 video-shotcraft 保持可选；未选 `external_stock` 时，Pexels 与 Pixabay 连接保持可选。选中后，条件项立即按 manifest 的 `required_level` 计入必需项。

报告还保存 `job_id + workspace`、配置哈希、实际 `sys.executable`、运行时模块哈希及合成器版本。未带 `--job-context` 的报告只用于环境诊断，不能解锁生产。项目 API 用同一解释器的新进程实际导入，保留该解释器可见的依赖；不使用另一个 PATH Python 或跨项目模块缓存。

`preview-runner` 同时要求 `prepare_preview_v2`、`validate_preview_opening` 与 `validate_preview_music` 可调用，以拒绝缺少正式封面或音乐校验的旧实现。配乐输入在预览前另验双声道、解码长度、音乐与许可索引身份；可调用不等于已混音或已试听，不允许为旧 Job 自动重签运行时身份。缺少运行时代码时按 [运行时部署](runtime-deployment.md) 处理；导入通过后仍执行本合同，不将导出包当成已安装的媒体工具。

退出码 `0` 表示全部当前必需项满足；`2` 表示当前必需项缺失；`3` 表示清单、ShotRecipe 或检查输入无效。未被配方选中的可选项可以形成 `ready_with_optional_gaps`，但不阻塞 Job。

## 2. Job 内复用

每个新 Job 都重新运行预检，因为项目根目录、工具版本、Skill、插件连接和 provider 配置可能变化。当前 Job 内满足以下条件时可复用报告：

- 报告在最近 24 小时内，manifest SHA-256、项目根目录、真实运行时和报告中的 `visual_plan.path/sha256` 不变。
- 已解析命令、路径、入口、probe identity 和实际依赖版本仍一致。
- provider、模型及账号连接选择未变化。

当前脚本刷新整个轻量报告，串行执行，不重复下载或生成，不手工拼接新旧报告。已知安装/路径/连接变化时立即刷新，不等 24 小时；这个上限不是持续监控账号的保证。配置不变不重复确认；配置改变需重新预检并确认。运行时或 Skill 版本变化属于显式迁移，不能只改哈希解除阻断。同 Job 同缺失集合只询问一次安装授权，写入 `manifests/dependency-install-approval.json`；新 Job 不继承旧授权。

### 配置文件与批准入口

仅本地测试、无需图片/视频生成时可使用以下完整配置；不能套在用户要求生成媒体的任务上：

```json
{"schema_version":1,"providers":[],"max_concurrency":1,"generation_enabled":false}
```

启用生成时 `generation_enabled=true`，`providers` 中每项只能包含如下字段（示例标识必须替换为实际值）：

```json
{"purpose":"image","provider":"<provider-id>","model":"<exact-model-id>","endpoint_id":"<non-secret-connection-id>","connection_status":"verified","reference_images":true,"native_9_16":true,"silent_output":true,"quota_status":"unknown"}
```

`purpose` 为 `image/video/stock`，每类最多一项；`connection_status` 为 `verified/unavailable/not_required`；`quota_status` 为 `available/unknown/unavailable`。能力字段为布尔值，不支持就写 false。endpoint 只存标识，不存密钥、token 或带凭据 URL。`verified` 须有宿主证据，不由密钥存在推断。配置批准不跳过请求时的 provider 检查。

需要对无字幕参考视频做本地语音识别时，使用 schema 2，在原配置中增加 `reference_asr`。完整的仅本地配置示例：

```json
{"schema_version":2,"providers":[],"max_concurrency":1,"generation_enabled":false,"reference_asr":{"provider":"whisper.cpp","model":"ggml-large-v3-turbo","execution":"local","upload_policy":"forbidden"}}
```

`model` 是精确模型标识，不是路径，也不带 `.bin`；本机模型文件名必须为该标识加 `.bin`。`reference_asr: null` 表示不启用，schema 1 保持不启用。现有生成 provider 配置原样保留，不因为选择本地转写而关闭用户已选的生图或生视频能力。

只有非 null 的明确选择才使清单中的 `reference-asr` 成为启动必需项。预检使用同一 Python 的独立进程运行所选项目的检查入口，固定并记录本地程序、模型文件的 SHA-256 与大小；只执行程序快照的 `--help`，不加载模型、不读取用户媒体、不转写、不上传。报告中 `model_load_verified=false` 表示尚未验证模型加载或识别质量，`callable` 不能当作实际转写成功。

环境变量或已下载的模型不能代替本次选择和配置确认。缺程序、缺模型或探针失败时停止，不自动换模型、语言或服务。配置变化后重新预检并通过下述同一个确认入口，不增加第二个确认门。真正转写前仍需复核程序、模型、源素材身份并取得实际执行回执；预检报告不能替代它，也不能通过直接调用底层转写绕过正式流程。

展示一次配置摘要并得到真实用户回复后：

```bash
<python> <skill>/scripts/confirm_job_setup.py \
  --job-context <workspace>/job-context.json \
  --user-confirmation "<本次用户确认原文>"
```

入口写入固定 `manifests/setup-approval.json`，绑定 Job、配置、运行时和 Skill 身份。同 Job 同配置重复调用不修改既有批准。`state.require_runnable` 实际阻断缺报告、缺批准、跨 Job、过期、配置变化和必需结果缺失。不要手工写批准文件，不把机器 PASS 当用户确认。

## 3. 一次确认门

预检后向用户展示：

1. 已满足的必需项数量，以及达到 `callable` / `bound` 的数量。
2. 缺失的必需项及其影响阶段。
3. 未被当前配方选择的可选能力。
4. 每个安装动作的准确方法、包名、来源和目标目录。
5. 需要人工完成的账号连接、订阅或付费步骤。

路径存在但入口缺失、入口或版本未登记、probe 无法执行、probe identity 不一致、smoke 失败或非代码阶段未绑定时，要显示准确状态，不能计为满足。已有目录不自动覆盖、删除或重新 clone；先报告修正动作并等待授权。

没有缺失项时展示并确认当前配置草稿。存在缺失项时，只问一次是否执行安装计划；批准后按组安装并重新预检。用户拒绝必需项时在对应阶段前标记 `blocked`；拒绝未选可选项则记录并继续。

## 4. 安装方式与边界

| `method` | 执行方式 | 约束 |
| --- | --- | --- |
| `system-package` | 使用当前系统包管理器安装准确 package；同一 `group` 只安装一次 | 先展示准确命令；批准后运行；不自行使用 `sudo`、改 shell 配置或换包 |
| `python-package` | 使用本 Job 已选 Python 环境的 `python -m pip` 安装登记 package | 本 Job 授权后执行；不改全局解释器或自动更换 Python 环境 |
| `skill-installer` | 使用当前 Agent 环境的 Skill 安装能力，从登记 source 安装 | 只安装报告中的 Skill；安装后验证 `SKILL.md` 可发现 |
| `git-clone` | 将登记 source 克隆到准确 destination | 只处理缺失目录；目标已存在但不合格时报告冲突，不覆盖、删除或 reset |
| `plugin` | 使用当前平台插件管理器安装用户已选插件 | 先取得本 Job 明确批准；账号与连接步骤由用户完成 |

安装失败后停止该安装组，保留命令、退出码和简要错误信息；不自动换镜像、换包、换插件或重试。修正后只复检受影响依赖。

## 5. 条件依赖

- `code_generated` 调用现有依赖 Skill。绑定 `html-video`、`hyperframes`、`hd-talking-head-local-canonical` 或 `video-shotcraft` 时，对应 adapter 必须 `selected + callable + bound`；manifest 精确登记 entrypoint、producer version、adapter identity 和可执行 probe。`hyperframes` 分别登记 Notification Cascade 与 ChatGPT Exchange 两个包装器；`hd-talking-head-local-canonical` 登记本 Skill 的共享 renderer 入口。预检按已冻结 entrypoint 只匹配对应 probe，并同时检查固定 HyperFrames 提交、`@hyperframes/cli` 版本、渲染入口与包装器，不能只凭目录存在通过。
- `code_generated` 绑定 `video-shotcraft` 时，Skill 必须可发现；manifest 精确登记 entrypoint、producer version、`SkillInvocationAdapter` identity 和可执行 probe。执行后 ShotRecipe v2 的 `invocation_record` 保留 Skill 调用证据。
- `external_stock` 草案选中 `pexels` 或 `pixabay`：对应 provider 必须在首次搜索前 `selected + connected`。该状态可来自 Job 启动时的连接摘要，但请求前必须重新复核。
- `ai_generated` 草案选中具体 provider 后：在首次生成前，按精确模型 ID、参考图支持、9:16、无声输出、并发与额度状态做当前 Job 确认。素材冻结后再用完整 ShotRecipe v2 复核 binding。
- `official_material`：需要浏览器或来源连接器时，在首次获取前确认可用状态。
- `official-video-acquisition` 只在仍需获取时成为必需项。带 Job 上下文的预检核对已冻结视频的 Job 内普通文件路径、publisher/URL、SHA-256 与 FFprobe 视频流/有限正时长；有效时记录 `local_official_media`，不要求下载器。文件缺失恢复获取依赖，字节变化或探测失败明确停止，不能偷偷换素材。探测不是全片解码或事实核验，正式使用仍需来源核实及当前区间 QA。

条件依赖不触发跨类改写。某个已选来源暂时不能执行时，保持原配方并给出 `retry_same_strategy` 或返回 `visual_direction` 重新批准；不静默换成另一类来源。

## 6. 显式停止条件

- 当前必需 runner、运行时、Skill、入口、binding probe、非代码阶段绑定或 provider 连接缺失：在首次使用前标记 `blocked`，返回准确状态。
- 安装完成后必须重新预检；只有达到 manifest 声明的 `required_level` 才计为满足。
- 预检、安装和连接检查不调用图片或视频生成，不增加 generation 次数，也不消耗 provider 额度。
- 不因当前机器已经存在目录而省略检查；代码入口、实际版本和 adapter identity 必须由可执行 probe 一次返回并逐字核对，不能从源码字符串推断。
