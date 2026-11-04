# Anidoodle 完整原生接入

固定官方 `alexgreensh/anidoodle` 提交 `9c20e77467be393e54c7193611eeec2f7bfb8cc7`，版本0.10.1。完整仓库保存在 `vendor/anidoodle`，不改、不提取第三方实现。来源逐文件记录为 `anidoodle-native-source.json`；模板为 `anidoodle-template-catalog.json`。父级由专用 `scripts/anidoodle_native_adapter.py` 派发、捕获实际调用并消费完成结果。

## 渠道、模板和用途

一个渠道，32个原生registry画风。`native_style_id`保留原生camelCase或主体名；对外模板`anidoodle/<kebab-slug>`。32个原生绘制过程不再额外计数；3份house style、launch/explainer工作流、种子和本期主题不新增模板。源码画风与完整工作流都有真实入口，但不是32套只换文字的固定动画。

可创作整屏B-roll，也可创作真人透明贴片。两用途保持同一模板身份，分别审核输出。**原生render没有把opaque画风demo变透明的开关。**透明用途必须在本期原生工程中画独立主体，不画全屏纸底、背景与`g.paper()`；局部标签底板可以保留。原生VP9 WebM保留alpha，桥接明确解码VP9 alpha并转ProRes4444供既有合成消费。检查实际解码透明像素和可见像素；只有`yuva`编码标志不算透明通过。

## 原生制作和中文

完整读取原生 `skills/anidoodle/SKILL.md`、所选画风recipe／源码以及任务对应的完整workflow。父级只交批准语义、词钟、原声、真实素材、1080×1920／24fps／整数帧数及实际头像、字幕安全区。原生独立完成故事、look、场景、动作、源码与原生QA。已有原声仅作词钟参考；本接法创建无声输出，不新建TTS、BGM或下载音源包。

用原始 `engine/tools/scaffold.mjs <Job工程> --linked --film <filmId> --format 9x16 --duration <seconds> --fps 24` 创建Job独立工程。所有本期创作写在该工程；完整引擎仍从vendor读取。原生`scaffold --linked`不会复制或改写引擎；原生host、deterministic frame与绘制工具均直接复用。

`drafting.ts`、`lettering.ts`和`scrapbookKit.ts`的手写glyph只覆盖Latin字符，不能接中文。中文在本期工程走原生Canvas `fillText`与已存在CJK字体，或原生`launchLook.ts`的`fonts/registerFaces`导入含中文字形的真实字体文件。不修改vendor glyph表，不把字库横线当中文通过。画风的形状、材质与动作仍按选定原生recipe实现。首次中文竖屏样片只证明该次工程，不能声称32个旧demo均已适配中文或透明。

原始渲染命令为 `[node,<engine>/tools/render.mjs,<filmId>,--out,out/native.webm|out/native.mp4,--workers,1]`。桥接只接受原生linked工程、该完整渲染入口与准确输出路径；先原生render，再原生`ship.mjs`全部技术检查。透明转换不裁切、不改时钟、不加音轨。父级用`capture_render`和`publish_completed`保存真实调用与结果，再按现有审核、冻结和组件消费协议完成接入。制作完成不自动等于用户接受。

## 环境和消费接口

`scripts/anidoodle_native_runtime.py`只检查并复用现有包内运行依赖：Hyperframes的esbuild0.25.12，以及Playwright1.64.0和真实已缓存Chromium。`anidoodle_node_runtime.mjs`用Node resolver将原生bare ESM `esbuild`导入指到该原版依赖；`NODE_PATH`让原生detect找到现有Playwright。不在vendor增加node_modules，不全局安装，不隐式下载。隔离resolver需要Node≥22.15；当前上游引擎本体最低Node20。缺已有依赖时明确停止，准备该已有依赖后再继续。

专用模块保留既有schema2 brief字段和schema3 result字段；`native_options=[]`、`canvas_transport=identity`。`ENTRY=scripts/anidoodle_native_adapter.py`，`VERSION=1.0.0`，`primary_renderer=HTMLCanvas`，`renderer_version=anidoodle-0.10.1-9c20e77467be`。`source_root/load_template_catalog/native_task/capture_render/publish_completed/inspect_result/load_result/create_adapter/create_binding/create_artifact_probe`与已有原生桥接同签名。路径、文件描述符、输入核验、原声检查、进程执行、ReferenceProcessAdapter和父级批准事实沿用现有共用工具。

资格样片位于完整Skill包外 `capability-samples/20261104-library-expansion/anidoodle/`。样片是标明身份的零付费开发素材；正式主阶段消费结果以本次父级Smoke为准。不改旧Job、不重签或重做已交付视频。
