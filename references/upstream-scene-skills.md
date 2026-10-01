# 上游场景 Skill 与本地渲染合同

本合同把父 Skill 的边界固定为：理解语义、选择并编排镜头、冻结批准素材、验收静帧与成片、合成 A-roll 小窗和唯一字幕轨。父 Skill 不重写上游动画引擎，也不把“参考过仓库”写成“调用过 Skill”。每个新场景必须先读取上游完整 `SKILL.md` 及所选 DIRECTOR、TECHNIQUE、STYLE（或 composition/motion/look）指引，再按上游工作流制作 source，最后才允许本地 runner 渲染。

## 选择与资格

先按 `semantic_match_score`，再按 `quality_score` 排序；同分才比较 `template_origin`，最后比较 `reuse_gap`。来源资格仍是硬门，不能替代语义或美术判断。`verified_third_party`、`verified_local_canonical`、`custom_fallback`、`structural` 是资格描述，不是语义替代链。新的自由场景即使使用开源代码，也不能冒充 `verified_third_party`；记录 `producer_type=dependency`、`dependency_id`，自研时如实记录新增实现。现成动画优先，只有上游能力确实不足且已记录缺口时才允许最小自研。prompt 库只能提供提示词参考，不能充当制作依赖。

保留既有边界：HyperFrames 负责透明 A-roll/轻组件，TalkCraft 负责精确数据，Doudou 负责白板与思维导图，Paper 负责拼贴分层，Lovart Kling O1 负责已批准的场景动作。它们都是实际调用入口，不互相借用 producer 身份。父级仍统一处理圆窗、原口播和全片唯一字幕；场景输出无声、整屏、1080×1920。

## 本地依赖与固定来源

新增本地依赖仅允许：

| dependency_id | upstream_commit | 原生入口 |
| --- | --- | --- |
| `lemo-opuscar` | `f3c590dffab39419e2f3018416706e046986fe11` | `node core/render/video.mjs <scene>` |
| `onetake` | `cf09bde3e392c9aa32c4157f80cdbe1fa556685e` | `.venv/bin/python scripts/render.py index.html` |

依赖由 `ensure_visual_broll_skills.py` 在项目本地自动准备，脚本内固定 render 包版本；禁止全局安装、worktree 共享、自动更新或运行时联网拉取。Lemo 复用项目 Chrome，不运行自动 reset/setup；OneTake 使用项目 Python 3.12。两套依赖必须同时登记到正式 executor 与 `visual_plan`，运行时不支持即停止，不能只带 Skill 文件声称跨机器可执行。

本地适配合同由 `scripts/upstream_scene_adapter.py` 实现，原生 runner 由适配器调用（API 优先，CLI 仅用于探测和真实执行）：

```python
create_adapter(project_root, dependency_id, python_executable, brief_loader)
create_binding(adapter, brief_bytes, reference_sample)
create_artifact_probe(ffprobe)
```

`dependency_id` 仅允许 `lemo-opuscar` 或 `onetake`；`primary_renderer=HTMLCanvas`；适配器版本为 `1.0.0`。CLI 支持真实 runner 及本地探测：`--probe --project-root ROOT --dependency-id ID`。

创建 binding 后登记到 `component_adapters["code_generated"][dependency_id]`，并接入现有 artifact probe/执行链；不得另起旁路渲染器。

## brief 与 workflow

`brief` 固定为 schema 1，字段如下：

```text
source_binding={aroll_sha256,segment_id,start,end}
template_request
composition={id,width:1080,height:1920,fps:24,frames}
dependency_id
files=[2..8 个冻结 Job 相对文件]
workflow_media_ref
```

每个 file 写 `media_ref/job_path/scene_path/sha256`，并覆盖 `index.html`、`workflow.json`、本期 JS、字体和素材；依赖 core 资源只引用固定 upstream。`workflow.json` 必须锁定 `dependency_id` 和 `upstream_commit`，写出真实选择路径列表、concept、beat_sheet、`upstream_features`（原库路径或 style 函数及说明）以及实际静帧 QA；不能只写“已调用”。

## 原生 runner 与探针

Lemo-Opuscar 使用：

```bash
node core/render/video.mjs <scene> --size 1080x1920 --fps 24 --workers 1 --out <output>
```

成功必须观察 `READY`、`render` 和 `DUR`。OneTake 使用：

```bash
.venv/bin/python scripts/render.py index.html --width 1080 --height 1920 --fps 24 --dur <秒> --workers 1 --out <output>
```

成功必须观察 `__ready`、`__seek` 和 `__meta.dur`。两者均为无声整屏输出；仅 OneTake 保留 180 度快门；不硬编码人物或配音，不自动付费。适配器只冻结 source 与依赖身份，不自行改写场景语义。

原生执行必须保留 frameclock 与无声守卫。`workflow.json` 中的 feature path、symbol、usage 必须能在本期实际 source/code 中对账；OneTake 还须保持原生 `motion.js` 字节一致。QA 只记录实际静帧审阅，不把 QA 记录写成已 render 或 smoke 成功。

开发调用验证：Lemo 与 OneTake 各有一条真实 executor smoke，均输出 1080×1920、24fps、144 帧、6 秒、无声；这只是开发调用验证，不是新正式 Job 全流程。Lemo 实测 JPEG 输出为 fullrange `yuvj420p`，适配器须做真实 fullrange→limited `yuv420p` 颜色转换并核对 SAR 1:1，不得只改标签，也不得缩放、retime 或 loop。OneTake 保留原 180 度快门，不重编码，仅允许写入 SAR 元信息。两者画风不同，开发样片不是永久模板；旧 Job 不变。

## 阶段与兼容边界

继续沿用 full-v2 十二阶段、批准素材和状态级联。旧 Job 不重签、不迁移为新依赖；新依赖只进入新 revision。渲染前父级必须确认 source、依赖提交、brief 哈希和静帧实际审阅；渲染后再检查尺寸、帧率、帧数、无声、动作前中后和 source_binding 时钟。任何一项缺证据就停在当前阶段，不能用历史样片、目录存在或成功退出码代替真实验收。
