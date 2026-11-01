# 无人物内容可视化模式

## 目标

制作可直接插入知识讲解短视频的独立视觉素材。通过物件的归类、排序、连接、对比、筛选、递进或因果转化解释主题、关系、过程和结果，不出现人物、手、脸、身体剪影或角色化物件。

无人物不等于抽象化。优先使用主题中的真实工具、产品、工作台、内容成果和流程节点，让观众先看懂“在讲什么”，再看懂关系或变化。

## 适用结构

- 转化：抽象碎片 → 清晰实体
- 筛选：杂乱输入 → 漏斗 → 少量关键结果
- 连接：孤立节点 → 路径 → 网络
- 生长式显现：从固定起点按内容结构逐段生成，例如路径、网络、图表、建筑、产品轮廓或植物
- 组装：基础结构 → 核心部件 → 连接件 → 完成物
- 对比：混乱与清晰、旧与新、分散与集中
- 循环：输入 → 处理 → 输出 → 反馈

## 构图规则

- 使用 3–6 个大组，避免满屏小图标。
- 让核心关系在静帧中无需文字也能读懂。
- 为短视频字幕预留负空间；默认将动作主体放在中央偏下或一侧。
- 使用物件本身的运动表达因果，不使用一只“解释性的手”。
- 避免真实软件界面、按钮文字和假数据；需要界面概念时改用无字卡片和几何占位。
- 至少 2 个核心物件必须直接来自原句主题，不能全部替换为石头、晶体、灯泡、齿轮、拼图、种子等通用隐喻。
- 优先贴近正式参考图的编辑图解语法：真实可辨的物件线稿、少量局部彩铅、克制圆框或虚线路径、大片纸面留白。

## 动作规则

- 每个阶段有一种清楚的主要变化，但允许相关物件以 0.15–0.45 秒错峰接力响应，不必等前一动作完全停住。
- 物体沿清楚的直线、弧线、轨道或结构路径运动。
- 采用“主结构变化 + 相关物件接力响应 + 局部状态强调”的分层节奏。生命感来自物件自身：卡片滑入、图标轻抬回落、节点依次激活、色块沿结构填充、叶片或柔性物件轻摆。
- 生长式显现从固定起点按对象自身结构展开；组装按承重结构到细节；筛选按输入到输出。禁止用整体缩放或淡入代替生长。
- 连接线数量服从静帧已确认的关系；每条线必须连接明确对象。允许沿既定路径接力描出，禁止悬空线、随机分叉或在负空间自行游走。
- 最后 0.5–0.8 秒保持清晰结果态；局部低幅动作可以自然收束，便于剪辑点和转场。
- 禁止随机漂浮、装饰性弹跳、全画面呼吸缩放和没有语义的粒子。

## 静帧提示词补充

```text
Subject mode: content-only B-roll visualization. Show no people, no human figures, no hands, no faces, no body silhouettes and no character-like objects. Communicate the idea entirely through 3–6 clear objects, their spatial relationship and one readable transformation. Reserve clean negative space for short-video captions. No text or UI.
```

## 视频提示词补充

```text
Animate only the named content objects and approved connection paths. Never introduce a person, hand, face, body silhouette or character. Keep the canvas, paper texture, object identity, palette and negative-space layout locked. Use one readable primary transformation with staggered responses from related objects, then keep the completed result clear through the end.
Use layered knowledge-explainer motion: one primary semantic transformation, related object responses offset by 0.15–0.45 seconds, and brief object-attached emphasis. Do not freeze every non-primary object and do not add free-floating decorative motion. Use sparse synchronized action sounds but absolutely no pencil writing, pen scratching, marker rubbing, drawing-on-paper, scribbling or scraping sounds.
```

## Gate 1 输出差异

把“人物动作”替换为：

- 核心物件动作
- 结构变化顺序
- 连接/结构生长/筛选路径
- 为字幕或口播画面预留的负空间位置
- 主题直观度：列出直接对应原句的主题物件；若没有至少 2 个，先重做方案
