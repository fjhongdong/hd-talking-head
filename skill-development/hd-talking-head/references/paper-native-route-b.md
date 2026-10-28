# Paper：完整原生 Skill，Route B

创作渠道统一为 `paper-collage-ad`；`paper-collage-hyperframes` 是 Route B 的执行依赖身份。`paper-collage-ad/hyperframes` 是完整上游 Skill 的 Route B 工作流。HyperFrames 是原生工作流指定的执行器，不另算渠道。上游固定为 `a69c9f56eec57ca19d1c02f6bdcffe573b4324a8`；不改上游文件，不把 `layer-animate.mjs` 当作完整 Skill。

## 原生准备

确认前，在现有 `prepare_template_inputs` 阶段调用桥的上下文入口：

```bash
python3 scripts/paper_hyperframes_adapter.py \
  --project-root <完整Skill包根> \
  --authoring-request <请求JSON>
```

请求只有：

- `output_directory`：新原生项目目录，必须为空或不存在。
- `source_binding`：原口播 SHA、segment_id、start、end。
- `composition`：width=1080、height=1920、fps=24、frames、alpha=false。
- `template_request`：现有语义合同；当前只接非数值解释。
- `transcript`、`semantic_goal`：已批准原话和表达目标。
- `assets`：已授权真实素材的本地绝对路径列表。
- `speech`：本段局部真实音频的 `{path, sha256}`；path 为绝对路径，摘要和实际单音频时长须匹配本段。独立无声样片显式传 `null`。
- `word_anchors`：本段 `0-duration` 的真实局部词时码列表，每项为 `{text, start, end}`；有父级语音时必须提供，保留原词序，不自动识别或重写。独立无声样片显式传 `[]`。
- `authorization`：父级现有授权对象，原样交给原生作者；当前只接受 `paid_generation:false`，本次样片为 `{"paid_generation": false}`。任何新增生成仍先走父级已冻结生成计划/队列及具体模型、次数批准，再把本地结果作为 assets 交入，不新增收费分支。
- `parent_subtitle_layout`：有父级语音时必须传正式 `subtitle_layout` 返回的实际 safe_zones 和 placement；独立无声样片显式传 `null`。

同名 Python 接口为 `authoring_context(project_root, *, output_directory, source_binding, composition, template_request, transcript, semantic_goal, assets, speech, word_anchors, authorization, parent_subtitle_layout=None)`。它返回可执行的 `execute_native_skill` 动作、完整 `SKILL.md` 路径、适用原生参考文件与摘要、原生 preflight 命令、Route B 和必要输入。当前宿主读取并执行这个动作。创意、构图、纸片编排和 GSAP 由完整原生 Skill 自主决定；父级不提供模板化动画代码，不规定额外的导演字段。

上游自身的脚本、故事板、风格等确认门沿用既有用户批准，不重复请求同一批准。新语义或新事实仍走正常确认。短时无声 B-roll 的时长和画幅来自批准片段。有父级口播时，原生作者读取本段真实音频、局部词时码和正式字幕区域，按原话与词锚创作；交付仍为 silent 视频，原口播、唯一字幕及整片混音由父级合成，原生任务不生成新声音。独立无声样片的 `speech:null / word_anchors:[] / parent_subtitle_layout:null` 不证明有声 Job 能力。

## 结果冻结与执行

原生作者完成可编辑 HTML 和全部本地素材之后，才形成真实 `schema_version=2` brief。brief 沿用共享 HyperFrames 的源时钟、请求、entry/assets、composition、upstream_route 和 source_pins 字段。`validate_brief(payload)` 额外要求 Paper Route B、不透明视频和真实位图素材；Paper 不受共享路线原有 4 资产数量上限约束，仍保留路径、摘要和重复身份校验。

`create_binding(adapter, payload, sample)` 生成当前真实输出绑定，原有 `custom_fallback/structural` 表示本 Job 按原生工作流新创作的场景，不声称存在上游预制模板。当前模板身份为 `paper-collage-ad-hyperframes-portrait-adaptation`，版本 `2.0.0`。

冻结后的输入通过既有 `ReferenceProcessAdapter` 进入确认和执行。`native_task(job, recipe, component, brief_path)` 可交接已冻结条目，但不在执行时改写已批准 HTML。桥通过标准输入启动，带显式 `--skill-root`，从继承的媒体文件描述符接收冻结资产，调用真实 HyperFrames CLI；保留源时钟、上游固定版本、运行时摘要、真实 argv、输出摘要和运动检测结果。工厂预检、正式执行均校验审阅后的共享入口摘要，不能仅在 render 时发现失配。

验收检查完整画面的语义、中文、纸质材质和动作关系，不能用无冻结告警代替视觉验收。样片单独保存在 `skill-samples/20261028-native-integration/paper/`，旧 Job 和旧成片不重做。

原生创作输入中的 `parent_subtitle_layout` 由宿主用正式字幕的同一 `subtitle_layout` 函数取得；有父级口播字幕时必须传入当前片段的真实预留区，原生作者自行安排完整画面避让。独立无字幕样片可明确传空，不把固定坐标作为所有影片的构图约束。
