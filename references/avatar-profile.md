# 同一 Job 的头肩头像合同

从 `visual_direction` 开始读取本文件。这里是新配方的可执行参数，不是仅供参考的头像建议。当前 `edit/hd` 合成器使用 1080×1920、24 fps；其他帧率或旋转/像素比例未归一的输入先按已批准剪辑时间轴处理，不能静默沿用裁切坐标。

开发样片也必须先读取原片的采样宽高比（SAR）与显示宽高比（DAR），按显示比例归一为方形像素画面后，才测量、裁切圆窗人物。对非 1:1 SAR 的原片，仅写 `setsar=1` 会把人物拉宽或压窄，不能当作比例归一；预览须检查人物首、中、尾帧，而不只检查输出视频的 1:1 SAR 标记。

## 只校准一次，按需补测

1. 复用本 Job 已批准的 `edited-aroll`、剪辑映射、内容分析和视觉方向，不重新确认封面、文案或关键词。
2. 从当前 A-roll 每个拟用 B-roll 区间取首、中、尾帧；测量头顶、脸框、下巴、颈部及左右肩线。测量可以人工或通过已确认的检测工具完成，必须保留原帧与测量结果，不能用示例数值假装检测。`scripts/calibrate_avatars.py` 的 Haar 人脸框和裁切建议仅写入独立的 `avatar-calibration-candidates.json`，供人工参考；它会以 `manual_required` 非成功退出，绝不生成或覆盖正式 `avatar-calibration.json`。
3. 本 Job 统一头像内径、边框宽度与颜色。新草稿的 bottom-window 头像统一放在右下角：外径为 `diameter + 2 * border_width`，位置为 `x = 1080 - 80 - outer`、`y = 1700 - outer`；按人物真实构图选择裁切方框。旧已批准计划仍按其冻结坐标读取，不由新策略回写。
4. 位置变化使用裁切关键帧，同一镜头裁切尺寸固定，避免忽大忽小。人物转头、走动或遮挡时加密采样；线性插值只是执行测量轨迹，不是自动跟踪或所有中间帧合格的证明。
5. 将参数同时冻结在该段 `visual_strategy.composition.avatar` 和 `shot_recipe.composition.avatar`，随本期视觉方向确认。`plan_avatar_policy` 只对新草稿归一化位置；`validate_avatar_plan_policy` 拒绝非右下角的新草稿。

## 字段与单位

`avatar` 使用 `profile`、`position`、`crop`，按需增加 `entrance`、`exit`、`continuation` 字段；下列名称是 JSON 字段，不是可见文案。

| 对象 | 字段 | 约束 |
| --- | --- | --- |
| `profile` | `schema_version`, `framing` | `1`、默认 `head-shoulders`；用户明确允许时可用 `head-neck` |
| `profile` | `source_sha256` | 当前归一 A-roll 的真实 SHA-256，不能填头像图片或旧成片的哈希 |
| `profile` | `diameter`, `border_width`, `border_color` | 内径 128–384 px，边框 0–24 px，RGB 十六进制颜色；同一计划全部 B-roll 完全一致 |
| `position` | `x`, `y` | 圆形外框左上角整数坐标；外径 = 内径 + 2 × 边框；不能超出宽 1080 和 soft-safe 底边 1700 |
| `crop` | `size` | 在 1080×1920 原画面中的方形边长，32–1080 px；不是输出头像内径 |
| `crop` | `anchors` | 3–128 个按帧号严格递增的测量点，必须含 `0`、`frames // 2`、`frames - 1` |
| 每个 anchor | `frame`, `x`, `y` | 当前 B-roll 的局部帧号及裁切框左上角，不是全片帧号；框必须留在原画面内 |
| `landmarks` | `head_top`, `chin`, `neck` | 原画面像素坐标 `[x, y]` |
| `landmarks` | `face_box` | `[x, y, width, height]`，原画面坐标 |
| `landmarks` | `shoulders` | `head-shoulders` 必填：`[左肩点, 右肩点]`；允许肩线倾斜，不可只测颈部冒充肩线。`head-neck` 不要求此字段 |

所有测量数值必须有限且不能是布尔值。内径范围是输入校验边界，不是鼓励同一视频随意改变头像尺寸；实际值以本 Job 批准结果为准。当前共享合成器不加阴影，各镜头不得自行叠加不一致阴影。

比例均以裁切方框为基准：`head-shoulders` 脸宽 0.38–0.52、肩宽至少 0.68；`head-neck` 建议脸宽 0.38–0.60；两者头顶留白均为 0.06–0.11。头、脸框四角、下巴、颈部必须落在最终圆形遮罩内；`head-shoulders` 另须包含两个肩点，不能仅靠方框包含判定通过。用户明确允许后才可使用 `head-neck`，允许肩部自然截取；默认仍为 `head-shoulders`。若原片无法自然容纳，不为过门改头形，也不自动选择另一种头像类型。

## 先连组，再安排进出

先合并相邻 `full_frame` 镜头，按完整真人段落判断间隔，不能把贴片前2帧或5帧的纯真人切片单独当空档。已有贴片和确认内容必须保留。两个小窗段之间不足24帧（1秒）、且整段没有组件的纯真人空档，应延续前一段B-roll的末态覆盖，圆窗真人继续按原声时钟播放；不能放大后马上缩小，也不能冻结整张合成画面。

夹有短贴片的真人段先按[视觉校时](visual-quality-contract.md)判断是否需要全屏。连到 B-roll 组时，先安排好贴片的语义和画面，再按同组规则衔接头像。

保留原生动作触发时刻，只用已有公开时长/末态保持参数增加背景停留；更新本段source end、brief身份和实际头像首中尾测量，后段起点、原声与总时长不动。只吸收无独立内容的空档，不覆盖已确认贴片。保留视觉行ID与编号，不因删除空cut重新排号。

连续小窗组的每个组内前段须声明 `"continuation": true`。下一段必须紧邻并使用同源、同profile、同位置、同裁切尺寸的小窗，且不得再次 `entrance`；当前段不得同时 `exit`。该字段强制关闭原末12帧渐隐，保持头像大小和不透明度；它不冻结人物视频。完整字段进入原单段recipe和复用身份，不能只依赖整表hash。

一组只在首段进入、末段退出。正式 validator 自动拒绝短空档往返缩放、组内漏填 `continuation`、位置或裁切尺寸跳变及重复入场。背景末态延续至下一段接入。

正式阶段入口在依赖准备前调用 `plan_avatar_policy`，返回不修改原稿的规范副本：缺省首入12帧、末出8帧，组内前段标记continuation，并清掉位置矛盾的旧进出字段；合法自定义帧数保留。没有相邻全屏真人的片首/片尾不增加相应动作。空间不足按现有占用规则报具体错误，不能压缩时长凑通过。

短空档返回 `prepare_visual_inputs`，包含左段旧时窗、包含空档后的完整目标时窗、被吸收的空段ID和不动的右段起点。宿主内部按已选原生公开时长/末态参数准备输入，更新完整口播引用、阅读窗、绑定及真实首中尾采样，再重入原入口。此时 `prepared=false`；没有新proposal、没有推进状态，也不要求用户再次选择。不能安全延续时先调整草稿，不自动更换已批准引擎或伪造新测量。

确认准备处另调用 `validate_avatar_plan_policy`，无论动效字段是否存在都检查短空档及各组完整性。确认后的编译仅校验冻结方案，不补动作或改时窗。原 `validate_plan_avatars` 继续服务已批准计划的执行合同，不追溯重做旧Job。

## A-roll 收缩为头像

从全屏人物进入 B-roll 时，可在该段的 `avatar` 中冻结 `"entrance": {"kind": "aroll_to_avatar", "frames": 12}`。只允许前一段为连续的 `full_frame` 人物画面；B-roll 之间不重复入场。帧数为 8–18，须与末尾原有 12 帧淡出或本段显式 `exit` 分开。

同一条 A-roll 按原局部时钟继续播放：画面先收圆，再缩到已校准的小窗位置。首帧保持原全屏，最后一帧直接接入原头像裁切链；不复制人像、不插帧延时、不改原声和字幕时钟。仅重做受影响段，保留原头像尺寸、裁切及退出行为。

按入场完成后的稳定区间规划关键文字的阅读时间。定位切入异常时，检查受影响边界的人物连续性、重复叠画、黑边与落位。


## 头像放大返回 A-roll

返回全屏人物时，在结束的 B-roll 段冻结 `"exit": {"kind": "avatar_to_aroll", "frames": 8}`。仅允许下一段为连续的 `full_frame` 人物画面；连续 B-roll 不退出。帧数允许 6–18，常用 8 帧（约三分之一秒），返回节奏略快于进入；不插入额外时间。

配置 `exit` 时，取消本段原有头像淡出。先保留原静态圆窗的首个退出帧，再将同一条、同一时钟的人物放大展开；最后一帧必须完整覆盖画布，接下一帧全屏 A-roll。入场和退出可同段配置，两个时窗不能交叠。没有入场、只有退出的段也输出透明全画布并在原点叠加，不能再次按小窗坐标偏移。

把完整稳定的阅读窗排在头像放大可能覆盖关键字的时段之前。定位返回异常时，结合段末、展开与全屏接点核对人物连续性和时钟。

## 可执行入口与正式绑定

主包 `scripts/avatar_profile.py` 提供：

- `validate_avatar(avatar, frames=...)`：校验单镜头并返回独立副本；不做检测或修改原输入。
- `validate_plan_avatars(segments, source_sha256=...)`：检查每段时长、统一 profile、当前 A-roll 身份；`hidden` / `full_frame` 不得携带无效头像参数；入场核对前段，退出核对后段。
- `crop_at(avatar, frame)`：供 QA 获取指定局部帧的线性插值裁切框。
- `filter_chain(avatar, frames=...)`：从同一局部时钟 `[0:v]` 生成 `[presenter]`；静态头像输出小窗，入场动效输出透明全画布，由合成器在原点叠加。组内 `continuation` 关闭末尾淡出；其他未配置退出的段保留原淡出行为；配置退出时由同源人物展开替代淡出，不新增音轨。

兼容项目由 `edit/hd/tools/avatar_profile.py` 薄入口调用主包。`visual_plan` 在编译草案及检查正式计划时拒绝未校准的 `bottom_window`，正式 `segment_render.generation_identity` 再核对实际输入 SHA，构建图时检查真实视频尺寸。profile、位置、裁切轨迹进入已有配方/计划/输出 identity；不要另外手写成功记录。独立调用纯辅助函数不等于已通过完整生产门。

低层 strategy/recipe reader 仍可读不含 avatar 的历史结构，但新计划及正式渲染不能继续使用它。旧批准 Job 缺参数或运行时身份变化时明确报告差异，由用户选择受控修订；不得为“兼容”自动补旧坐标或重做 v11 等已批准成片。

## 验收与边界

规划时按真实取景测量头肩、轨迹和稳定阅读区，机器检查验证输入与当前画面规格和时钟的关系。音画误差仍按合同控制在 2 帧内。入库样片和局部排错可对照实际圆形输出的稳定段及受影响边界。常规成片验收按[阶段合同](stage-contracts.md#制作交付与状态)。

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
