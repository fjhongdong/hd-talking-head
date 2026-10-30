# Barty / Bang 完整原生调用

两渠道保持完整原生 Skill、参考、模板和渲染脚本。我们的接入层负责任务交接、环境准备、结果审核和正式消费。原生 Skill 决定设计、拆层、构图、动作和工程；父级传入输出规格和安全区，不预写编舞。

## 身份与一次匹配

统一按“渠道→模板→标签”选择。`canonical_identity` 是规范渠道和模板的唯一计算入口，匹配结果、联合分配和统计共同使用它；实际 candidate、route、入口及来源绑定保持各自执行身份。只归并有同一原生来源证据的别名，不凭名称或渲染器相同合并渠道。

先分别建立贴片和 B-roll 语义列表，各自数量由语义决定。每项匹配全库一次，缓存保留完整命中集合。复核用同一目录和确定性召回条件检查集合完整性，不重新搜索、不重复宿主语义评审。合格候选共同参与先渠道、后模板的联合最大化；最后校验时长、覆盖与阅读窗口。新增语义项才新增匹配，原项复用缓存。

每项使用一个稳定模板身份。Bang 组合选项记录在 `native_options`，值为原生目录内的渠道内标识；不重复主模板、不创建组合模板，不额外增加模板计数。叙事流程与风格同时选中时，以叙事流程为主，风格作为原生选项。两概念组合保留原生指定主次，不由父级限制内部编排。主题、文字、模型和本期工程均不产生新模板身份。

## 确认前：绑定任务

当前接入版本为 `2.0.0`，brief 使用 `schema_version=2`。不自动补写旧 Job 的新协议身份，不迁移旧批准媒体。

每项在本 Job 的 `native-inputs` 创建 brief，字段由 `motion_native_skill_adapter.validate_brief` 检查：

- `dependency_id`、`job_id`、`template_id` 和 `native_options`。
- `source_binding={aroll_sha256,segment_id,start,end}`，`composition={width:1080,height:1920,fps:24,frames}`，`alpha`，`canvas_transport`。
- 原有 `template_request`、`semantic_goal`、`transcript`、段内 `word_anchors`、`speech`、`materials` 和 `authorization`。
- `task_source={semantic_row_id,quote,semantic,required_change,component_brief}`，由已有 director 和 treatment 的同一语义行及组件派生，使用 `task_source(...)`，不手填相似描述自证一致。
- 本次 `project_directory` 和 `result_record_path`。文件描述继续使用 `{job_path,sha256,byte_count}`。

`quote/semantic` 包括原话支持的对象、关系、变化和禁项，必须与当前父级语义来源一致。`required_change/component_brief` 保留本次表现参考，原生可以采用更合适的表达；父级设计说明不锁定构图、图层或关键帧。真实输出仍须表达批准的意思，不得新增无依据的事实或数值。

确认前冻结语义列表、完整候选缓存、所选渠道和规范模板、原生选项、用途、时间与规格、素材和服务授权、编号、人物及字幕安排。尚未创作的原生项目明确处于待制作状态，不能填写“无关键文字”冒充检查完成。用户仍只确认现有完整清单一次。

确认前仍须按[有出处的语义判断](motion-capability-library.md#有出处的语义判断)为每个已有或待原生创作组件填写 `semantic_assessments`；`pending_native` 只延期实际工程、媒体和字形，不豁免规划任务的语义复核。Barty / Bang 尚未创作时，`phase=planning` 的判断只针对批准任务：`transcript_refs.current_clause` 引用当前时窗的完整批准词段，`content_refs` 必须引用本次哈希绑定 brief 的 `/transcript`、`/task_source/quote`、`/task_source/semantic`、`/template_id`、`/native_options` 五个真实值，理由明确未完成产物验收。只写 `task_source` 或选择理由不等于已提交此记录。创作后改用真实完成结果和冻结工程的实际内容证据；`phase=completed` 仍拒绝无完成产物的任务。已注册并验证的未来生成目标继续走 `planned_generation_targets` 的独立规划边界，不用 `pending_native` 冒充，也不凭提示词宣称实际内容通过。

## 确认后：调用原生并审核产物

`run_stage` 返回 `execute_native_skill`，交接同一批准任务、完整原生入口、原生选项、材料和局部词锚。宿主完整读取原生说明后创作。收费资产请求继续沿当前 Job 已有授权流程，不因接入自动启用服务或额度。

相对脚本、HTML 和输出路径均以本项工程为基准。调用记录按结果文件身份独立命名，多个项可以共用 `native-inputs` 父目录。Barty explainer 的内嵌渲染脚本和 Bang exporter 按原文逐字复制到 Job 后执行；不改第三方源码。媒体统一写入工程根的 `out/`；仅此输出目录及安装依赖不作为作者输入，其他真实输入均冻结，包括嵌套 `assets/out/` 中的素材。

Barty `motion-broll` 的 `.L` 是原生引擎管理的锚点外壳；每次 `seek(t)` 都按 `anchor` 重写该层的 `left/top`，不能把内容偏移写在 `.L` 自身。按原生 `engine-api.md` 把偏移放入其内部子层；`world` 内对象也使用原生世界坐标和 `center/cam` 换算，不把屏幕坐标直接当世界坐标。构建后先看真实完整尺寸静帧，确认正文、必要的示意标记和边界均可见，再将实际图作为其他原生流程的输入；构建或导出成功不代表排版通过。

调用 `capture_render(...)` 执行原生脚本。先核看真实图形、动作、文字及过渡，再以 `publish_completed(...,qa_note=...)` 登记实际产物。技术规格通过不等于语义或美观通过。原生 QA 和实际画面判断沿现有阶段回执保存，不另建评分或审批系统。

在现有 realization 中，为本次完整原生组件补充实际 `visible_text`、`motion_readability` 的源码引用、字号角色、区域和阅读窗口，以及实际语义引用和视觉检查。真实文字必须有目标清单，不能用空清单绕过；原先明确确认的文案必须保留。变化仅限当前原生项的实际产物，不能借此修改语义、模板、时窗、费用、编号或其他组件。

审核冻结后，正式执行器只消费该审核版本的结果和媒体字节，不再创作。结果、源码、素材或所选任务不一致时停止，不能按路径接受后来替换的文件。

## 当前项返修

失败先停止当前项并分析原因。任务和授权不变时，在新工程及结果位置修订该项，记录该项 `native_revision_reason`，保留旧产物并重新做实际 QA；未受影响项保留原绑定和字节。不可变任务字段必须与批准 brief 相等，仅执行位置及其派生绑定身份可在审核前更新。多项先后完成的合法单项修订可共同进入最终审核，不按累计修订项数拦截。审核冻结后的变更走原有正式修订流程，不无条件自动重试。

`confirmed-content.json` 继续保护用户明确要求保留的文字和来源。按原合同只登记真正需要保留的字段，不冻结整个 brief 或临时工程位置；用户明确锁定的具体已完成媒体不能借技术修订替换。

## 环境与验收

所选渠道通过唯一依赖清单按需准备。依赖锁要求 Barty 的 Node ≥20，Bang 的 Node ≥22.12.0；安装前检查，不自动升级全局环境。新制作记录实际 Node、FFmpeg、FFprobe、浏览器版本及锁文件身份。已审核媒体复用只检查必要工具、冻结生成记录和真实产物，不要求重新安装历史浏览器或再次渲染。

父级字幕安全区按当前镜头的真实 `visual_strategy.mode` 和 composition 计算，透明贴片不误按 B-roll 读取头像。透明媒体检查使用实际 FFprobe 结果：ProRes 4444 的 `yuva444p10le` 与 `yuva444p12le` 都保留真实格式，不能因编码参数为 10 位就把解码结果改标为 10 位。透明性、精确编码组合、尺寸、帧率与帧数仍须同时通过。

发布前使用最终代码跑一条独立代表样片：Barty 透明贴片叠真人，接 Bang 原生 B-roll，含真实中文、父级原声、唯一字幕和编号。文字目标在原生制作后绑定实际源码，检查透明进出、人物和字幕避让、整板方向与完整画面、语义和阅读时间，并走到正式消费。配合针对身份别名、候选裁剪、任务变更、合法产物补全及素材替换的必要反例；不按模板数量机械重复渲染。

样片及用户素材放完整 Skill 包外。旧 Job、现有成片和第三方 Skill 保持原样。
