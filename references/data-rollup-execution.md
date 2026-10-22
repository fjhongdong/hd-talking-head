# 原生 DataRollup 执行接口

仅当已批准的 `code_generated` 组件选中 `html-video/frame-data-rollup` 时加载本文件。不把所有文案强行变成柱状图，也不因为这个模板能运行就替换其他已批准设计。

## 支持边界

- 原始第三方源码来自本包 registry，保持原始构图和逐柱生长、数字滚动动效；封装不是另画一个相似模板。
- 输入必须是 3–8 个同口径、非负、安全整数。小数、负值、过大整数或最大正数达到最小正数 50 倍时拒绝，避免原模板静默舍入或转对数刻度。不要为通过检查改数字、凑条目或编造事实，应重新选择适合当前语义的模板。
- 明确提供标题、标签、单位（可为空）及三种颜色；不使用模板自带 GitHub 示例数据。标题、标签、数值和单位先做保守宽度估计，过长直接返回问题，不自动缩字、裁掉或改写文案。
- 原生 1080×1920、24fps、H.264/yuv420p、无音轨，至少 72 帧，让最后一根柱完成入场后有阅读时间。内容较多时依据文案延长，不能把最低帧数当作推荐时长。
- `exit_policy=external_compositor`：组件末段保持稳定，淡出由正式合成器统一处理，不额外添加相机复位。这里不包含口播、小头像和最终转场。

本接口的原始模板身份仍以 registry 的源码哈希为准；历史 30fps 样片不能充当本次 24fps 产物。

## 配置与真实调用

宿主在新任务的环境确认中提供：兼容的 `edit/hd` 项目运行时、Python、Node、已安装的 Remotion runtime 目录、本地 Chromium 和 FFprobe 的绝对路径。封装不安装依赖、不使用 `npx` 下载、不调用付费 provider。本机验证版本为 Remotion / renderer / bundler 4.0.520；三者必须同版本，其他版本仍要重新跑本接口实测和本次 canary。

在已配置项目模块路径的新 Python 进程中加载 `<skill>/scripts/data_rollup_adapter.py`：

```python
adapter = create_adapter(
    runtime_root=runtime_root,
    node_executable=node_path,
    browser_executable=chromium_path,
    brief_loader=load_current_job_brief,
)
binding = create_binding(adapter, approved_brief_bytes)
probe = create_artifact_probe(ffprobe_executable=ffprobe_path)
```

`load_current_job_brief(job, recipe, component)` 返回当前 Job 内已确认 brief 的原始 UTF-8 JSON 字节。不要从 Skill 目录读取用户内容。`binding` 冻结到当前 `source_bindings`，由正式计划编译器形成 ShotRecipe，经当前人工门批准后再执行：

```python
artifact = execute_component(
    job,
    ComponentExecutionRequest(recipe=approved_recipe, component_id=component_id),
    adapters={
        "code_generated": {"html-video": adapter},
        "artifact_probe": probe,
    },
)
```

组件为 `executor="reference_adapter"`、`media_type="animation"`、`artifact_contract.alpha=false`。brief 的帧数必须等于组件 `end_frame-start_frame`。调用前的 `invocation_record` 使用 `status="planned"` 和 `exit_code=null`；这是计划，不是执行成功。只有输出的 `artifact.invocation_evidence` 能证明实际进程、退出码、源码与输入哈希、渲染引擎和产物身份。不要提前填 `exit_code=0`，也不要手工捏造运行证据。

执行器将入口源码通过 stdin 交给 Node，brief 和输出通过继承的文件描述符传入。包装器复核登记源码，将同一份已验字节复制到私有临时目录打包，显式传入真实 `inputProps`。单浏览器、单渲染 worker、顺序编码，结束后关闭浏览器并清理本次临时目录。生成的 MP4 经真实 FFprobe 检查再由执行器发布；同配方、同输入的成功结果复用既有字节和调用证据。

## brief 结构（仅结构示意）

```json
{
  "schema_version": 1,
  "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 96},
  "template_request": {
    "semantic_family": "bar_chart",
    "information_units": 3,
    "numeric_values": [2, 5, 9],
    "numeric_scale": "linear"
  },
  "props": {
    "data": {
      "title": "模板测试 A",
      "unit": "项",
      "items": [
        {"label": "流程一", "value": 2},
        {"label": "流程二", "value": 5},
        {"label": "流程三", "value": 9}
      ]
    },
    "accent": "#FF5A2C",
    "background": "#0E0E10",
    "foreground": "#F5F5F2"
  }
}
```

以上为虚构测试数据，不是生产文案或商业事实。`template_request.numeric_values` 必须按顺序逐项等于真正的 `props.data.items[].value`；信息单元数也必须相等。整个 brief 的哈希绑定标题、标签、单位、颜色与数据，修改任何一项都要形成新的 revision。

## 检查与维护

低成本预检（不启动渲染）：

```bash
node <skill>/scripts/render_data_rollup.cjs --validate < <current-job-brief.json>
```

维护时才运行 `tests/render_data_rollup_integration.py`，显式传入 `--project-root`、`--runtime-root`、`--node`、`--browser`、`--ffprobe`、`--output`。它用两组标明为虚构测试的数据，通过正式 `execute_component` 串行渲染并核对重复调用复用；不创建真实用户任务，不代表任何人工批准，不替换历史用户成片。测试失败保留证据，使用新的测试目录，不覆盖旧结果。

两组既有原始产物已随包保存在模板 `qualification/` 下，登记校验器通过 `execution_qa` 强制核对，细节见 [双输入实测资格](template-qualification.md)。它保留执行时的旧登记快照，不改写旧回执以匹配新验证 ID。入口或原生源码变化须重新实测；未变化时只读复核即可，不重复渲染。资格帧核验另需要 FFmpeg，用真实 RGB 像素匹配 MP4 的相应帧，而非只信截图文件名。

当前内容仍必须逐一核对入场、稳定、退出三态：文字是否完整、数值是否真实、字体实际回退是否改变布局、条目是否同口径、阅读时间是否足够。宽度估计不是像素级排版验收。最终组合后再检查头像安全区和 A-roll 转场；组件测试成功不能代替完整成片审核。
