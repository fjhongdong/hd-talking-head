# 原生 Notification Cascade 执行接口

仅当已批准的 `code_generated` 组件选中 `hyperframes/notification-cascade` 时加载。本接口用于“四个顺序里程碑、进展或交付检查点 → 一个结论”的两阶段表达，不把所有流程、关系或清单强行套成通知动画。

## 支持边界

- 使用归档的 HyperFrames 原生 `notification-cascade.html` 字节、背景与品牌资产；只替换模板公开变量，`adaptation_level=tokens_only`，不根据截图重画。
- 支持 `milestone_notifications`、`progress_sequence`、`delivery_checkpoints`，信息单元必须恰好为 4，`numeric_values=[]` 且 `numeric_scale=not_applicable`。
- 第一阶段四条通知依次进入并重排，全部退出后第二阶段显示结论卡。不能删节点、加节点、拉伸时长或改变两阶段结构后继续沿用当前验证身份。
- 原生合同固定为 1080×1920、24fps、336 帧、14 秒、H.264/yuv420p、无音轨。B-roll 音频继续使用 A-roll 主时钟；模板不生成声音。
- `notifTitle`、四条 `messages`、`appName`、`headlineTop`、`headlineAccent`、`footerText` 和内联 `brandLogo` 必须全部显式提供。每个文本变量保持上游默认字符数的 ±20%，不自动缩字、截断或填充无意义文字。
- `NOW` 与 `Show less` 是模板的原生界面 chrome，已在代表样片中人工确认；它们不是本期论断。若当前语言或发布场景不能接受这两个固定词，应排除本模板，而不是结构改造后冒用资格。

## 配置与真实调用

新任务环境确认必须提供：兼容的 `edit/hd` 项目运行时、Python、Node、本地 Chromium、FFprobe，以及固定 HyperFrames checkout 的绝对路径。本机资格版本为仓库提交 `0fd70b1d2165d6ac9f4199bfafa9f22c711bfc8f`、`@hyperframes/cli` 0.8.19；所需入口为 `packages/cli/src/cli.ts` 与 `node_modules/tsx/dist/cli.mjs`。

正式包装器使用已批准 Node 直接启动本地 TSX 与 HyperFrames CLI。资格实验曾复现 Bun 在执行器净化环境中不能正确处理中文路径，因此不能把 Bun 路径写回本合同。渲染固定 `workers=1`、`low-memory-mode`、`strict`、`strict-variables`、关闭浏览器 GPU 与 best-effort。

在已配置项目模块路径的新 Python 进程中加载 `<skill>/scripts/hyperframes_notification_adapter.py`：

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

`load_current_job_brief(job, recipe, component)` 返回当前 Job 内已确认 brief 的原始 UTF-8 JSON 字节。`binding` 使用活动 `references/verified-template-registry.json`；`qualification/source-registry.json` 只允许维护资格实验显式传入，不能在普通生产任务中自我授予验证身份。

执行方式与 DataRollup 相同：把 adapter 放入 `adapters["code_generated"]["hyperframes"]`，再调用 `broll_component_executor.execute_component`。组件 `executor=reference_adapter`、`media_type=animation`、`artifact_contract.alpha=false`，render window 必须正好为 336 帧。计划中的 `invocation_record` 保持 `status=planned / exit_code=null`；真实 PID、退出码、输入、入口、renderer 与输出哈希只读取执行器自然生成的回执。

## brief 结构（仅结构示意）

```json
{
  "schema_version": 1,
  "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 336},
  "template_request": {
    "semantic_family": "progress_sequence",
    "information_units": 4,
    "numeric_values": [],
    "numeric_scale": "not_applicable"
  },
  "props": {
    "data": {
      "notifTitle": "企业智能转型进展",
      "messages": [
        "业务目标完成梳理并确认首批真实落地场景",
        "流程负责人及协作边界均已经确认",
        "试点数据通过复盘并形成完整推广操作手册",
        "规模化发布清单全部完成并进入持续运营阶段"
      ],
      "appName": "企业智能转型项目组",
      "headlineTop": "四步打通落地闭环",
      "headlineAccent": "从试点走向规模化",
      "footerText": "四个关键节点依次完成推动企业方案稳定落地",
      "brandLogo": "data:image/svg+xml;base64,..."
    }
  }
}
```

示例只说明结构，不是生产文案或事实。实际文本需先通过内容提炼人工门；任一字段变化都形成新的 brief 哈希与 revision。

## 网络、缓存与当前 Job 验收

首次真实 CLI 编译会缓存 Inter / EB Garamond，并把精确 GSAP 3.14.2 内联到渲染输入；因此当前证据不能被描述成无条件完全离线。预检需在渲染前确认依赖已经可用，正式执行过程中不允许临时搜索素材或更换 CDN 版本。已有完整缓存可以被后续串行执行复用。

历史资格只证明两组不同输入由同一原生模板正确产出，不批准当前内容。每个新 Job 仍要检查：四条通知的进入顺序、重排稳定态、退出连续性、结论卡完整性、中文字体实际回退、无越界/重叠/截断、头像和字幕安全区、回到 A-roll 的自然过渡。人工确认失败时进入当前 revision；不静默改模板、不伸缩已验证结构，也不直接交付资格样片。
