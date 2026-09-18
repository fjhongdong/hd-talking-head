# 发布与跨 Agent 调用合同

## 完整包，不是单个 Markdown

- 使用整个 `hd-talking-head/` 目录：`SKILL.md`、`references/`、`scripts/`、`assets/`、`tests/` 以及 `release-manifest.json`。相对引用始终从本包解析，不依赖调用者工作目录。
- 本包不绑定 Codex、zcode 或某一家 Agent；宿主需要读写文件、运行命令和人工确认能力。完整剪辑仍依赖兼容的 `edit/hd` 项目运行时、媒体工具及当前 Job 选中的 provider，不随 Markdown 自动安装。
- 登记的源码、样片和验证帧是历史模板证据，不是当前视频已经生成或已验收的证明。不得将设计示例文案、用户人脸、旧 Job 时码或旧模型配置直接用于新任务。

## 启动与恢复

跨机器取得兼容运行时代码使用 [运行时导出、校验与安装](runtime-deployment.md) 的 `runtime_bundle.py`，安装到不存在的新项目根；这不包含系统依赖、媒体、模型密钥或用户 Job。安装后仍执行完整预检，不能重签旧 Job 绕过源码身份差异。

```bash
python3 <skill>/scripts/verify_skill_release.py
python3 <skill>/scripts/verify_broll_template.py
```

第一条校验发布附件与 SHA-256；第二条还需要 PATH 中的 FFprobe 与 FFmpeg，对包内第三方样片参数、双输入执行记录及三态 PNG 与 MP4 对应帧的真实像素进行复核。它串行解码，不启动渲染器或写新媒体。失败时停止相应工作并报告具体路径，不能现场刷新哈希、删去记录或创建空文件使检查通过。

`initialize_video_job.py` 在创建任何 Job 输出前强制运行发布完整性及模块来源检查，记录 release 与实际运行时身份。随后写非密钥配置草稿、执行带 `--job-context` 的预检，本次用户确认后调用 `confirm_job_setup.py`。单纯复制 Skill 到旧运行时不够：项目须包含 `startup.py`，且 `state.require_runnable` 已接入启动门。

恢复同一视频时，先读它的 `job-context.json` 和 workflow，不重新新建 Job。对照保存的 release 身份及当前完整性报告。旧任务没有 release 字段或包版本已变时，应明确列出差异，决定继续旧包还是执行受控迁移；不得借升级绕过已有人工门或悄悄重做已批准资产。

运行时绑定合成器 contract、实际 Python 及 `edit/hd/tools` 下 Python 源码哈希。不同工作树即使都叫 full-v2，也不能视为同一实现。长驻进程已导入另一项目时改用新进程，不删除 `sys.modules` 后混用旧对象。记录版本不等于证明全部视觉要求已满足，正式 canary 仍须验收。缺 `runtime`/启动批准的旧 Job 没有自动迁移器，先保留旧包与批准资产，明确处理差异，不重签上下文假装无变化。

可向其他 Agent 这样交接：

> 阅读 `<skill>/SKILL.md`，执行 `hd-talking-head`。项目运行时在 `<project>`；原视频为 `<video>`，文案为 `<script>`。先校验完整包及依赖，确认本任务模型配置。按唯一 Job 和人工门推进，使用已有批准记录，不重复确认，不静默替换模板、字体、文案或模型。

尖括号均替换为当前机器的真实绝对路径，不能照抄为参数。密钥交给宿主的安全配置渠道，不写入 Skill、发布清单或交接消息。

初始化入口使用 `--project-root`；直接运行依赖 `edit.hd` 的路由编译器时，应显式设置本次命令的 `PYTHONPATH="<project>"` 并使用已确认的 Python 解释器。不要依赖前一次 Python 进程里的 `sys.path`，也不要通过修改全局 shell 配置解决路径问题。例如 `PYTHONPATH="<project>" <python> <skill>/scripts/broll_capability_router.py --help` 可检查跨目录入口；实际编译还需已批准的 intent、strategy、bindings 和帧数参数。

## 生产接口的模板身份

- 代码组件必须将模板的 10 个来源字段同时冻结在 `source_bindings` 与 ShotRecipe 中，见正式生产绑定。标准 `visual_plan` 编译器可以直接消费已冻结字段，不依赖聊天外另传候选集合。
- 候选集合只在首次选择模板时使用。候选结果与绑定中已有字段冲突立即失败；不允许以“重新路由”为由覆盖用户已批准模板。
- 第三方记录在候选转换、正式编译和执行器入口均复核主包登记身份及实际附件，不接受手填同名记录。来源字段、容量或引擎不符立即失败。排序函数本身不证明真实性；本地 canonical 的来源及当前渲染参数消费仍需各自证据，不能套用第三方验证结论。
- `execution_qa` 是强制资格附件，协议见 [双输入实测资格](template-qualification.md)。追加资格证据也会改变当前 `verification_id` 与 release；旧 Job 的身份冲突须明确迁移，不能倒改历史配方/回执。`qualification/source-registry.json` 仅为旧执行的只读证明，不是第二份活动 Skill 或运行配置。
- 代码绑定的 `invocation_record.template_request` 冻结当前语义、信息量与精确数值，字段见路由合同。编译与执行器入口都检查；缺字段的旧计划明确退回绑定阶段，不悄悄补默认值。
- 缺少新字段的旧视觉计划应返回 `visual_direction` 重新冻结，不自动补假哈希或虚构验证记录。不得从一个工作树整体覆盖另一工作树的无关剪辑代码来升级 Skill。
- 新模板执行计划使用 `invocation_record.status=planned`、`exit_code=null`，不预先宣称进程成功。历史成功绑定可以读取，但不替代正式执行器本次输出的真实调用证据。DataRollup、Notification Cascade 与 ChatGPT Exchange 的可调用工厂、brief 结构和验证边界分别见 [DataRollup 原生执行接口](data-rollup-execution.md)、[Notification Cascade 原生执行接口](hyperframes-notification-execution.md)和 [ChatGPT Exchange 原生执行接口](hyperframes-chatgpt-exchange-execution.md)。
- 新 B-roll 的 `bottom_window` 必须绑定 [共享头肩参数](avatar-profile.md)。缺参数、跨镜头 profile 漂移、错误 A-roll SHA 或裁切越界会停止；这不是自动识别人脸或保证任意中间帧姿态。更新 helper 同时改变发布身份；不自动迁移已批准 Job。
- 用户资料变更只使用 `manage_user_materials.py`，完整行为以 [权威素材使用回执与变更事务](material-usage-contract.md) 为准。已使用资料按当前有效回执规划和修订；旧 Job 缺回执时停止，不补造引用或批准。
- 支持 `segment-inputs` 的合成器提供 [跨视觉计划的片段字节复用](visual-revision-reuse.md)。新 manifest 固定逐段输入指纹及正式/canary 复用清单，旧批准证据和当前输入均须校验。整计划批准仍由父 manifest 绑定，不能因为片段 identity 不再包含整计划 SHA 就跳过批准或伪造新版 manifest。媒体复用不保留下游人工批准；旧 renderer 产物不自动迁移。

## 维护与发布

1. 只在唯一主版本维护，保留用户其他修改。回滚依靠版本控制或使用路径之外的可恢复文件；不在项目、工作树、Skill 发现目录中留下旧包、备份或第二份执行说明。登记所需的原始证据和 Job 事务恢复文件不是过期备份，不随文档清理删除。
2. 先写能复现问题的失败用例，再修复规则、脚本和直接相关接口。规则写入文档不等于机器 gate 已实现，报告时分别说明。
3. 串行运行 Skill 自测、项目相关回归、真实模板验证及包结构检查；无必要不重渲染已批准成片，不启动多个浏览器或渲染进程。
4. 完成检查后，为包内全部受控文件生成 `release-manifest.json`，记录 `schema_version=1`、唯一 `release_id` 与相对路径 SHA-256；清单不包含自身、`.DS_Store`、`.pyc` 或 `__pycache__`。发布后修改任何受控文件都需新一次审查和更新清单，不能让任务执行器自动重签。
5. 本机仅维护 `/Users/Abner/.agents/skills/hd-talking-head/` 一个主版本，所有 Agent 直接读取；不再复制到项目、工作树或 `.codex/skills`。跨机器交接才传完整包并指定一个目标主目录，`--peer` 仅作交接完整性比较，不是建立多个活动版本的要求。历史证据保持原样。
6. 从项目外目录实际调用发布入口，确认相对引用、模板附件与项目根路径可用。报告测试范围、外部调用未验证项及是否重渲染，不把结构测试写成完整视频验收。

本发布包含的自动阻断：包缺失/改动、跨项目模块缓存、Job 预检/配置批准缺失或失效、实际 runner 导入失败、模板证据哈希不符、未登记的第三方身份、渲染器与登记引擎不符、声明内容的语义/容量越界、已知模板不支持的数值输入、已冻结字段被候选覆盖。媒体检查另拒绝不合格画幅、像素比例、显示旋转、时序及当前输出帧率。美观度、文案实际消费、语义准确、重字听感、开场叙事和转场自然程度仍需真实媒体检查与人工验收；不能宣称自动杜绝全部视觉或语音问题。
