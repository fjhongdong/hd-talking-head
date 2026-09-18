# 同一 Job 的头肩头像合同

从 `visual_direction` 开始读取本文件。这里是新配方的可执行参数，不是仅供参考的头像建议。当前 `edit/hd` 合成器使用 1080×1920、24 fps；其他帧率或旋转/像素比例未归一的输入先按已批准剪辑时间轴处理，不能静默沿用裁切坐标。

## 只校准一次，按需补测

1. 复用本 Job 已批准的 `edited-aroll`、剪辑映射、内容分析和视觉方向，不重新确认封面、文案或关键词。
2. 从当前 A-roll 每个拟用 B-roll 区间取首、中、尾帧；测量头顶、脸框、下巴、颈部及左右肩线。测量可以人工或通过已确认的检测工具完成，必须保留原帧与测量结果，不能用示例数值假装检测。
3. 本 Job 统一头像内径、边框宽度与颜色。每段按主视觉避让选择位置，按人物真实构图选择裁切方框；居中、偏侧和移动不能共用旧视频的固定坐标。
4. 位置变化使用裁切关键帧，同一镜头裁切尺寸固定，避免忽大忽小。人物转头、走动或遮挡时加密采样；线性插值只是执行测量轨迹，不是自动跟踪或所有中间帧合格的证明。
5. 将参数同时冻结在该段 `visual_strategy.composition.avatar` 和 `shot_recipe.composition.avatar`，随现有视觉方向/真实 canary 一起审核，不增加第二套头像批准状态。

## 字段与单位

`avatar` 只允许 `profile`、`position`、`crop` 三个字段；下列名称是 JSON 字段，不是可见文案。

| 对象 | 字段 | 约束 |
| --- | --- | --- |
| `profile` | `schema_version`, `framing` | `1`、`head-shoulders` |
| `profile` | `source_sha256` | 当前归一 A-roll 的真实 SHA-256，不能填头像图片或旧成片的哈希 |
| `profile` | `diameter`, `border_width`, `border_color` | 内径 128–384 px，边框 0–24 px，RGB 十六进制颜色；同一计划全部 B-roll 完全一致 |
| `position` | `x`, `y` | 圆形外框左上角整数坐标；外径 = 内径 + 2 × 边框；不能超出宽 1080 和 soft-safe 底边 1700 |
| `crop` | `size` | 在 1080×1920 原画面中的方形边长，32–1080 px；不是输出头像内径 |
| `crop` | `anchors` | 3–128 个按帧号严格递增的测量点，必须含 `0`、`frames // 2`、`frames - 1` |
| 每个 anchor | `frame`, `x`, `y` | 当前 B-roll 的局部帧号及裁切框左上角，不是全片帧号；框必须留在原画面内 |
| `landmarks` | `head_top`, `chin`, `neck` | 原画面像素坐标 `[x, y]` |
| `landmarks` | `face_box` | `[x, y, width, height]`，原画面坐标 |
| `landmarks` | `shoulders` | `[左肩点, 右肩点]`；允许肩线倾斜，不可只测颈部冒充肩线 |

所有测量数值必须有限且不能是布尔值。内径范围是输入校验边界，不是鼓励同一视频随意改变头像尺寸；实际值以本 Job 批准结果为准。当前共享合成器不加阴影，各镜头不得自行叠加不一致阴影。

比例均以裁切方框为基准：脸宽 0.38–0.52、肩宽至少 0.68、头顶留白 0.06–0.11。头、脸框四角、下巴、颈部和两个肩点还必须落在最终圆形遮罩内，不能仅靠方框包含判定通过。取不到完整头肩时停止并报告具体区间，不自动生成头部特写，也不擅自改成隐藏头像。

## 可执行入口与正式绑定

主包 `scripts/avatar_profile.py` 提供：

- `validate_avatar(avatar, frames=...)`：校验单镜头并返回独立副本；不做检测或修改原输入。
- `validate_plan_avatars(segments, source_sha256=...)`：检查每段时长、统一 profile、当前 A-roll 身份；`hidden` / `full_frame` 不得携带无效头像参数。
- `crop_at(avatar, frame)`：供 QA 获取指定局部帧的线性插值裁切框。
- `filter_chain(avatar, frames=...)`：从同一局部时钟 `[0:v]` 裁切、缩放并生成圆形 `[presenter]`；主画面不被缩放或复制替换。末尾 12 帧保留现有淡出行为，不新增音轨。

兼容项目由 `edit/hd/tools/avatar_profile.py` 薄入口调用主包。`visual_plan` 在编译草案及检查正式计划时拒绝未校准的 `bottom_window`，正式 `segment_render.generation_identity` 再核对实际输入 SHA，构建图时检查真实视频尺寸。profile、位置、裁切轨迹进入已有配方/计划/输出 identity；不要另外手写成功记录。独立调用纯辅助函数不等于已通过完整生产门。

低层 strategy/recipe reader 仍可读不含 avatar 的历史结构，但新计划及正式渲染不能继续使用它。旧批准 Job 缺参数或运行时身份变化时明确报告差异，由用户选择受控修订；不得为“兼容”自动补旧坐标或重做 v11 等已批准成片。

## 验收与边界

机器校验只证明**输入的测量值**符合阈值，不证明测量值是真的。必须查看实际圆形输出的进入后、稳定段、退出前代表帧，另核对轨迹首/中/尾及转身等风险点；淡出末帧不能替代完整可见肩线的稳定帧。核对边框、外径、位置、头肩、主信息避让，并按既有合同检查音画误差不超过 2 帧。

可选低内存集成测试：

```bash
<python> <skill>/tests/render_avatar_integration.py \
  --project-root <project> \
  --portrait-frame <absolute-measured-frame.png> \
  --calibration-json <absolute-frame-calibration.json> \
  --output <absolute-new-evidence-directory> \
  --ffmpeg <ffmpeg> --ffprobe <ffprobe>
```

此测试的 calibration 使用同一结构，但 `source_sha256` 专门绑定**输入静态帧**，包含 48 帧的首中尾测量点。测试把这张真实人物静态帧置于居中、偏左、偏右和受控横移构图，生成新的测试视频哈希后再绑定测试 avatar。它串行调用实际合成器、检查画幅/帧数和头像稳定误差；输出进程记录与抽帧。它不是生产 Job 的校准文件，不可直接用于生产，也不验证自然运动、嘴型同步或完整视频已获批准。
