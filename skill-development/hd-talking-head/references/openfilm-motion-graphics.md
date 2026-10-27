# OpenFilm motion-graphics

这是已授权的原生创作 Skill；能力库当前登记一个通用模板，按原生 Skill 创作，不宣称存在多个现成模板。执行者按其说明为本句编写可编辑场景；我们的 adapter 只冻结输入、调用原生公开渲染入口和检查输出，不临时写动画。已认可样片证明这类主体动作和完成度可用，不把样片中的手机、放大镜、信封、颜色或时码固化为下一条的设计。

## 选型

能力库将本入口登记为渠道 `OpenFilm`、模板 `openfilm/motion-graphics-scene`，再用标签匹配语义。每期场景内容随主题创作，但沿用该模板身份；适配资格不改变渠道或模板层级。

唯一发现入口返回 `openfilm-motion-graphics:motion-graphics`，与其他 Skill 一起进入既有两轮选择。适合需要具体对象操作、状态转变、检查与发现、控制权交接，或需要按主题专门组织主体与信息的短镜头。标准数据卡、原生聊天、手绘推导已有组件更直接时，仍按语义和质量选择它们；真人行为、真实产品操作或事实凭证不以画出来的示意图冒充。

只有“高级感”“会动”或相似关键词不足以入选。先说明观众会看到什么主体、什么动作、什么变化，以及相邻镜头为什么适合这种视觉语言。主变化未成立时不能靠标题复述、卡片滑动、换色、镜头缩放或装饰补过验收。不设 Skill 配额，不为了轮换牺牲准确性。候选匹配完成后，在真正制作前同时判断语义是否成立、审美是否可实现；保留合格候选供全片渠道和模板最大化选择，不为漂亮丢掉语义，也不把“换一种画风”当作多样化。

## 环境与实际调用

`project_python.py --prepare` 已编排 `ensure_visual_broll_skills.py --skill openfilm-motion-graphics`。当前项目内版本为 `openfilm@0.2.4`，原生 `playwright-core@1.61.1`／Chromium 1228；Node 至少 22.2。缺失时仅准备项目本地依赖；已装版本不一致、目录残缺或检查失败即停止，不覆盖安装、不自动重试。宿主在环境检查前仍按统一更新规则核对上游新版；更新须先核对接法与原生说明，不在正式渲染中联网切换。

启动探针不止检查文件和版本：现有 binding probe 还实际加载 `openfilm/host`、`openfilm/render`，启动并关闭一次原生浏览器。它只在启动检查中执行，不在 adapter 工厂或每段导出中重复启动，不读取项目素材、不渲染、不打开 Studio 或生成服务。独立合成检查也必须通过 `project_python.py --project-root <project> -- <检查脚本>` 启动，复用项目现有 Python 包路径，不因漏传路径而重装依赖。

选中后，从预检所得 runtime 调用实际 `node <runtime>/node_modules/openfilm/bin/openfilm.mjs skill motion-graphics`，完整阅读输出和同包 `MANUAL.md`。原生创作工作台按手册使用当前 Job 的独立目录；不改已验收成片或共享示例。指令的路径和版本记录在既有制作记录中，brief 冻结其摘要；摘要不是“已阅读”或视觉合格的证明，不新增自证布尔字段或审批链。

所有资源先保存到本 Job。页面按原生 `window.film={width,height,duration,ready,frame(t)}` 创作，直接设计为 1080×1920；`duration=frames/24`，页面局部时钟从 0 开始。同一 t 在任意跳转顺序下必须画出同一帧，资源和字体加载完才 ready。原生工作流创作的页面与我们的包装代码分开归属，不声称页面是第三方原有模板。

仅使用本 Job 冻结的本地图片、字体、SVG、CSS、JS。页面不得有配音、音乐、第二条字幕、音视频标签、自行计时播放、远程加载或未授权素材调用。当前 adapter 不开放 `openfilm get`／服务密钥，也不代替 Lovart 的既有费用与上传授权。静态扫描只检查输入合同，不是 JavaScript 安全沙箱。

本地库的版权网址及内部计时函数不等于页面实际外联或自动播放，不据此一刀切拒绝。实际资源引用继续核对冻结路径；动态加载入口仍受现有检查约束。播放行为以原生 `frame(t)`、时钟和跳转一致性检查为准，不复制或接管第三方库的时间线。

## 交接与冻结

沿用当前 treatment 的原文、语义目标、required_change 和 `visual_pattern`；不要维护另一份互相矛盾的文案。`creative_handoff` 将这些值交给创作执行者，并补充主体、选样式的理由、禁止提前出现的结果，以及动作拍：

```json
{"start_frame":0,"end_frame":48,"spoken_anchor":"当前原声的真实词锚","before":"动作前可见状态","action":"主体实际完成的动作","after":"动作后可见状态"}
```

帧数只是格式示例，不是所有镜头的统一时长。按本段 Scribe 词锚确定局部整数帧；每拍在本镜头内、顺序不倒置，留足辨认和阅读时间。信息密度来自对象、动作、关系和上下文，不以字数或装饰数量充数。出现数字、引语或事实时，继承当前批准来源和精确数值，不能为画面编造。

设计交接仍只使用上述 8 个字段，但每个字段必须能指导实际画面：`subject` 写清主体、焦点对象、对象比例和空间关系；`style_reason` 说明为什么采用这组构图、文字层级、留白、线条、材质、光影和动作节奏，以及它与相邻镜头的区别；`visual_pattern` 写真实的构图／动作家族，不写语义标题、编号或表面换色；`beats` 写动作前、中、后的状态、焦点和节奏，并保证同一对象跨镜的外观和位置逻辑连续；`forbidden_outcomes` 明确文字重复、遮挡、错误朝向、比例失真、无意义装饰和提前出现的结果。主体比例、UI 字体和留白必须服从父级头像、字幕和安全区合同，不能缩小已批准头像给主图腾地。美观不是统一 3D、全加阴影或把所有字放大加粗；按题材选择合适的表面、材质和光影，让动作本身承担信息。

语义标签只负责召回候选；最终选定前只做一次匹配，再在候选中比较渠道、模板、构图和审美可实现性。实际制作只验证被选路线，不把未生成的候选说成已通过视觉审片。将 assignment 冻结的 `design_plan` 四段说明逐项放入既有 `style_reason`，可用“构图／字级／完成度／焦点”连接，保持 brief 八字段不变；新冻结入口核对实际 brief 已收到所选设计。具体契约见[候选与设计合同](visual-quality-contract.md#语义列表匹配缓存与确认字段)。

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

在既有本地 QA 和 canary 内检查，不新增审批包：

- 语义：在正常速度下能看懂“谁对什么做了什么，结果如何”；动作对齐本句，否定和前后因果正确，没有提前显示下一句结果。
- 主体动作：看动作前、中、后的原尺寸画面及连续片段；只动标签或卡片不通过。代码有 frame 函数、文件是 MP4、像素变化都不能证明这项合格。
- 美观和信息：主次、中文字体、材质与光影、空间和运动细节协调；有效信息完整但不过载。检查运动中的遮挡、放大区域与真实原物一致、文字不模糊或越界、最后状态有可读时间；不以加粗、加阴影或统一 3D 掩盖比例、留白和焦点问题。
- 多样性：对照本片邻近镜头和最近两条的实际主体、构图与动作。换色、换 Skill 名但仍是同样卡片不是多样性；该样片的物件和风格不是默认模板。
- 确定性：使用原生 `look <具体秒数>` 在有效帧时间检查任意跳转一致性；不要无参数 look 产生联系表。其退出成功或静态报告不代替语义审片。
- 合成：1080×1920／24fps、准确整帧、SAR 1:1、单条无声音轨；父级继续用当前同时间轴圆形人物小窗、原声及唯一关键词字幕。先对照父级避让区域，不能靠覆盖旧成片下半部作为正式合成接法。

任何内容、动作或美观失败只修订当前授权镜头；先在原路线做针对性修订并记录已有 `visual_review` 观察。若能力不支持，或一次针对性修订没有改善，则回到已有匹配缓存重新选择；不静默切换到新收费素材，不修改第三方源码、其他已确认素材或已验收成片。没有合法且合格的替代时停止当前段并报告原因。已有认可不重复报审，但新文案仍须经过本次真实语义、审美和合成验收。

当前接法已用已认可场景完成一次独立的公共 `execute_component`、来源与配方守卫、`render_segment_video` 及既有预览命令的真实合成检查，包含同源圆窗、原声和唯一关键词字幕。结果为 129 帧／5.375 秒／1080×1920／24fps，原成片及原场景未变；这不是新正式 Job 的十二阶段验收，也不赋予通用模板资格。后续维护复用现有场景和检查入口，不为重复证明同一结果再生成素材或重渲成片。
