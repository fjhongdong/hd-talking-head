# 依赖预检、确认与安装合同

每个新视频 Job 都要运行本合同，提前检查全流程运行时、项目 runner、必需 Skill、参考项目，以及由 `visual_direction` 草案或已冻结配方触发的能力。预检本身只读取当前状态。按用户要求，本地缺失环境在正式阶段前安装，不反复请求同一普通安装许可；不改第三方源码、全局 Skill 或 shell 配置。账号连接、密钥、订阅、付费媒体请求和冲突目录覆盖仍不在自动安装范围内。

**目录存在不等于能力可执行。** 报告统一记录以下字段：

- `selected`：静态必需项，或被本 Job 明确配置、当前 `visual_direction` 草案 / 已冻结 ShotRecipe v2 选中的条件项。
- `configured`：存在配置，但不代表账号已认证。非空 API key 只能到此级别；`false/0/no/off` 不算已配置。
- `connected`：宿主明确声明连接已验证，记录 `connection_evidence=host_declaration`；不是预检脚本自行完成的联网认证。首次请求前仍需真实连接证据，不得为了通过检查将环境变量设为 true。
- `callable`：命令版本检查、实际模块/API 导入或登记的执行探针成功。只存在 `SKILL.md`/入口文件记为发现，不升级为可调用；也不代表完整渲染成功。
- `bound`：binding probe 返回的 `dependency_id / entrypoint / producer_version / adapter_identity` 与批准配方及 manifest 逐字一致。
- `entrypoint` / `version`：来自当前批准代码组件，并由 probe 对实际入口和依赖版本复核；命令依赖则来自本机版本检查。

五类 B-roll 来源仍按语义平等选择。预检只判断所选能力能否执行，不建立来源优先级，也不把 external stock 或 AI 当成其他来源的替补。

### 语音服务的有效凭据

首次转写前，在本 Job 已绑定的 `video-use` 入口、实际工作目录和子进程环境中调用其只读 `load_api_key()`，只检查是否返回非空值，不输出或持久化密钥。`--help`、目录存在和运行时绑定通过不能证明 Scribe 凭据就绪；此检查也只证明本地配置可读，服务可用性仍以本次获准请求的真实响应为准。
完整 Skill 包不包含私有 `.env`。机器已有获准使用的私有凭据时，可安全注入这一次子进程环境；程序入口仍用本 Job 绑定的包内 helper，不改用全局 Skill 运行时，也不把密钥复制进包、Job、参数或日志。凭据加载在上传前失败时，保留失败记录并说明尚未提交，不误记为已消耗转写次数；修正有效环境后继续原有一次授权，不重新请求同一许可。

凭据探测和已授权转写必须沿用本 Job 的已准备 Python，通过 `project_python.py --project-root <project> -- <绑定 helper 或只读导入命令>` 执行。探测只导入预检绑定的 helper 并调用 `load_api_key()`，不运行转写 CLI。不得为探测改用 PATH 中另一个 Python、`uv run`、`uv sync` 或 `pip install`；这些命令可能安装依赖、生成锁文件或改写来源目录。若已准备解释器确实缺模块，退回唯一准备入口处理，不在凭据环节补装。

首次读取为空时，先核对当前子进程的工作目录和环境，再检查宿主已知、获准使用的 `video-use` 私有配置。宿主已安装 Skill 的 `.env` 可以仅作为已有密钥来源；只读取所需字段并注入同一子进程环境，不执行该全局 Skill，也不将密钥写入参数、包或 Job。重新调用同一个包内 helper 的只读检查，通过后才消耗本期尚未使用的转写授权；未检查这些已知来源前，不宣称整机缺少凭据。

若探测误触发安装，立即暂停阶段并保留原因，只清理能够确定由本次操作新增且不被引用的来源目录文件。先验证原发布包恢复，再按维护合同更新父级规则；不得把误生成的锁文件或构建产物加入发布清单来放行。

## 1. 唯一清单与两次检查

新建 Job 前只调用下述唯一准备入口；它先校验发布包，再调用项目内已有准备与检查。包身份与附件缺失是发布问题，不得通过安装或重签清单掩盖。初始化入口仍独立校验发布身份；恢复旧 Job 时也要核对 `job-context.json` 中的 release 身份。详见 [发布与调用合同](release-contract.md)。

静态事实源是 `references/dependency-manifest.json`，不得在聊天中维护第二份列表。初始化后先写 `manifests/provider-config.json` 草稿，再用选定的同一个 Python 预检。下文 `<python>`、`<workspace>`、`<job>` 分别是解释器绝对路径、初始化返回的 workspace 和 job_dir：

需要单独准备已选能力时，使用 `python3.12 <project>/run.py prepare --dependency-id <实际依赖ID>`，可重复参数。未知 ID 会报错；该命令不调用生成服务。正常制作由 `run_stage visual_direction` 自动完成这一步，不需要用户操作或再次确认。

### 包内来源与更新

当前完整包随附固定版本的子 Skill、模板源码和来源归档。首次准备只恢复包内原 Git 身份并安装环境依赖，不依赖原项目、全局 Skill 或再次克隆源码。源码缺失属于发布不完整，停止并报告缺失文件。

需要升级某项能力时，由维护者更新包内来源、检查受影响接法并发布新版本。同一 Job 的已冻结来源、媒体和确认记录不被环境准备覆盖；路径或发布身份变化仍按正式迁移入口处理。准备不调用付费图片或视频生成。

### 正式 Python 环境入口

新建 Job 前执行，不依赖尚未创建的 Job：

```bash
<python> <skill>/scripts/project_python.py --project-root <project> --prepare
```

它从唯一清单实际导入全部必需 `python_module` 项：Pillow（`PIL`）、requests、NumPy、OpenCV（`cv2`）。缺包才用同一 Python 的 pip 按清单版本安装到项目内 `skill-development/runtime/talking-head-python<major><minor>`；已可用分发版本作为约束保留，不主动升级。OpenCV 只缺失时安装 headless 分发，不与已有可用 GUI 分发混装。已安装但导入失败时停止，不用重装掩盖问题；安装后实际导入一次，不自动重试。准备按项目本地锁串行执行，有超时和失败记录。

基础准备只执行清单 `preparation` 中未声明 `dependency_ids` 的必需项。模板选定后，`run_stage.py` 从实际组件 bindings 提取 dependency_id，在发布确认列表前调用同一准备入口；`preparation.dependency_ids` 选择相应准备动作，`runtime_checks` 仅检查本次所选能力和实际入口版本。未选模板不安装、不探测。探针结果在准备报告里只记 `callable`，不伪造当前镜头 `bound`。账号、收费生成、未接入研究库不进入准备列表。没有自动准备入口的缺失环境停止并列出准确缺口，不临时创建安装器。

白板原生适配仅在本 Job 选中 `whiteboard-video` 后准备。入口为 `scripts/whiteboard_adapter.py --project-root <project> --prepare`；它在包内引擎目录创建一次 Python 3.12 `.venv`，安装项目合同冻结的 Pillow 12.3.0、NumPy 2.5.3、pydantic 2.13.5 与本地 editable `whiteboard-video-engine`，随后用原生 `render_whiteboard.py` 的严格源码、模块路径、解释器前缀和版本探针核验。已有环境不覆盖、不升级；缺失 Python 3.12、环境不符或安装失败即停止，不自动重试。上述精确版本是本项目已验证运行时合同，不声称来自上游锁文件。

OpenFilm 只在本次选中后执行这两份清单的对应项：按 [原生创作合同](openfilm-motion-graphics.md)检查项目本地包、真实 motion-graphics 说明、手册、原生浏览器和工具版本；缺失时仅补项目内环境，不改全局。启动检查不打开 Studio 或素材生成服务；正式包装器使用公开 `openfilm/render` 导出，避免 CLI 的自动更新／下载／重试。它只是一种语义候选，准备成功不代表本句动作、美观或信息密度通过。

其登记探针实际加载公共渲染模块并启动、关闭一次原生浏览器，失败区分模块加载与浏览器启动，不以文件存在冒充运行成功。该探针不渲染素材，不在每段导出或每帧重复执行；独立合成检查仍通过统一 Python 入口加载现有项目依赖，不直接换解释器、重装包或重试渲染。

`preparation.node_tool` 登记原生入口指定的项目内工具版本。Hypit 使用源码声明的 `pnpm 10.33.0`，缺失时从 npm 官方 registry 安装到项目 `skill-development/runtime/pnpm-10.33.0`，不执行安装脚本、不改第三方锁文件或全局工具。统一入口仅给子进程传递该工具路径；已存在版本异常或不完整目录时停止，不覆盖。准备报告保存命令、退出码、超时或可安全提取的错误类型/版本要求，不保存任意原始输出或密钥；旧失败报告保留。

所有主流程 Python 入口，包括初始化、预检、配置确认、迁移和项目 runner，统一在上述入口后用 `-- <脚本及参数>` 执行。它沿用调用者的解释器和工作目录，传递项目、Skill scripts 和本地包路径；不从 PATH 换 Python、不改用户 shell。第三方专用准备进程清除 `PYTHONPATH/PYTHONHOME`。统一 `_check_binding_probe` 对 Huashu、OneTake 的注册路线重建仅含项目和 Skill scripts 的导入路径，移除 `PYTHONHOME`；准备检查和正式预检共用此边界，不改已验收适配器、原生版本锁或注册命令。公共组件执行器继续使用原有离线环境。完整预检仍检查系统命令、原生组件与第三方入口，准备通过不能替代 Job 绑定预检。

GBRO 半调纸拼贴的原始 Skill 是启动必需源码项：先用 `ensure_visual_broll_skills.py --project-root <project> --skill gbro-collage-broll` 检查固定提交，缺失时仅在项目 vendor 准备，再由清单核对原始说明和入口文件。这里的 `installed` 只证明来源已准备，不证明静帧或动态成片通过。图片与视频渠道不在本条固定；由本 Job 的 provider 预检及请求前检查确认，模板内部调用沿用同一渠道配置。

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/dependency_preflight.py \
  --manifest <skill>/references/dependency-manifest.json \
  --project-root <full-v2-project-root> \
  --reference-root <project>/参考项目/B-roll开源方案 \
  --job-context <workspace>/job-context.json \
  --output <job>/manifests/dependency-preflight.json --summary-only
```

`visual_direction` 批准后，直接读取正式 schema-v3 `visual-plan.json`。预检先调用项目正式 `validate_visual_plan`，再逐段调用 `validate_shot_recipe_v2`；完整合同通过后才从 `segments[*].shot_recipe` 提取绑定：

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/dependency_preflight.py \
  --manifest <skill>/references/dependency-manifest.json \
  --project-root <full-v2-project-root> \
  --reference-root <project>/参考项目/B-roll开源方案 \
  --visual-plan <job>/07-visual-direction/visual-plan.json \
  --job-context <workspace>/job-context.json \
  --output <job>/manifests/dependency-preflight.json --summary-only
```

缺字段、identity 不一致、非法 component、旧视觉 Job 或旧配方都会返回明确停止状态。冻结主计划只接受 VisualPlan schema v3 与 ShotRecipe v2，不兼容旧 visual Job；TalkCraft 工作台消费的派生 span-aware v4 计划不经本预检冻结。未选 `code_generated` 时，Node.js、npm、html-video、hyperframes 与 `hd-talking-head-local-canonical` 保持可选；未选 `external_stock` 时，Pexels 与 Pixabay 连接保持可选。选中后，条件项立即按 manifest 的 `required_level` 计入必需项。

报告还保存 `job_id + workspace`、配置哈希、实际 `sys.executable`、运行时模块哈希及合成器版本。未带 `--job-context` 的报告只用于环境诊断，不能解锁生产。项目 API 用同一解释器的新进程实际导入，保留该解释器可见的依赖；不使用另一个 PATH Python 或跨项目模块缓存。

`generation-coordinator` 必须实际导入项目内 `edit.hd.tools.generation_queue` 的八个登记接口（含 `prepare_retry` 与 `retry`）。只复制 Skill、缺少该项目入口时不能提交媒体生成；调用方法见 [有界生成编排](production-bindings.md#有界生成编排)。它只控制实际宿主工具的领取和回执，不内置另一套生成服务。

`preview-runner` 同时要求 `prepare_preview_v2`、`validate_preview_opening` 与 `validate_preview_music` 可调用，以拒绝缺少正式封面或音乐校验的旧实现。配乐输入在预览前另验双声道、解码长度、音乐与许可索引身份；可调用不等于已混音或已试听，不允许为旧 Job 自动重签运行时身份。缺少运行时代码时按 [运行时部署](runtime-deployment.md) 处理；导入通过后仍执行本合同，不将导出包当成已安装的媒体工具。

退出码 `0` 表示全部当前必需项满足；`2` 表示当前必需项缺失；`3` 表示清单、ShotRecipe 或检查输入无效。能力库检索读取包内已审核来源快照，不依赖可选运行环境先安装；实际选中后仍检查当前运行环境。未被配方选中的可选项可以形成 `ready_with_optional_gaps`，但不阻塞 Job。

`--summary-only` 只缩短终端输出，正式报告仍完整。报告给出缺失模块名与失败退出码，不保存任意原始 stderr 或密钥。刷新前，已有必需项失败报告原字节保存在输出目录的 `preflight-failures/`；不得为了覆盖报告另写临时 Python 包装、导入未登记 helper 或丢掉失败现场。

## 2. Job 内复用

每个新 Job 都重新运行预检，因为项目根目录、工具版本、Skill、插件连接和 provider 配置可能变化。当前 Job 内满足以下条件时可复用报告：

- 报告在最近 24 小时内，manifest SHA-256、项目根目录、真实运行时和报告中的 `visual_plan.path/sha256` 不变。
- 已解析命令、路径、入口、probe identity 和实际依赖版本仍一致。
- provider、模型及账号连接选择未变化。

当前脚本刷新整个轻量报告，串行执行，不重复下载或生成，不手工拼接新旧报告。已知安装/路径/连接变化时立即刷新，不等 24 小时；这个上限不是持续监控账号的保证。配置不变不重复确认；配置改变需重新预检并确认。运行时或 Skill 版本变化属于显式迁移，不能只改哈希解除阻断。普通项目内环境沿用本合同的提前安装要求；需要特殊授权的动作仍写入本 Job 的 `manifests/dependency-install-approval.json`，新 Job 不继承旧账号或付费授权。

### 配置文件与批准入口

仅本地测试、无需图片/视频生成时可使用以下完整配置；不能套在用户要求生成媒体的任务上：

```json
{"schema_version":1,"providers":[],"max_concurrency":1,"generation_enabled":false}
```

启用生成时 `generation_enabled=true`，新 Job 默认 `max_concurrency=2`，含义是本 Job 所有图片和视频生成共用的总名额；不是每个 provider 或子 Skill 各 2 个。运行时只接受 1 或 2，实际提交还须遵守账号当前能力和已批准次数；按各已选 provider 的真实额度入口核对当前 `concurrency_limit`，不能把上次账户上限当成当前空闲名额。旧 Job 不自动改配置或重签，修改配置须按原入口重新预检与确认。`providers` 中每项只能包含如下字段（示例标识必须替换为实际值）：

```json
{"purpose":"image","provider":"<provider-id>","model":"<exact-model-id>","endpoint_id":"<non-secret-connection-id>","connection_status":"verified","reference_images":true,"native_9_16":true,"silent_output":true,"quota_status":"unknown"}
```

`purpose` 为 `image/video/stock`，图片和视频各最多一项，可相同或不同；`connection_status` 为 `verified/unavailable/not_required`；`quota_status` 为 `available/unknown/unavailable`。能力字段为布尔值，不支持就写 false。endpoint 只存标识，不存密钥、token 或带凭据 URL。`verified` 须有宿主证据，不由密钥存在推断。配置批准不跳过请求时的 provider 检查。生成预检报告另保存 `generation_channels`，列出所选 provider、model、endpoint_id、连接状态和独立查询绑定。`probe_status=not_run` 表示没有发起真实生成；宿主须核对当前工具确实可调用后，才把配置写为 `verified`。本地 Python 只返回真实工具标识与参数，由宿主执行。异步渠道在下方完整配置的对应 purpose 中填写 `query`；同步渠道省略它。查询绑定与启动确认一起冻结，不把提交工具当查询工具。
`manifests/generation-channels.json` 中 `image`、`video` 等每个 purpose 都必须声明 `model_binding`：`{"mode":"argument","parameter":"model"}` 表示 `prepare` 补齐已选型号且参数不符时拒绝；`parameter` 可按实际接口填写 `model_id` 等顶级参数名；`{"mode":"fixed"}` 表示服务管理模型，不注入 `model`，并记录真实工具标识。参考输入必须声明 `reference_mode=local_path` 或 `upload`。`upload` 时必须有 `upload:{"tool":"<真实上传工具>","arguments":{"file":{"$input":"path"}},"result_path":["data","asset_id"]}`；宿主使用响应原始字段路径取得引用，回传原 action 与真实响应，后续提交请求才替换逻辑请求中的本地路径，并保留上传回执供续做复用。

下例同时启用图片与视频（图片工具固定模型、视频工具接收模型参数；工具、参数名及响应路径须按本次真实渠道填写）。也允许仅启用其中一种：`providers` 只列已选用途，`generation-channels.json` 只保留对应的完整模型、输入和查询绑定；不能把不可用用途留在列表后默认为已关闭。完全不生成时使用 `generation_enabled=false`。实际请求仍核对所需用途已选且可用，不自动补齐另一用途。生成工具与选定型号只来自 `provider-config.json` 的 `endpoint_id/model`，本文件不重复配置它们：

```json
{
  "schema_version": 1,
  "image": {
    "model_binding": {"mode": "fixed"},
    "reference_mode": "local_path"
  },
  "video": {
    "model_binding": {"mode": "argument", "parameter": "model"},
    "reference_mode": "upload",
    "upload": {
      "tool": "<真实上传工具>",
      "arguments": {"file": {"$input": "path"}},
      "result_path": ["data", "asset_id"]
    },
    "query": {"tool": "<真实查询工具>", "task_ids_parameter": "task_ids", "arguments": {}}
  }
}
```

需要对无字幕参考视频做本地语音识别时，使用 schema 2，在原配置中增加 `reference_asr`。完整的仅本地配置示例：

```json
{"schema_version":2,"providers":[],"max_concurrency":1,"generation_enabled":false,"reference_asr":{"provider":"whisper.cpp","model":"ggml-large-v3-turbo","execution":"local","upload_policy":"forbidden"}}
```

`model` 是精确模型标识，不是路径，也不带 `.bin`；本机模型文件名必须为该标识加 `.bin`。`reference_asr: null` 表示不启用，schema 1 保持不启用。现有生成 provider 配置原样保留，不因为选择本地转写而关闭用户已选的生图或生视频能力。

选中本地对照识别后，预检前先定位本机实际程序和对应模型；已存在模型不重复下载或复制。非默认位置必须同时显式传入 `HD_WHISPER_CLI=<程序的真实绝对路径>` 与 `HD_WHISPER_MODEL=<模型绝对路径>`；程序路径先解析符号链接，不能只传其中一项，也不能把配置中的模型名当作文件路径。两项均未设置时，发现器才检查 PATH 中的 `whisper-cli` 和当前用户的 `~/.cache/hd-talking-head/models/ggml-large-v3-turbo.bin`，不会扫描原开发项目或自动继承上期环境。

本期后续预检及实际本地识别子进程沿用这组显式路径，并与本 Job 预检中的 `reference_asr_probe.executable / model_file` 核对；不从旧 Job 复制探针或批准记录，不修改用户全局环境。即使用最外层 `run.py preflight`，也显式指定 `--output <当前job>/manifests/dependency-preflight.json` 保存正式报告；不把仅有终端摘要当作已登记预检。缺路径先修本期启动绑定，保留原选模型、文件身份检查和本地上传禁令。

只有非 null 的明确选择才使清单中的 `reference-asr` 成为启动必需项。预检使用同一 Python 的独立进程运行所选项目的检查入口，固定并记录本地程序、模型文件的 SHA-256 与大小；只执行程序快照的 `--help`，不加载模型、不读取用户媒体、不转写、不上传。报告中 `model_load_verified=false` 表示尚未验证模型加载或识别质量，`callable` 不能当作实际转写成功。

环境变量或已下载的模型不能代替本次选择和配置确认。缺程序、缺模型或探针失败时停止，不自动换模型、语言或服务。配置变化后重新预检并通过下述同一个确认入口，不增加第二个确认门。真正转写前仍需复核程序、模型、源素材身份并取得实际执行回执；预检报告不能替代它，也不能通过直接调用底层转写绕过正式流程。

展示一次配置摘要并得到真实用户回复后：

```bash
<python> <skill>/scripts/project_python.py --project-root <project> -- \
  <skill>/scripts/confirm_job_setup.py \
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

路径存在但入口缺失、入口或版本未登记、probe 无法执行、probe identity 不一致、smoke 失败或非代码阶段未绑定时，要显示准确状态，不能计为满足。Punk 前置安装只处理目录完全不存在的情况；已有异常目录不覆盖、删除或重新 clone。普通准备沿用现有授权；账号、费用、管理员权限和冲突目录仍单独确认。

没有缺失项时展示并确认当前配置草稿。缺失普通本地环境时按清单计划和项目内安装入口补齐后复检，不重复询问；账号、费用、管理员权限或处理冲突才需要用户决定。用户拒绝必需项时在对应阶段前标记 `blocked`；拒绝未选可选项则记录并继续。

## 4. 安装方式与边界

| `method` | 执行方式 | 约束 |
| --- | --- | --- |
| `system-package` | 使用当前系统包管理器安装准确 package；同一 `group` 只安装一次 | 普通安装按本合同执行；需要管理员权限时停止，不自行使用 `sudo`、改 shell 配置或换包 |
| `python-package` | 使用 `project_python.py --prepare` 为已选 Python 安装登记的必需包 | 自动补齐缺包到项目 runtime；不改全局解释器或自动更换 Python 环境 |
| `skill-installer` | 使用当前 Agent 环境的 Skill 安装能力，从登记 source 安装 | 只安装报告中的 Skill；安装后验证 `SKILL.md` 可发现 |
| `git-clone` | 将登记 source 克隆到准确 destination | 只处理缺失目录；目标已存在但不合格时报告冲突，不覆盖、删除或 reset |
| `plugin` | 使用当前平台插件管理器安装用户已选插件 | 先取得本 Job 明确批准；账号与连接步骤由用户完成 |

安装失败后停止该安装组，保留命令、退出码和简要错误信息；不自动换镜像、换包、换插件或重试。修正后只复检受影响依赖。

## 5. 条件依赖

- `overlay-studio-native` 仅供已选中的 A-roll `pin-board` 短要点候选。准备动作登记项目内固定 vendor 提交和本项目 adapter/runtime；缺少 runtime 锁定文件时只复制与 vendor 字节相同的文件，缺少 `node_modules` 时在项目 runtime 内执行锁定的 `npm ci --ignore-scripts --no-audit --no-fund`，并设置 `PUPPETEER_SKIP_DOWNLOAD=true`。探针只证明当前系统 Chrome 与原生入口可调用，不下载 Puppeteer 浏览器、不生成媒体；锁文件冲突、源码提交或版本不符时停止，不覆盖或修改第三方源码。正式执行时区分 `native_export` 与 `reuse_png`，复用已有 PNG 不重新调用上游导出；最小合成检查只能证明透明层复用和父级合成，不扩大为全部原生卡片资格。

- 选中 `whiteboard-video` 时，`whiteboard-video-adapter` 探针核对项目 vendor 的纯 Skill wrapper、engine 源码/资源指纹、Python 3.12 虚拟环境的实际模块导入与锁定依赖版本，以及 FFmpeg/FFprobe。此探针不生成媒体。缺失或版本不符时停在准备阶段，按[生成型 B-roll 编排](generated-broll-skills.md)的项目内依赖边界处理，不换解释器或调用其他生成服务来绕过。
- 选中 `paper-collage-ad` 时，项目内 Paper Skill、固定 `layer-animate.mjs`、Python/Node/FFmpeg/FFprobe 及本包 wrapper 必须同时可用；`paper-collage-adapter` 的真实绑定探针创建适配器并核对入口身份、工具可执行性，不生成图像或视频。详细调用及图片来源见[生成型 B-roll 编排](generated-broll-skills.md)。缺上游时停在准备阶段，按该页项目内安装边界处理，不能换回自画动画。
- `code_generated` 调用现有依赖 Skill。绑定 `html-video`、`hyperframes` 或 `hd-talking-head-local-canonical` 时，对应 adapter 必须 `selected + callable + bound`；manifest 精确登记 entrypoint、producer version、adapter identity 和可执行 probe。`hyperframes` 登记 Notification Cascade、ChatGPT Exchange 两个 B-roll 包装器，以及 A-roll 的 `hw-pipeline` 包装器；`hd-talking-head-local-canonical` 登记本 Skill 的共享 renderer 入口。预检按已冻结 entrypoint 只匹配对应 probe，并同时检查固定 HyperFrames 提交、`@hyperframes/cli` 版本、渲染入口与包装器，不能只凭目录存在通过。
- 所有代码组件的冻结绑定须包含 `invocation_record`，关联上游 Skill 调用证据与当前内容参数；正式执行的实际入口、退出状态及输出身份另由产物的 `invocation_evidence` 保存。记录只反映已经执行的事实，不能预填成功或用候选登记代替真实调用；字段及绑定校验以当前组件合同为准。
- `external_stock` 草案选中 `pexels` 或 `pixabay`：对应 provider 必须在首次搜索前 `selected + connected`。该状态可来自 Job 启动时的连接摘要，但请求前必须重新复核。
- `ai_generated` 草案选中具体 provider 后：在首次生成前，按精确模型 ID、参考图支持、9:16、无声输出、并发与额度状态做当前 Job 确认。素材冻结后再用完整 ShotRecipe v2 复核 binding。
- `official_material`：需要浏览器或来源连接器时，在首次获取前确认可用状态。
- `official-video-acquisition` 只在仍需获取时成为必需项。预检中 `yt_dlp` 可导入或浏览器能力存在仅证明下载通道可能可用；实际获取必须按 [官方视频下载 Skill 调用与验收](official-video-acquisition.md) 读取并调用上游 Skill。带 Job 上下文的预检核对已冻结视频的 Job 内普通文件路径、publisher/URL、SHA-256 与 FFprobe 视频流/有限正时长；有效时记录 `local_official_media`，不要求下载器。文件缺失恢复获取依赖，字节变化或探测失败明确停止，不能偷偷换素材。探测不是全片解码或事实核验，正式使用仍需来源核实及当前区间 QA。

条件依赖不触发跨类改写。某个已选来源暂时不能执行时，保持原配方并给出 `retry_same_strategy` 或返回 `visual_direction` 重新批准；不静默换成另一类来源。

## 6. 显式停止条件

- 当前必需 runner、运行时、Skill、入口、binding probe、非代码阶段绑定或 provider 连接缺失：在首次使用前标记 `blocked`，返回准确状态。
- 安装完成后必须重新预检；只有达到 manifest 声明的 `required_level` 才计为满足。
- 预检、安装和连接检查不调用图片或视频生成，不增加 generation 次数，也不消耗 provider 额度。
- 不因当前机器已经存在目录而省略检查；代码入口、实际版本和 adapter identity 必须由可执行 probe 一次返回并逐字核对，不能从源码字符串推断。

白板的本地 editable 安装会产生 `.egg-info` 元数据，它与 `.venv` 一样属于机器运行环境，不纳入发布源文件清单。Adu 另要求项目内 FFmpeg/FFprobe 9.0.2；这是机器工具前提，准备入口不自行编译或替换系统 FFmpeg。机器已有同版本可执行文件时可复制到包根的 `skill-development/runtime/ffmpeg-9.0.2/bin/`，保留其系统动态库条件，再由原生色彩探针核对；不得引用原开发项目路径作为运行依赖。
