# 暖色 3D 黏土贴片

真人透明贴片默认采用暖色 3D 黏土风。用圆润的微缩物件、哑光微颗粒、浅暖柔光和物件投影构成小场景。奶油白负责大面积，陶土橙集中在会动或需要看清的部位。图形的前后变化承担口播意思，确需命名或精确读数时加少量短词。真实截图和证据使用原图与原文字，把质感留给框、承托和随口播移动的指示物件。

先用该句 `overlay_action` 确定可辨的物件、起始姿态、怎么动和可见末态。比如“审批通过才会发出”，用闸门抬起后信封滑入发件槽表现前提。承托、取景、先后关系和场景大小随本句选择。同片保留一致的质感、主色和定格节奏。完整界面操作按原规划使用 B-roll。

`production-defaults.json` 的 `aroll_overlay.style` 是运行时设定，默认选型使用带透明输出的 Barty `motion-broll`。匹配保留完整候选，当前句集中编排这个可执行入口的动作与时长，其他路线保留 `unreviewed`。单渠道理由写在现有 `single_source_review`。用户明确指定本期其他风格或固定模板时，在 `treatment` 填 `overlay_style: "native"`，按相应原生能力制作。

## 首次制作

1. 在本镜 Job 的原生项目中编写 `scene.js`，定义 `designOverlay({THREE, scene, mount, palette, clay, roundedBlock, cues})`。把本句话所需的物件加入 `scene`，返回同步姿态函数 `({frame, motionFrame, progress}) => …`。`progress` 在动作窗内从 0 到 1，每两帧推进一个姿态，在约定帧完整落定并停留。进入前的画面和附加动作可用本镜局部 `frame`。`cues` 是本镜已确认的局部帧。
2. `clay(color)` 提供共享光照下的哑光材质。可用 `cream`、`ivory`、`terracotta`、`deepTerracotta`、`peach`、`ink`。`roundedBlock(width, depth, thickness, color, radius)` 返回以底面为原点的圆角物件，`scene` 中的 Y 轴向上。可用 Three.js 自建形体。必要的 HTML 短词放在 `mount` 内，有卡片时套用现有 `hd-text-card` 和 `hd-text-card-content`，让文字撑开卡片。
3. 沿动作响应里的 `overlay_style.build_argv` 执行，追加本镜源文件、输出片段和 `--center-y`。命令已按 `overlay_local_timing` 带上本镜帧钟。纵向摆位根据真正的演员、手势、字幕和安全区确定。独立贴片采用竖屏横向中心 `540`。确需绑定画面主体时使用 `--center-x` 及既有固定横向锚点。

```bash
<python> <skill>/scripts/warm_clay_overlay.py scene.js clip.html \
  --frames <本镜总帧数> --center-y <摆位像素> \
  --action-start-frame <起势帧> --settled-frame <落定帧> \
  --visible-until-frame <完整展示结束排除帧>
```

4. 用 [Barty 原生透明流程](barty-motion-integration.md#motion-broll-原生调用)编译片段和渲染 24fps 透明 `.mov`，沿当前 `capture_render`、`publish_completed` 和原合成入口交付。共用底座自动设置哑光材质、灯光、柔影和透明画布，动作跟随已确认的时钟。需要读取经批准的本期素材时，在 `designOverlay` 初始化时等其加载完成，再按原生素材合同绑定来源。
