# Sweety 原生接入

来源为完整官方 `threerocks/sweety-handdraw-video` v3.1.0，提交
`0d0187c93db8fab0cc772d39da6c4ab8d845646c`。完整原仓库保存在
`vendor/sweety-handdraw-video/`，第三方源码、内置 Skill、资产、规则和许可均保持原样。
唯一原生 Skill 入口为其中 `skills/sweety-handdraw-video/SKILL.md`。
能力库入口限于手绘口播 Skill。仓库内人像实验室属于独立的长片流程，目前不参与模板选型或依赖准备。

## 渠道、模板和用途

`sweety-handdraw-video-template-catalog.json` 管理 41 个模板：

- 21 个 `style-*` 原生画风模板，仅用于全屏 B-roll。编号 1/4/5/17/19/20 为逐笔绘制，
  其余 15 个为画笔揭示。画风标签描述题材、构图或视觉气质，本次插画和分镜负责体现实际人物动作及关系。
  编号、完整配方和绘制方式由上游 `style_choice` 校验。
- 20 个 `web-*` 固定原生网页动效。原生 `web_motion.render` 调用完整包内 `recipes.js`，
  输出透明 PNG 序列。父级只编码为 ProRes 4444 并合成，不生成替代动画。
- 同一个固定 recipe 可有多种用途，模板只计一次。圈注、形状标记、粒子、气泡和进度环用于真人贴片；
  其余 15 个 web 模板也可作为 B-roll 中的透明层。一个完整 B-roll 语义计一项，底色只参与合成。
- `custom`、手部、音色、转场和镜头选项不是额外模板，不与画风做乘积计数。

画笔揭示必须明确列为“刷出成图，而非逐笔绘制”。统一清单真实确认可以交给原生流程作为
接受依据；自动选择或笼统授权不能伪造 `reveal_accepted`。保留原生选择及接受证据。
3.1、19、20 的特殊参考锚点、阶段编辑和验收流程仍由完整原生指南决定，不缩写配方。

## 自有接口

`scripts/sweety_native_adapter.py` 复用现有 `ReferenceProcessAdapter`、媒体描述符、
原生完成结果和 `material_adapter` 媒体探针，不设置第二套审批或美观 QA。
提供 `source_root/load_template_catalog/validate_brief/native_task/prepare_narration/`
`capture_render/publish_completed/inspect_result/load_result/create_adapter/create_binding/`
`create_artifact_probe`。

Brief 沿用原生 Skill 交接字段（schema 2）。模板 ID 使用 `style-17`、`style-3-1`、
`web-kinetic-title` 等。`native_options` 为空；参数、画面与设计属于原生当前 Job 工程，
不是父级自写动画。`composition` 是 1080×1920、24fps，`frames` 与真实口播窗口一致。
全局 registry、选择器、阶段分发和发布索引由主接入统一登记。

### 透明组件

确认前写清模板要显示什么、靠什么底图讲清这句，以及动作何时落定。A-roll 用原生透明层，按实际脸部与字幕位置摆放。B-roll 有两种合成方式：

- **纸底。** 动效自身能把关系讲清时，使用单一 `single_full_frame` 主画面，母片负责铺浅纸色并叠加原生透明层。保留右下角人物圆窗及字幕区域。纸底不计素材、渠道或模板。
- **资料叠加。** 真实截图或片段提供必要信息时，使用 `evidence_with_data_overlay`。真实资料为底，Sweety 透明层用于指出实际位置、对象或关系，两层共用一条 B-roll 语义。资料来源仍按真实来源记录。

选型时将必要内容绑定到 `web-motion.json` 的实际 `/params/…` 字段，调用和发布时核对相同参数。真实资料本身已有的事实可由底图承担；用 `content.annotation` 绑定标注动作，叠层新增的事实仍需绑定实际字段。

流程、泳道、清单和阶段路线图分别承载步骤/分支、并行/等待、逐项完成/排除、阶段进度。
图表绑定真实数值、单位和来源，表格使用同一对比标准，卡片体现分组，公式使用实际 TeX。
地图绑定真实站点及路线；形变、物理和立体旋转只承担原生形态或动作可以表达的内容，涉及真实产品时用可辨认的产品素材。
标题、滚动数字和脉冲线通常做贴片，只有标题、单一数值或时间节奏就是本句主体时才占整屏。
模板选择继续在语义和输入合格的候选中最大化全片渠道、再最大化模板，最后校时。字句和关键动作应在窗口结束前落定并留出阅读时间，必要时回同一批候选。

当前 Job 的 `native-projects/<revision>/web-motion.json`：

```json
{"template_id":"web-kinetic-title","recipe":"kinetic_title","params":{"text":"真实原话中的关键句","style":"glyph_in"}}
```

`capture_render` 直接调用原生 `web_motion.render`，保留原生 settled endpoint PNG；
按父级真实帧数编码，不拉长、裁画面或重画组件。原生组件最长 30 秒。
透明不是简单根据 PNG 格式推断：原生页面透明，截图 `omit_background=True`，原生 SVG/Canvas
不统一铺全框底。局部气泡、卡片、物体和放大的地球可以有实色；这不等同整幅纯透明。
实际 alpha 像素检查只用于来源资格样片，不是每次生产的额外 QA。

### 21 个画风的完整流程

原生 Agent 读取完整 Skill 与所选完整画风。父级提供原话、真实录音、场景内词钟、素材、规格、
安全区与资源授权。当前未授权新生图或新配音时，只能复用真实已有素材，缺失则说明需要什么，
不能把缺图替换成文字版或虚构生成记录。

1. 在当前独立 native project 编写原生 `job.json`、设计、分镜、美术与绘制记录。
2. `prepare_narration` 保留父级16kHz单声道16位PCM的原文件与描述符，在原生工程内仅用普通
   FFmpeg `aresample=48000` 转为48kHz单声道16位PCM；不归一、不降噪、不改时长。保存真实 `parent-words.json`，调用官方
   `align.py JOB --words parent-words.json`。不调用 TTS、不加载 ASR，也不手编词钟。
   录音只用于原生构建与画面时钟，不进入交付素材；不额外运行整片音轨门禁。
3. 由完整原生流程运行 `handdraw_video.py build JOB`。原生风格、图片、美术、预算、
   字幕、取景和笔顺校验继续生效，保留真实 timeline、素材与绘制记录。
4. `capture_render` 直接调用官方 `verify_job(JOB, assets_only=True)`，其中实际运行
   `verify_art_direction` 和 `verify_assets`；再运行官方 `verify_compiled_master`、
   `validate_timeline`。这些检查验证真实素材、锁定录音与字钟、字幕、转场和笔顺。
   记录原生真实返回值；可调用原生 `export_storyboard` 提供审阅图，不把封面验收作为当前无声素材的门槛。
5. 直接调用官方 `render_chunk(JOB, output, voice_start, 0, frames)`。
   该原生函数完整调用 `Renderer.frame → scene/blend/view`，以原生方法绘制全部画面。
   它只接收 RGB 视频帧，不添加音轨。不创建完整有声影片，不运行 mix、full-film verify 或 finalize。
6. `publish_completed` 核对真实视觉检查记录、冻结的原生 timeline/素材、源代码、原始输入与输出。
   capture 与 inspect 复用现有媒体探针，实际要求唯一视频流、零音轨、1080×1920、24fps 和精确帧数。
   父级消费冻结结果，不在消费时再次生成。结果范围为 `product_scope=silent_visual_material`；
   这不是上游完整有声成片验收通过，也不伪造 finalize 或原生验证 receipt。

画面依赖按原生 Renderer 实际读取路径冻结，包括 timeline、编译字钟音频、封面、引用的绘制
PNG/NPZ/分层图、overlay 的完整原生 PNG 序列、背景、笔/手、水印及已有水印位置计划，
以及原生动态计数器实际加载的字体。动态文件必须位于当前 Job 内；解析 symlink 后越界也拒绝。
官方固定 vendor 资源由完整冻结源码校验负责，不重复逐资源建立另一份来源证明。
在 Renderer 打开文件前先检查范围；原生水印计划准备后、画面 QA/渲染前保存实际输入描述符，
渲染后核对未变。publish/inspect 继续核对同一份依赖，任何引用帧变化都会拒绝消费。
原生可写的 out、watermark-plan 和 review 路径先检查留在当前工程内，目录、文件和已有子项均
拒绝 symlink；只读 vendor 资源豁免不适用于这些写入位置。此检查在任何原生写入前执行。

复制旧原生工程时，不能直接复用含旧绝对 `directory` 的 web-motion `frames.json` 缓存。
应在新工程省略该生成缓存，让官方 build 在当前 Job 重新生成原生序列；不修改旧 timeline 或
改写第三方缓存来伪造归属。动态计数字体等外部输入也须先合法导入当前 Job，再交给原生公开参数。

录音窗口从真实 `voice_start_seconds` 开始。保留原生画面、镜头、笔顺、转场与词钟。
结果显式声明 `native_captions=true` 和 `subtitle_owner=sweety_native`。该窗口的普通字幕由原生画面
唯一承担；父级保留用户原声并抑制同句重复字幕。其他窗口仍使用父级字幕轨。
`Renderer.view(include_captions=False)` 只支持单页视图；完整 frame/scene/blend 没有全局无字幕参数。
因此当前不关闭原生字幕，不裁画面、不删除 timeline、不改第三方、不 monkeypatch。

### 真实录音末尾的普通整理

默认导入只作原生所需的48kHz重采样。原16kHz音频不改写，原描述符及SHA继续绑定父级事实。
校验把原音与原生master统一到同一48kHz PCM时钟，核对同一时长、原词钟和完整实际命令。
若真实停顿底噪导致原生尾巴保护失败，可显式使用
`prepare_narration(..., tail_fade=True)` / `--prepare-narration --tail-fade`：仅在最后一个真实词锚
结束后的既有停顿中淡出，并为原生保留最后 0.12 秒静音。必须至少还剩 0.17 秒真实窗长；
空间不足直接拒绝，不加空白、不改总时长。淡出在重采样后执行，最后词锚以前的采样必须
与未淡出的同一48kHz标准化音频完全相同。

原始 `speech` 描述符仍绑定母片真实裁出的录音。原生 master 是另一个文件；
`parent-import-tail.json` 记录 raw/processed SHA、真实原音副本、原词钟哈希、完整 FFmpeg argv
及处理区间。inspect/load 重新核对帧数、原音、受限处理区间、说话采样不变和实际滤镜结果，
不接受重采样及该限定淡出以外的滤镜、任意降噪或重配音。不得把这个 master 宣称为原样音频。
原48kHz资格样片的旧执行记录保留历史原状，不迁移或重签。

## 普通运行依赖

使用预装 Python 3.12 执行 `run.py prepare --dependency-id sweety-handdraw-video`，
仅向项目内 `runtime/handdraw-python312/` 补充锁文件 `handdraw-python312-requirements.txt`
中缺失的普通包；已有版本不符时停止，不覆盖其他 Pillow 环境。
该选中准备链复用现有 Playwright 准备入口，使用已有浏览器，缺失时仅按该入口的明确准备步骤补齐，
不要求先选择 Barty。`scripts/sweety_native_runtime.py` 只检查该环境与
`runtime/motion-native-playwright-1.64.0/browsers`，不会在渲染时隐式下载。
所有运行设置 `PYTHONDONTWRITEBYTECODE=1`，不向 vendor 写缓存。
FFmpeg/ffprobe 复用本项目运行目录。只准备 Pillow、numpy、scipy、requests、fonttools、
pypinyin、jieba、Playwright 等普通依赖；没有安装 TTS、ASR、torch 或模型权重。

运行例：

```text
PYTHONPATH=<包根>/runtime/handdraw-python312
PLAYWRIGHT_BROWSERS_PATH=<包根>/runtime/motion-native-playwright-1.64.0/browsers
PYTHONDONTWRITEBYTECODE=1
python3.12 -B <包根>/scripts/sweety_native_runtime.py --check
```

## 当前来源资格样片

独立样片位于工作区 `capability-samples/20261104-library-expansion/sweety/`。
`webmotion-sample.json` 记录实际原生中文动效、PNG 输出、ProRes 媒体探针、解码后的 alpha 和看图结论。
透明样片完成不等于 21 种画风全部逐一实测，更不等于用户接受任何正式成片。
正式 Job 消费与完整画风样片状态以各自真实结果记录为准。

本次透明路径已实际完成原生 PNG→ProRes 4444→完成结果描述符→冻结 FD 消费，消费后媒体与
原生编码结果逐字节一致。该资格样片没有生产 Job 或用户语义审批，不冒充用户成片验收。

完整 draw 技术样片使用官方未改 `smoke_test.py` 生成的清线 fixture，保留原生 17 号选择、
美术/绘制记录、完整 build/render 和真实旁白/词钟。它已经实际渲染；最终 `verify` 被上游
音轨门禁阻断，未 finalize、未 publish 为已通过的原生成片。图标题材不作当前口播语义验收。

### 历史有声成片阻断与当前产品边界

历史 `style-17-native-final` 完整影片的上游音轨检查失败，原工程、输出和失败记录保持原状。
它没有 finalize，也没有被重签为通过。诊断在 `native-final-audio-diagnosis.json`。
`--assets-only` 不是完整影片检查的替代；本次用户明确要求无声画面，交付物改为原生视觉素材，
因此只调用该产品实际需要的原生视觉与时钟检查，不要求生成或验收不交付的整片音轨。

新无声资格样片另存独立目录；从已有工程复制真实输入与构建缓存，新的导入、构建、检查、
render_chunk 调用和完成结果均记录本次真实执行。原始技术图来自官方离线 smoke fixture，
它只证明接口、原生逐笔绘制、字幕时钟和无声消费链；不代表当前口播主题语义或用户美观验收。

旧无声样片 `silent-visual-20261104/` 保持原状。后续只读审查发现其原生 overlay 缓存沿用了
样片根外原工程的145张 PNG，旧接入没有绑定这些帧；因此它不能作为资源隔离通过的证据。
本次新独立工程为 `silent-visual-isolated-20261104/`，原生 build 在当前工程重建 overlay 缓存，
实际检查与消费结果以该目录新增记录为准。保留原生绘制偏赶警告，不据此认定主题美观已通过。
