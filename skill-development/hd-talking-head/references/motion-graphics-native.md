# Motion Graphics Native:自写纪律动效贴片

这是 `motion-graphics-native` 的条件接入说明。它支持三类 A-roll 透明贴片,每期按本合同现写,不选模板:

- `lower-third` 下横栏:命名人物/来源出处/地点标注,说话人开口后落板。
- `callout-pin` 标注引导:指认画面局部,拉线/画圈/描边,随词锚进退。
- `logo-sting` 品牌贴片:片头标识汇聚或片尾收束卡,标志最后锁定。

方法论参考项目内 `参考项目/B-roll开源方案/baocut`(钉定提交 `754737d2ed768bddcb33519f4763f75e7b447f9f`)的 motion-graphics 手艺;本合同用本项目自己的语言编写,不复制其文本或代码。该仓库不进入本包、不参与运行;它不是依赖,更换或删除它不影响本路线执行。

## 接入身份

- 依赖身份:`motion-graphics-native`
- 渲染器:项目内 hyperframes CLI(vendor 固定版),透明输出 QTRLE/ARGB MOV
- 我方入口:`scripts/motion_graphics_adapter.py`
- 我方渲染包装:`scripts/render_motion_graphics.cjs`
- adapter 类型:`ReferenceProcessAdapter`;正式执行器:`reference_adapter`
- 身份记 `custom_fallback + structural`:每期图形为本 Job 手写的结构改编,不冒充第三方模板,不继承任何上游验证身份

## 作者合同(hyperframes/1 同构)

每枚图形是一个自包含单文件 HTML,画面是时间的纯函数:

- 根元素带 `data-composition-id`、`data-width="1080"`、`data-height="1920"`、`data-fps="24"`、`data-duration`(秒)。
- 页面背景透明(贴片合同);根元素不透明底色仅用于全画幅品牌贴片的片头帧。
- 脚本在 `window.__timelines[<compositionId>]` 上注册一条**暂停的** gsap 时间线(需 seek/time/duration);画面只由 seek 到的时间决定。
- 禁止 `Date.now()`、`Math.random()`、自走动画、网络请求、外部字体;确定性失败即停止,不放宽。

## 三槽纪律

每枚图形按三个槽写,槽序固定:结构 → 布局 → 动效。

### 结构槽(scene)

元素清单 2–6 个可动元素,每个有角色和 `id`:

| 家族 | 角色组合 |
| --- | --- |
| `lower-third` | `name + role + org`(人物)或 `source + detail`(出处) |
| `callout-pin` | `anchor + line + label`(指认)或 `ring + tag`(圈注) |
| `logo-sting` | `mark + headline + tagline`(片头)或 `mark + cta-line`(片尾) |

主文案标 `data-copy-primary`,次文案标 `data-copy-secondary`,文字容器 `class="copy"`。

### 布局槽(layout)

9:16 位置族与像素(与父级安全区合同一致,避开字幕 bottom=350 与圆窗):

| 位置族 | 适用 | 关键约束 |
| --- | --- | --- |
| `lower-safe` | 下横栏 | 底边 ≥ y=1450;左右 ≥ 60px;不与字幕重叠 |
| `side-rail` | 标注引导 | 标注目标侧;引导线不横穿字幕带 |
| `centered` | 品牌贴片 | 全画幅;主标居中 y=700–1100 |

字号:说明 15–18px、次级 20–24px、主标 42px、大字 68–80px。文案容器必有 `max-width`,长文案靠省略号不靠溢出。

### 动效槽(motion)

每个元素一个时间窗 `range(t, start, end)` 配一个缓动与 1–2 个属性:

- 位移配 `easeOut`,弹出配 `backOut`,描线与出场配 `easeInOut`。
- 写法固定:`prop: (1-p) * 幅度`;`scale: 起点 + (1-起点)*p`;`opacity: p`。
- 幅度:元素位移 30–120px,面板进出 340–560px,rotate ≤ 25°,弹出 scale 起点 0.2–0.45,容器 settle 起点 0.75–0.95。
- 同一元素不同时 slide 又 pop。

## 时间包络(24fps)

| 项 | 规则 |
| --- | --- |
| 第一元素 | 词锚后 0.02–0.05s 起步;片头帧例外(标题 0 秒在位) |
| 单元素窗口 | 入场 0.5–0.8s;描线 0.6–1.0s |
| 错峰 | 相邻元素起点差 0.1–0.4s;同类 stagger 0.1–0.3s |
| 入场结束 | 最后一个入场在总时长一半之前结束 |
| 可读停留 | 入场结束到出场开始 ≥ 1.2s;整句文案 ≥ 2s |
| 统一出场 | 结束前 0.62s 到 0.05s,整个 scene 用 easeInOut 淡出 |
| 词锚绑定 | 入场对齐 `overlay_alignment.events` 的 `current_clause` 锚;进退由父级时钟驱动 |

## 颜色 token

只用三 token:`--ink`(深色文字)、`--panel`(浅底)、`--accent`(强调)。半透明用 `color-mix(in srgb, var(--ink) N%, transparent)`。从本 Job 的默认制作配置(`production-defaults.json` 的 `aroll_overlay`)取值,不引外部字体。

## Brief 合同

```text
schema_version=1
source_binding = {aroll_sha256, segment_id, start, end}
composition = {id, width:1080, height:1920, fps:24, frames, alpha:true}
template_request = {semantic_family: lower_third|callout_pin|logo_sting,
                    information_units: N, numeric_values:[], numeric_scale:"not_applicable"}
entry = {job_path: "<Job 内相对路径>.html", sha256}
assets = []
data = {… 家族公开 DATA 内容槽,见下}
```

`data` 公开槽(全部来自已批准内容地图,不编事实):

| 家族 | 槽 |
| --- | --- |
| `lower-third` | `name`(≤8字)、`role`(≤12字)、`org`(≤12字,可空) |
| `callout-pin` | `target_desc`(指认描述)、`label`(≤10字)、`direction`(up/down/left/right) |
| `logo-sting` | `mark_text`(≤6字)、`headline`(≤14字,可空)、`cta`(≤10字,可空) |

## 渲染与验收

- `render_motion_graphics.cjs` 调项目 hyperframes CLI 渲染透明 QTRLE MOV;父级按现有 A-roll 合成链叠加原声与唯一字幕。
- 透明 alpha 须实际解码检查,不接受容器声明。
- 每枚图形在原尺寸真人画面上检查稳定帧:文字可读、不遮人物、不与字幕重叠、进退画面与词锚一致。
- 本路线只消费本合同;不改第三方、不冒充上游身份、不扩展为全画幅 B-roll。

## 能力边界

- 每期现写,单次制作成本高于调现成组件;不替代 Riso/HyperFrames 现成贴片。
- 只接 A-roll 透明贴片;不接 B-roll 整屏、配音、音乐或收费素材。
- 语义选型优先检索整个能力库;本路线三个家族在下横栏/标注/品牌语义上与现有通知/开关/对比/钉板互补,不与之竞争。
