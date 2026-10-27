# Lemo-Opuscar 原生接入

Lemo 使用官方 vendor `lemo-opuscar@413a6bd6d78ebd3bdd5abaec9538a26867f890df` 的 59 个独立 styles。能力库身份统一为：

```text
渠道：lemo-opuscar
模板：lemo-opuscar/<style_slug>
标签：来自所选 STYLE.md 的 subjects/actions/relations/feelings/styles/patterns
```

完整读取 `plugin/skills/lemo-opuscar/SKILL.md`、`AGENTS.md`、`DIRECTOR.md`、`TECHNIQUE.md` 和所选 `styles/<style_slug>/STYLE.md`。先写本期 TREATMENT，再按所选 STYLE 的原生动作制作本期场景（demo 只作技术参考）；第三方文件不改，不拆源码，不重写引擎。输出固定为 1080×1920、24fps、无声整屏 B-roll。登记 59 条不代表每个主题都已完成成片验收，仍须对当前主题、真实输入和最终像素逐项检查；纪实风格必须先匹配用户提供或合法授权的真实材料，不得用假数据代替。

## brief

实际字段由 `scripts/upstream_scene_adapter.py` 校验，最小结构如下；不要增加未被校验的字段：

```json
{
  "schema_version": 1,
  "dependency_id": "lemo-opuscar",
  "source_binding": {
    "aroll_sha256": "<64位sha256>",
    "segment_id": "seg-example",
    "start": 12.0,
    "end": 18.0
  },
  "template_request": {
    "semantic_family": "按本期语义填写",
    "information_units": 2,
    "numeric_values": [],
    "numeric_scale": "not_applicable"
  },
  "composition": {"id":"lemoScene","width":1080,"height":1920,"fps":24,"frames":144},
  "files": [
    {"media_ref":"scene","job_path":"scene/index.html","scene_path":"index.html","sha256":"<64位sha256>"},
    {"media_ref":"workflow","job_path":"scene/workflow.json","scene_path":"workflow.json","sha256":"<64位sha256>"},
    {"media_ref":"treatment","job_path":"scene/TREATMENT.md","scene_path":"TREATMENT.md","sha256":"<64位sha256>"}
  ],
  "workflow_media_ref": "workflow",
  "style_slug": "<官方styles目录中的slug>",
  "creative_handoff": {
    "transcript":"当前剪后原话",
    "semantic_goal":"观众需要理解的语义",
    "required_change":"必须看见的变化",
    "subject":"主体对象",
    "visual_pattern":"所选STYLE的原生表现模式",
    "design_plan":{"composition":"构图","typography":"文字","finish":"质感","focus":"焦点"},
    "beats":[{"time":0.0,"action":"首个原生动作"}],
    "forbidden_outcomes":["不得提前展示后文结论"]
  }
}
```

Lemo 的 `files` 为 3–8 个本地冻结文件，路径必须是相对路径；必须包含本期 TREATMENT，可加入脚本和本地素材，但总量不超过 8 个。workflow 需记录所选 style、TREATMENT、完整 `design_plan` 以及五份原生指引和所选 STYLE 的哈希。调用前后都核对 style 身份、输入文件、帧数、无声状态和真实画面；只通过 brief 或 renderer 检查不能宣称成片通过。

## 执行边界

1. 语义列表先独立确定，再从 59 个模板中匹配；模板选择同时看原生动作、关系、主体和真实可编辑内容。
2. 选中后读取当前 STYLE 与导演指引，按本期 TREATMENT 制作主题专属场景；主题变化不新增模板身份。
3. 纪实、调查、数据类风格必须绑定实际来源和授权材料，事实、数字和引用逐项核对。
4. Lemo 只作为整屏无声 B-roll，不进入 A-roll 贴片候选；不因本地没有素材而伪造事实。
5. 实际调用仍须通过对应原生执行能力；只新增索引、标签或文档不能视为接入完成。

本次独立接入样片与原始创作文件位于 `assets/lemo-native-smoke/`。它从统一标签选中瑞士排版模板，经公共 `execute_component` 调用官方 `core/render/video.mjs`，实际输出 144 帧、1080×1920、24fps、无声视频；原生阅读时长检查覆盖 12 项文字。该样片不修改现有成片，也不代表其余风格的每种主题都已逐一出片。

正式执行器以标准输入运行冻结的包装入口，适配器显式绑定 `--skill-root` 后定位包内依赖；场景文件继续通过受控文件描述符传入。后续接入同样验证公共执行器的实际路径，不用直接运行 renderer 或通过 `--probe` 代替真实试片。
