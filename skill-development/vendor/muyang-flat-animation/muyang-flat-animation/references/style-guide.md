# 沐阳视觉风格指南

## 视觉基准

本 Skill 的固定画风是“纸上钢笔线稿 + 选择性彩铅填色”的编辑插画，不是光滑的企业矢量扁平图。开源仓库不附带第三方参考插画。用户可将自己拥有使用权的图片放入 `assets/references/` 并命名为 `style-reference-*.png`；这些图片只能用于学习媒介、线条、质感、留白和图解语言，不得复制具体人物、物件、构图或配色。

人物不是画风必要条件。`character` 模式可有人物，`content-only` 模式只用与主题直接相关的场景、物件和关系图，同样保持以下视觉签名。

## 不可丢失的画风签名

- 暖白、象牙白或浅米色的非涂布纸底；默认可见极淡方格纸纹，也可按主题使用无格纸纹。
- 黑色或炭黑钢笔/针管笔轮廓，线宽有轻微变化，边缘带自然手绘抖动和重复描线。
- 彩色区域采用彩铅、蜡笔或干性马克笔般的颗粒笔触；只选择性填色，保留大量纸白，不做无缝满铺色块。
- 头发、衣物暗部、建筑或承重结构可使用疏密不一的排线、交叉线和涂鸦式黑色阴影。
- 物件真实可辨但经过编辑式简化；允许轻微不对称，不追求工程制图般规整。
- 构图重视大面积留白和一个清晰视觉命题。箭头、虚线轨迹、圆形注释框、星点、短线和手绘色块仅在表达关系时使用。
- 色彩不固定。按主题自动选择 2–4 个强调色；颜色负责信息层级，不承担画风身份。

## 构图语言

- 优先使用一个与原句直接相关的真实桌面、工作场景、主题物件或清楚流程；平衡关系和中心隐喻只作辅助，避免仪表盘式模块拼装。
- 只保留 3–6 个语义组；每组应是可识别的物件、微场景或符号组合，不是抽象硬几何占位块。
- 内容可视化可以使用圆框、路径或卡片，但框只是组织关系，框内必须是具体图形化内容。
- 人物模式中，人物动作自然克制；无人物模式不得因为参考图含人物而自动补人、手、脸或剪影。
- 为短视频字幕或后续合成保留明确负空间；固定机位下各语义组轮廓相互分离，方便局部动画。

## 视觉命题的直观度

- 先画“主题是什么”，再画“主题意味着什么”。例如“做自媒体发现潜力”应先出现摄像机、麦克风、脚本、作品或发布流程，再用逐渐增加的技能成果表达潜力；不得只画石头裂开露出水晶。
- 主题物件至少占核心语义组的一半。通用符号不能喧宾夺主。
- 允许箭头、虚线、圆框和色块组织关系，但它们不能成为主体。
- 使用参考图的表达方式：一个真实场景或主体物件，加 2–4 个具体结果/步骤，以克制路径连接；大量纸面留白保持可见。
- 避免可套用于任何主题的通用隐喻：灯泡、火箭、迷宫、钥匙、山峰、种子、晶体、齿轮、拼图。只有当它们是主题中的真实对象或用户指定时才可作为主体。

## 静帧生成时使用参考图

生成 Gate 2 静帧时，如果用户提供了有权使用的 `assets/references/style-reference-*.png`，将其中 2–5 张最相关图片作为 **style-only references** 输入图片工具。明确告诉模型：只继承纸面、钢笔线、彩铅颗粒、排线、留白和编辑图解语言；不得复刻参考图人物身份、具体布局、物件或色板。没有参考图或工具不能传参考图时，使用下面的完整文字描述。

```text
Create a finished editorial illustration on warm ivory uncoated paper, optionally with a very faint square notebook grid. Use imperfect black fineliner contours with slight line-weight variation, occasional double strokes, sparse cross-hatching and scribbled ink shadows. Add selective dry colored-pencil or crayon fills with visible grain, leaving substantial paper unpainted. The subject must be recognizable, simplified and pictorial rather than built from rigid corporate geometry. Compose one clear visual metaphor with generous negative space and only semantic hand-drawn arrows, dotted paths, circular callouts or small accent marks. Subject mode: [character or content-only]. [Concrete visual proposition]. Choose 2–4 accent colors freely according to the topic; do not copy the reference palette. Fixed composition, stable separated silhouettes, no text. If content-only: absolutely no people, hands, faces or human silhouettes. Avoid smooth SVG/vector art, uniform outlines, full-bleed flat fills, gradients, glossy 3D, photorealism, watercolor wash, UI dashboards, logos and watermarks.
```

## Gate 2 画风验收

静帧只有同时满足以下条件才可提交确认：

- 放大看得到自然墨线变化和干性上色颗粒，不像自动描边的 SVG。
- 至少一半以上画面仍能感到纸面与留白，彩色不是所有对象的满面积塑料平涂。
- 主体由可识别物件或场景承担语义，不依赖生硬圆角矩形、圆柱、积木块或 UI 面板。
- 排线和装饰克制，层级清楚；没有变成写实素描、水彩画或儿童卡通。
- 配色服务主题且可自由变化，没有因为参考图而强制蓝橙色。
- 人物仅在 `subject_mode: character` 时出现。
- 遮住口播文字后，画面中的物件仍能让人判断主题类别；不得依赖解释才能把通用隐喻映射回原句。
- 构图、线条密度、局部彩铅着色和留白比例与正式参考图属于同一视觉家族，而不只是背景有纸纹。

## 禁止偏移

- 禁止光滑企业矢量、统一粗描边、几何积木、塑料平涂和渐变高光。
- 禁止照片拼贴、剪纸阴影、3D 渲染、写实摄影、厚涂水彩、日漫赛璐璐。
- 禁止把“简约”理解为空洞图标，把“图形化”理解为机械 UI 模块。
- 禁止为了贴近参考图而固定人物、蓝色衣服、蓝橙配色、方格纸或同一构图；这些都是可变内容。
- 禁止用无语义的箭头、星点和涂鸦填满负空间。
