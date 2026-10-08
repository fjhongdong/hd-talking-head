# Huashu 原生动效接入

本页只描述本项目对 Huashu 的薄接入，不把 Huashu 的场景目录或 35 个场景当作模板资格。固定 vendor 提交为 `26dba25b2b495c2138848c29a2c90df356a20325`；本轮只允许三条能力路线：`y2_vox`（证据拼贴）、`y1_kurzgesagt`（机制关系）、`t2_keynote_ui`（三张功能卡）。`t3`/`t1` 按需后接；`y3`（仅马克笔、无握笔手）、`y4`（作者固定角色）、`y5`（第二字幕/非独立语义）不启用。

## 调用边界

入口为 `scripts/huashu_motion_adapter.py`。它接收 brief，实际调用固定 vendor 的 `render.py --spec`；父级继续统一圆形人物小窗、A-roll 原声和唯一字幕轨。Huashu 不负责替代父级时钟、字幕或真人合成。`alpha` 本轮固定为 `false`，目标画布为 `1080×1920@24fps`；`left/right safe` 不参与布局，上下安全避让以实际父级合成结果为准。

启动时可用 `ensure --skill huashu-art-motion` 检查项目内依赖；缺失时只准备项目 vendor，不做云端生成。现有 verifier 以 `require_execution=False` 核对 candidate snapshot 时，只维护 bootstrap，不能授予 production 资格。真实资格仍需 registry 中有两输入短片证据并完成实际绑定与媒体验收；未通过这些检查，不宣称入口已接通。

当前接入层为 `1.1.0`。经用户允许，三条路线统一使用进程内原生启动器：仅在独立 Python 子进程设置 `socketserver.TCPServer.request_queue_size=64`，保留原生 argv、导入路径及非零退出传播，再执行固定 vendor 的 `render.py`。这不是并发渲染器，不修改上游服务、JS、模板、字体、动效或宿主进程设置；本地重型渲染仍串行。

三条路线各以两份不同口播内容完成新的真实 `ReferenceProcessAdapter` 执行（172 / 180 帧），六例均自然退出 0，并以新快照、配方、回执、MP4 和三态帧登记，未改旧回执。`y1_kurzgesagt` / `y2_vox` 的新 MP4 与先前验收输出字节完全一致，来源窗口、人物配置及字幕轨不变，沿用已有父级视觉检查；其中 y1 首份内容已有共享合成及 0 帧音频偏移检查，y2 两段已有完整高亮过程的正文、来源与避让检查。`t2_keynote_ui` 两份新输出另通过真实父级合成和独立目视，三卡中文、圆形头肩小窗、原声及唯一关键词字幕没有遮挡或裁切。资格只覆盖下述精确输入范围，不扩大为所有 Huashu 场景。

此前原版默认连接容量下，t2 字体 cmap 请求及 y1 资源加载曾出现 `ERR_CONNECTION_RESET` / `ERR_SOCKET_NOT_CONNECTED`；已按当时约定停止并保留失败记录。统一启动器的六例通过证明当前调用方案可用，不证明间歇故障永久消失，也不将连接容量推断写成已证实的唯一根因。遇到新的失败仍停止对应路线，不自动重试、扩大容量、切换 renderer、删字体、忽略页面错误或修改第三方源码。

最新实施状态：接入层在校验固定运行时后，为独立 wrapper 子进程统一设置冻结 FFmpeg/FFprobe 目录与系统工具目录，并核对命令解析精确命中固定工具；不改变宿主、系统、共享执行器或第三方 Skill。调用前使用项目已准备的 Python 3.12 环境，不混用系统 Python；厂商 Python 路径继续固定在 vendor venv。早期校验、上游调用和输出处理失败均由现有受控出口返回准确阶段与非零退出，既有执行器能接收该摘要，不打印原始文案、运行时参数、密钥或完整命令。旧失败维护记录保留，新入口使用独立维护执行上下文，不迁移、补签或删除旧记录。统一 `normalize_native_output` 仍只通过 H.264 metadata / stream copy 补 SAR=1:1、DAR=9:16，设计样片与正式调用共用；不重新编码、缩放、裁切或放宽原有严格检查。旧 Job 与已确认成片未改。

候选资格仅沿现有完整 VisualPlan 校验传递：`qualification_context` 绑定镜头、组件、依赖、模板、完整 recipe 摘要和 candidate registry 路径/摘要；只作用于精确目标，其余组件仍按正式 registry 验证。此上下文不能批准用户方案、替代 A-roll/已批准文件校验或赋予正式模板资格。

## Brief schema

```json
{
  "schema_version": 1,
  "dependency_id": "huashu-art-motion",
  "source_binding": {
    "aroll_sha256": "<A-roll sha256>",
    "segment_id": "<segment>",
    "start": 0,
    "end": 6
  },
  "canvas": {
    "width": 1080,
    "height": 1920,
    "fps": 24,
    "duration_in_frames": 144
  },
  "template_request": {
    "semantic_family": "evidence_source",
    "information_units": 1,
    "numeric_values": [],
    "numeric_scale": "not_applicable"
  },
  "props": {
    "data": {
      "grammar": "y2_vox",
      "data": {},
      "cues": [
        {"at": 0, "kind": "image", "image": "source-doc", "text": "原文"},
        {"at": 1, "kind": "highlight", "data": {"rect": [0.08, 0.24, 0.76, 0.12]}}
      ],
      "safe": {"top": 120, "bottom": 640}
    }
  },
  "assets": [
    {"media_ref": "source-doc", "job_path": "assets/source-doc.png", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
  ]
}
```

上例只是合法结构样例，不是执行素材；实际调用必须替换为真实 A-roll 摘要、Job 相对媒体路径和文件 SHA-256。没有图片 cue 时不添加 `assets` 条目。

`source_binding` 只绑定来源和原声主时钟，不增加 `status` 自证字段。`canvas.duration_in_frames` 是唯一时钟；native dimensions 与 duration 均由 canvas 派生，不在其他字段重复声明。真实 A-roll 词帧先在主时钟确定，再转换为当前镜头的 local cue；`number at` 只在词帧落定后写入 brief。`assets` 只登记实际媒体引用、Job 路径和 SHA-256，不放占位媒体。

路线语义约束：`y1_kurzgesagt` 只支持恰好三节点机制流程，语义为 `process_flow` / `mechanism_system`，不做 hierarchy；完整配置必须不使用 `highlight` / `enter`，保留原始 `title`、`point`、`flow=true` 及原生信号（如 entrance、pulses、stars），不能用自写 JS 重做。`y2_vox` 只使用单张真实来源图与对应 `rect` 高亮，语义为 `evidence_source`，不能扩写成证据对比或多图比较；完整概览配置中的全部语义标签必须可读，并在实际播放中完成语义 QA，不能以“焦点外节点弱化”放宽可读性或裁切要求。`t2_keynote_ui` 只支持 `product_features` 的恰好三张原生功能卡、标题、eyebrow、subtitle 与 accent；不承诺未测的截图、数字、教学步骤或其他变体。

### Vox 输入版式与避让

本次验证的是 `1000×620` 横向原文摘录、三至四行正文、完整来源脚注及原生黑底来源标签，`safe.top=120 / bottom=640`。两次高亮由实际文字边界测量产生，宽度均不少于图片的 0.5；荧光笔与红圈保持上游原生动作。正文来自用户提供的文稿，须注明“口播原文摘录”，不伪装为独立核实的外部证据。外部截图保留原始内容，不能为了凑版式重排或删掉事实、出处。

调用时先按语义挑选能容纳完整正文及来源的横向材料；文稿摘录可以保持原义重新分行。逐个测量真实整行的矩形，不用空白撑大框，不缩小字体迁就容量。每个高亮都采用整行范围，不能先用窄框放大后再依赖后面的宽框缩回。原生宽框只限制推进倍数，不保证整个素材一直处于父级安全区；比例、矩形宽度和 `safe` 都只是输入筛选，不是自动验收结论。

当前 canary 还必须检查初始全貌、每次高亮的推进与停留、两次高亮之间的移动和退出，确保有意义的正文、脚注、标签及笔迹始终可读，不与人物或普通字幕重叠。纸张无信息的边缘可随原生镜头推近出画；重要内容不得裁切。只查入场与末帧会漏掉中途的放大遮挡；不另造相机、遮罩或父级二次推拉来补救。

## CLI 形状

依赖检查支持 `--skill huashu-art-motion`。adapter 的实际 factory 为 `create_adapter(project_root, python_executable, brief_loader, registry_path=...)`、`create_binding(adapter, brief_bytes, registry_path=...)` 和 `create_artifact_probe(ffprobe)`。其 argv 由 factory 填入 `--skill-root`、`--project-root`、`--registry-path`、registry SHA-256、`--runtime` 等参数；调用方不手填“成功”参数。外层探针/调用仍可使用 `--probe --project-root <project> --dependency-id <id>`，正式渲染使用 `--brief <brief.json> --media-manifest <FD> --output <path>`。

## 状态边界

只读源码、启动准备、candidate snapshot、brief 结构通过，都不是真实执行。只有固定 vendor、两输入证据、registry 记录、实际 `render.py --spec` 回执、媒体探针和当前语义/美观验收齐全，才能形成 production binding；在此之前保持待验证，不改上游 JS/美术，不改旧 Job 或已确认媒体。
