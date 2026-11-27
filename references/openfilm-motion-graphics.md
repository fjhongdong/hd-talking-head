# OpenFilm motion-graphics

这是已授权的原生创作 Skill；能力库当前登记一个通用模板，按原生 Skill 创作，不宣称存在多个现成模板。执行者按其说明为本句编写可编辑场景；我们的 adapter 只冻结输入、调用原生公开渲染入口和检查输出，不临时写动画。已认可样片证明这类主体动作和完成度可用，不把样片中的手机、放大镜、信封、颜色或时码固化为下一条的设计。

## 选型

能力库将本入口登记为渠道 `OpenFilm`、模板 `openfilm/motion-graphics-scene`，再用标签匹配语义。每期场景内容随主题创作，但沿用该模板身份；适配资格不改变渠道或模板层级。

唯一发现入口返回 `openfilm-motion-graphics:motion-graphics`，与其他 Skill 一起进入既有两轮选择。适合需要具体对象操作、状态转变、检查与发现、控制权交接，或需要按主题专门组织主体与信息的短镜头。标准数据卡、原生聊天、手绘推导已有组件更直接时，仍按语义和质量选择它们；真人行为、真实产品操作或事实凭证不以画出来的示意图冒充。

按[视觉规划](visual-quality-contract.md)核对 OpenFilm 能否做出本句需要的主体、关系和关键变化。语义相同的可行画风都可作为视觉选择，模板数量按真实身份计算。

## 环境与实际调用

`project_python.py --prepare` 已编排 `ensure_visual_broll_skills.py --skill openfilm-motion-graphics`。当前项目内版本为 `openfilm@0.2.4`，原生 `playwright-core@1.61.1`／Chromium 1228；Node 至少 22.2。缺失时仅准备项目本地依赖；已装版本不一致、目录残缺或检查失败即停止，不覆盖安装、不自动重试。宿主在环境检查前仍按统一更新规则核对上游新版；更新须先核对接法与原生说明，不在正式渲染中联网切换。

启动探针不止检查文件和版本：现有 binding probe 还实际加载 `openfilm/host`、`openfilm/render`，启动并关闭一次原生浏览器。它只在启动检查中执行，不在 adapter 工厂或每段导出中重复启动，不读取项目素材、不渲染、不打开 Studio 或生成服务。独立合成检查也必须通过 `project_python.py --project-root <project> -- <检查脚本>` 启动，复用项目现有 Python 包路径，不因漏传路径而重装依赖。

选中后，从预检所得 runtime 调用实际 `node <runtime>/node_modules/openfilm/bin/openfilm.mjs skill motion-graphics`，完整阅读输出和同包 `MANUAL.md`。原生创作工作台按手册使用当前 Job 的独立目录；不改已验收成片或共享示例。指令的路径和版本记录在既有制作记录中，brief 冻结其摘要；摘要不是“已阅读”或视觉合格的证明，不新增自证布尔字段或审批链。

所有资源先保存到本 Job。页面按原生 `window.film={width,height,duration,ready,frame(t)}` 创作，直接设计为 1080×1920；`duration=frames/24`，页面局部时钟从 0 开始。同一 t 在任意跳转顺序下必须画出同一帧，资源和字体加载完才 ready。原生工作流创作的页面与我们的包装代码分开归属，不声称页面是第三方原有模板。

仅使用本 Job 冻结的本地图片、字体、SVG、CSS、JS。页面不得有配音、音乐、第二条字幕、音视频标签、自行计时播放、远程加载或未授权素材调用。当前 adapter 不开放 `openfilm get`／服务密钥，也不代替 Lovart 的既有费用与上传授权。静态扫描只检查输入合同，不是 JavaScript 安全沙箱。

本地库的版权网址及内部计时函数不等于页面实际外联或自动播放，不据此一刀切拒绝。实际资源引用继续核对冻结路径；动态加载入口仍受现有检查约束。播放行为以原生 `frame(t)`、时钟和跳转一致性检查为准，不复制或接管第三方库的时间线。

## 交接与冻结

`creative_handoff` 的 `transcript / semantic_goal / required_change` 分别绑定已确认语义行的原话、语义与画面任务，并保持已选渠道、模板、词锚、素材和费用边界。主体、`visual_pattern`、`style_reason` 与动作拍由原生流程自行设计：

```json
{"start_frame":0,"end_frame":48,"spoken_anchor":"当前原声的真实词锚","before":"动作前可见状态","action":"主体实际完成的动作","after":"动作后可见状态"}
```

帧数只是格式示例，不是所有镜头的统一时长。按本段 Scribe 词锚确定局部整数帧；每拍在本镜头内、顺序不倒置，留足辨认和阅读时间。信息密度来自对象、动作、关系和上下文，不以字数或装饰数量充数。出现数字、引语或事实时，继承当前批准来源和精确数值，不能为画面编造。

设计交接仍只使用上述 8 个字段，但每个字段必须能指导实际画面：`subject` 写清主体、焦点对象、对象比例和空间关系；`style_reason` 说明为什么采用这组构图、文字层级、留白、线条、材质、光影和动作节奏，以及它与相邻镜头的区别；`visual_pattern` 写真实的构图／动作家族，不写语义标题、编号或表面换色；`beats` 写动作前、中、后的状态、焦点和节奏，并保证同一对象跨镜的外观和位置逻辑连续；`forbidden_outcomes` 明确文字重复、遮挡、错误朝向、比例失真、无意义装饰和提前出现的结果。主体比例、UI 字体和留白必须服从父级头像、字幕和安全区合同，不能缩小已批准头像给主图腾地。美观不是统一 3D、全加阴影或把所有字放大加粗；按题材选择合适的表面、材质和光影，让动作本身承担信息。

语义标签只负责召回候选；最终选定前只做一次匹配，再在候选中比较渠道、模板、构图和审美可实现性。实际制作只验证被选路线，不把未生成的候选说成已通过视觉审片。规划 assignment 保持冻结，作为选型上下文；不要求原生 `visual_pattern` 或 `style_reason` 复制其中的美术原文。原生 brief 的完整字段与自身技术 QA 继续保留。具体契约见[候选与设计合同](visual-quality-contract.md#语义列表匹配缓存与确认字段)。

本句讲痛点时，按[痛点场景与人物感受](visual-quality-contract.md#痛点场景与人物感受)将反复操作、阻碍和人的负担放入现有 `subject`、`beats` 与 `forbidden_outcomes`，不新增 schema 字段。只让卡片来回移动不足以表现困扰；人物存在也不等于人物在参与任务。桌面人物插画只是本期的合适方案，不作为下一条的默认场景。

`scripts/openfilm_motion_adapter.py` 提供 `validate_brief/create_adapter/create_binding/create_artifact_probe`。brief schema 1 的唯一顶层字段为：

- `source_binding={aroll_sha256,segment_id,start,end}`：与当前批准片段相同。
- `template_request={semantic_family,information_units,numeric_values,numeric_scale}`：与当前所选内容相同。
- `composition={width:1080,height:1920,fps:24,frames,alpha:false}`。
- `entry` 与 `assets`：每项 `{media_ref,job_path,scene_path,sha256}`；Job 内相对路径，主入口目标为 `index.html`，名称及目标路径各自唯一。主入口与素材共最多 8 个文件，沿用公共执行器的现有容量。
- `upstream={package_version,skill_sha256,manual_sha256}`：来自真实当前 runtime。
- `creative_handoff={transcript,semantic_goal,required_change,subject,visual_pattern,style_reason,beats,forbidden_outcomes}`。
- `schema_version:1`。

按既有 factory/binding 接口创建 `ReferenceProcessAdapter`，加入父级 `component_adapters`，把同一 payload 作为 brief_loader 的结果。`dependency_id=openfilm-motion-graphics`、renderer 为 `OpenFilm`、入口 `scripts/openfilm_motion_adapter.py`；`template_id=openfilm/motion-graphics-scene` 是稳定的渠道内模板身份，不等于每个具体场景都已单独完成模板资格验收。资格固定 `custom_fallback / structural`，不加入 verified-template-registry，不冒称双输入已验证模板。正式计划继续通过唯一选型 check、ShotRecipe 和批准门；渲染前不得修改已冻结页面。

正式包装器实际调用包公开导出的 `openfilm/render` 原生 `render([page], {fps:24,workers:1,out})`，而非复制或修改其渲染器。这样不触发 CLI 首次运行时自动打开 Studio、查询更新或下载浏览器的副作用；创作阶段仍按原生手册使用工作台。包装器先输出私有临时文件，再只补 SAR 元信息、检查真实帧数，最后交给公共执行器；不会把受控输出 FD 当成可派生日志的目录，不补帧、不循环、不变速、不在失败时换场景。失败保留命令、输出和日志后停止。已有正式产物复用沿用公共 canary／镜头复用，不新增第二套“恢复生成”入口。

## 验收

按[动效创作要求](visual-quality-contract.md#动效创作要求)和[阶段合同](stage-contracts.md#制作交付与状态)完成当前镜头。原生制作与定位具体问题时可用 `look <具体秒数>` 检查有效帧的跳转一致性。正式输出为 1080×1920、24fps、精确帧数、SAR 1:1 的无声视频。父级使用同一剪后时钟合成人物圆窗、原声和关键词字幕。用户反馈后的修改沿用[局部返修](visual-revision-reuse.md)。

当前接法已用已认可场景完成一次独立的公共 `execute_component`、来源与配方守卫、`render_segment_video` 及既有预览命令的真实合成检查，包含同源圆窗、原声和唯一关键词字幕。结果为 129 帧／5.375 秒／1080×1920／24fps，原成片及原场景未变；这不是新正式 Job 的十二阶段验收，也不赋予通用模板资格。后续维护复用现有场景和检查入口，不为重复证明同一结果再生成素材或重渲成片。
