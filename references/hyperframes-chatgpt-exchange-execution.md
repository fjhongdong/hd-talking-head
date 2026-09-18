# 原生 ChatGPT Exchange 执行接口

仅当已批准的 `code_generated` 组件选中 `hyperframes/chatgpt-exchange` 时加载。本接口用于“提出问题 → 流式回答 → 四项对照表 → 回读结论”的表达，不把任意对比、流程、官方资料或数字图表强行套进聊天界面。

## 支持边界

- 使用归档的 HyperFrames 原生 `chatgpt-exchange.html` 与字体资产；中文字符揭示、中文标点、字体回退和表格宽度属于已实测的 `adaptation_level=content_reflow`，不是按截图重画。
- 只支持 `ai_dialogue_comparison`、`four_factor_comparison`、`prompt_to_table`。信息单元必须恰好为 4，`numeric_values=[]` 且 `numeric_scale=not_applicable`。
- 固定叙事顺序为：问题进入、两段回答展开、四行三列表格出现、四个 chip 强调、完整答案回读。不能删行、加行、改为数值图表或重排时间轴后继续沿用当前验证身份。
- 原生合同固定为 1080×1920、24fps、358 帧、14.916667 秒、H.264/yuv420p、无音轨。模板最终状态保持到结束；切回 A-roll 由共享合成器执行 8–12 帧 alpha，不在模板内部制造退场。
- 22 个内容字段必须全部显式提供：`prompt`、`intro1`、`intro2`、3 个表头，以及 4 行各自的 `Use / Tool / Why / Chip`。包装器逐字段执行已验证中文字符容量，不自动缩字、截断、补空卡或使用上游示例。
- ChatGPT 应用外壳、输入栏与界面身份属于模板固定结构。当前内容不适合聊天问答语境时排除本模板，不通过结构改造隐藏界面后冒用资格。

## 配置与真实调用

新任务环境确认必须提供：兼容的 `edit/hd` 项目运行时、Python、Node、本地 Chromium、FFprobe，以及固定 HyperFrames checkout 的绝对路径。本机资格版本为仓库提交 `0fd70b1d2165d6ac9f4199bfafa9f22c711bfc8f`、`@hyperframes/cli` 0.8.19；渲染固定 `workers=1`、`low-memory-mode`、`strict`、`strict-variables`、关闭浏览器 GPU 与 best-effort。

在已配置项目模块路径的新 Python 进程中加载 `<skill>/scripts/hyperframes_chatgpt_exchange_adapter.py`：

```python
adapter = create_adapter(
    runtime_root=hyperframes_root,
    node_executable=node_path,
    browser_executable=chromium_path,
    brief_loader=load_current_job_brief,
)
binding = create_binding(adapter, approved_brief_bytes)
probe = create_artifact_probe(ffprobe_executable=ffprobe_path)
```

`load_current_job_brief(job, recipe, component)` 返回当前 Job 内已确认 brief 的原始 UTF-8 JSON 字节。普通任务只使用活动 `references/verified-template-registry.json`；`qualification/source-registry.json` 只供模板维护实验显式传入，不能自我授予生产验证身份。

把 adapter 放入 `adapters["code_generated"]["hyperframes"]` 后调用 `broll_component_executor.execute_component`。组件必须使用 `executor=reference_adapter`、`media_type=animation`、`artifact_contract.alpha=false`，render window 必须正好为 358 帧。新计划保持 `invocation_record.status=planned / exit_code=null`；PID、退出码、输入、入口、renderer 与输出哈希只读取执行器自然生成的回执。

## brief 结构（仅结构示意）

```json
{
  "schema_version": 1,
  "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 358},
  "template_request": {
    "semantic_family": "prompt_to_table",
    "information_units": 4,
    "numeric_values": [],
    "numeric_scale": "not_applicable"
  },
  "props": {
    "data": {
      "prompt": "学会AI后怎样真正提升工作",
      "intro1": "真正拉开差距的不是会不会调用模型，而是能否进入真实工作场景。",
      "intro2": "可以从四个维度判断AI能力有没有真正落地：",
      "tableHeadUse": "判断维度",
      "tableHeadTool": "关键动作",
      "tableHeadWhy": "为什么",
      "row1Use": "业务目标",
      "row1Tool": "先定问题",
      "row1Why": "把模糊需求转成清晰取舍",
      "row1Chip": "决策依据",
      "row2Use": "协作流程",
      "row2Tool": "统一上下文",
      "row2Why": "让上下游围绕同一结果推进",
      "row2Chip": "团队习惯",
      "row3Use": "行业规则",
      "row3Tool": "识别边界",
      "row3Why": "知道哪些判断不能交给模型",
      "row3Chip": "隐性知识",
      "row4Use": "结果复盘",
      "row4Tool": "持续修正",
      "row4Why": "用真实反馈改流程而非只换工具",
      "row4Chip": "长期积累"
    }
  }
}
```

示例只说明结构，不是生产文案或事实。实际字段先通过内容提炼人工门；任一字段变化都会形成新的 brief 哈希与 revision。

## 当前 Job 验收

历史资格证明两组不同的 22 字段输入由同一原生入口生成了不同 MP4，并完成了进入、稳定、结束三态人工检查；它不批准当前内容。每个新 Job 仍须检查：问题与回答的揭示顺序、四行表格和 chip 的语义对应、完整回读状态、中文字体回退、无越界/重叠/截断、固定 ChatGPT 界面是否适合语境、头像与安全区，以及通过共享 alpha 自然返回 A-roll。失败时进入当前 revision，不交付资格样片，也不改结构继续沿用验证身份。
