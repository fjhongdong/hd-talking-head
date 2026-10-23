# CutCod：复用真实来源，不把聚合站当渲染器

CutCod 只用于发现来源。已有 OpenFilm、Huashu、HyperFrames 等来源不重复登记。当前新增 `eian-riso-broll` 一个原生 Skill、10 个全屏信息模板；不是 10 个 Skill，也不是把网站全部模板都接通。

固定来源：`https://github.com/YIAN6557/eian-riso-broll`，提交 `e782ad7051f5fce1ca371523c144f4cb78ab5c40`。项目入口 `scripts/ensure_visual_broll_skills.py --project-root <project> --skill eian-riso-broll` 只准备项目内固定源码，随既有依赖检查和更新流程维护；不改第三方文件。使用前完整读取该来源的 `SKILL.md` 及其要求的 copy、templates、style、production 指引。版本变化先复核受影响的接法和能力描述，不静默放行。

## 选择边界

从完整口播命题出发，再在整个能力库比较动作和信息表达：

- `title / quote`：章节转折、已说出的结论；不是万能字幕。
- `number / compare`：明确数字或同单位对比。原生计数会取整，只接非负整数；不得虚构统计、效果比例或退款成功。不同单位必须先按真实换算关系提供同一尺度的 `base`。
- `converge / network`：归类汇聚、集合连结。示意节点数量不冒充真实个数；类别名称仅取原文已给内容。
- `focus / steps`：选项取舍、真实有先后关系的步骤。并列清单不画成流程，选择高亮不冒充实际完成。
- `shot`：真实本地资料截图和原生批注。必须冻结图像、来源和实际区域；禁止占位图、网页 URL、凭空标注。
- `versus`：原话中的认知修正或做法对照。不得凭空补充过去/现在或成功结果。

共同风格是双色孔版印刷：四种原生色本。它们只有信息主体（数字增长、条形变化、选项聚焦、归类移动等），没有真人动作。口播痛点需要体现人物困扰时，优先选库中能直接表达人物动作的其他来源，不用 Riso 卡片运动替代。相邻镜头仍比较构图、动作和节奏，不能因新接入而全片套此风格。

## 唯一调用

`scripts/riso_native_adapter.py` 提供 `validate_brief / create_adapter / create_binding / create_artifact_probe`，接入现有 `ReferenceProcessAdapter`、视觉计划、B-roll 路由及离线能力检查。禁止绕开正式编排直接把测试 MP4 登记为成片。

输入为 `schema_version=1, source_binding, composition, template_request, template, data, assets`。`template` 为上述原生名字；`data` 完整使用对应模板公开 DATA 字段，不接受 CSS、JS、时间轴或自由场景。`composition={id,width:1080,height:1920,fps:24,frames}`，时窗和 DATA.duration 一致。每个模板保留固定原生动作所需最短时长，不能剪断动作凑时窗。

草稿预检与正式组装共同调用我们路由器的 `riso_output_contract`：`layer_role=base`、`layout_slot=full_frame`，`composition.family` 只能为 `single_full_frame` 或 `evidence_with_data_overlay`，输出固定 `1080×1920 / 24fps / alpha=false`。执行适配器独立复核用途，拒绝 `no_broll`、`aroll_with_overlay`、非整屏布局及透明贴片输出。不新增输入字段，也不改变其他来源的输出规则。

`template_request` 的语义、信息单元和数字必须与 DATA 一致。数字模板登记可见数值和 `linear`；步骤登记实际步数；其他非量化画面为 `numeric_values=[] / numeric_scale=not_applicable`。`focus.verdict` 或汇聚数字标签仍需宿主引用原文逐项核对，解析检查不代替语义证明。

截图输入唯一格式：`assets=[{media_ref:"shot",job_path:"本Job相对路径",scene_path:"assets/shots/shot.png",sha256:"真实SHA256"}]`，可用 png/jpg/webp；`data.img` 必须是 `../` 加该 scene_path，不能空白。其他模板 assets 为空。

接法调用上游 `createProject / addTemplate` 创建独立制作输入，只替换该副本的 `const DATA`。原模板、样式、GSAP、动作和字体不变。先运行上游 `qa.mjs`，再调用 `render.mjs`。只有完整内容通过后才出片，不自动缩字、改布局、重试、切换模板或自写 fallback。失败完整日志保存在项目 `skill-development/runtime/riso-renders/native-*/invocation.json`，先分析再请求超出当前范围的修复。

原生输出 1080×1920 / 30 帧。我们自己的 `normalize_output` 按时间戳采样到 24 帧，并实际将全范围像素转换成合成器要求的有限范围 `yuv420p`；不只改色彩标签，也不放宽媒体检查。保持时长、动作速度和事件时间，不插帧、不重写上游 fps、不重新解释输入帧率。输出无音轨、方形像素、精确父级帧数；由原成片流程统一添加圆窗和唯一字幕。已有原生视频可复用同一导出函数，不重新调用浏览器或生成动效。

当前仅开放不透明 B-roll；不因上游存在 `--alpha` 就开放 A-roll 贴片。透明、避让与真实词锚尚未验证，不计入贴片入口。已有一条数字模板的 5 秒 MP4 样片完成原生动作、30→24 帧输出和 QA 检查；这只证明该代表模板的接法可用，不代表其余 9 个模板已经逐一渲染验收。每条真实内容仍需检查 native QA、实际动作、可读性、语义、字幕/圆窗避让和末帧连续性。

## 不强接的候选

`cutcod-ui-morph` 是固定方形演示；`opus-5-5-video-templates` 的候选以固定横屏/方形构图和硬编码动作内容为主。当前没有可直接满足本项目竖屏全屏 B-roll 或透明贴片的公开接法，不裁切、改第三方或重写场景来凑接通。仅有提示词或展示视频的资源也不登记为可执行模板。
