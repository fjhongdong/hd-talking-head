# Motion Graphics Native:自写纪律动效贴片

当前正式制作只接通 `callout-pin`；`lower-third` 和 `logo-sting` 的设计槽与离线校验仍在，但不能进入正式选择或执行。发现源码或说明不等于已接通能力。

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

正式绑定同样须经过公共 ShotRecipe 校验。`verification_id` 由实际渲染入口摘要与当前 brief 摘要确定，作为本次自写输入的身份标识；它不授予第三方模板或双输入资格。只通过 brief 离线校验、候选检索或原生渲染，不代表绑定字段已符合正式配方合同。

完整离线检查还须从真实 brief 的 `callout_pin` 家族、公开 DATA 槽和透明输出合同识别 `callout-pin`，再与已登记模板和显式选型记录一致。绑定可编译但真实 brief 路由缺失时仍停止；不能以候选表里存在同名项替代这一步。

新增正式路线须用实际适配器绑定走公共 `compile_strategy`，同时核对原生入口、唯一渲染器、模板身份和使用位置。此路线只能是 `custom_fallback / structural` 的 `callout_pin`、`HyperFrames` 渲染器和 A-roll annotation；不得只补入口白名单，也不得用 factory 已登记或单独 ShotRecipe 字段校验替代正式编排检查。

选定计划后的环境检查须匹配实际绑定的 `scripts/render_motion_graphics.cjs` 入口。探针可以由 Python 适配器执行运行时检查，但输出须严格符合公共绑定探针合同，不附加运行时诊断字段；未带选定计划的启动检查不能替代这项验证。

正式包装通过适配器显式接收已验证的 `ffmpeg`、`ffprobe` 绝对路径，并将工具内容计入运行时身份。端到端样段须使用执行器真实的精简环境和受控文件描述符；保留宿主 PATH 的独立渲染不能证明正式环境可用。不得放宽执行器环境来掩盖工具绑定缺失。

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

最终 1080×1920 画面以主文案64px/800、说明48px为起点，按本包实际文字检查复核。文案容器必须有 `max-width`，优先短标签与合理换行，不靠小字、溢出或省略关键意思通过。

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

callout 的目标可以是当前真人画面的真实局部，也可以是本 Job 源码内可定位的静态 SVG 概念物件或简单关系图；ring/tag 必须确实指向它。静态目标只简单出现和停留，不借挂一个圈扩展成装配、变形或通用概念动画；空白区域和单纯放大的字幕不是目标。

确认前检查实际渲染的目标，而不是只审目标描述。暂时遮住标签，主体和关键关系仍应可辨：人与AI须有能区分的人物与机器特征；知识用于作品须同时看到知识、作品及明确的作用方向；做学回路须有作品、问题和学习对象。两个圆头不能冒充人与AI，孤立书本不能冒充知识已用于作品，同一靶心换标签不能冒充不同关系。缺少任一关键对象时退回当前输入，保留已有媒体；不能用非空描述、圈线或语义通过记录替它补足。

正式桥只读取原有 `reference-process-media/v1` 受控媒体 manifest 中的冻结 HTML，不从 brief 所在目录猜 Job 路径。实际 Node 调用锁定的 HyperFrames，检查原生帧钟及透明像素后输出 QTRLE/ARGB。确认前在真实浏览器 seek 已暂停的时间线，读取主标签的实际显现与退出，再核对当前原词锚；源文件包含时间线或文案字样不算通过。渲染后的原尺寸真人合成、字体和遮挡仍按既有 QA 完成。

- 每期现写,单次制作成本高于调现成组件;不替代 Riso/HyperFrames 现成贴片。
- 只接 A-roll 透明贴片;不接 B-roll 整屏、配音、音乐或收费素材。
- 语义选型优先检索整个能力库;本路线三个家族在下横栏/标注/品牌语义上与现有通知/开关/对比/钉板互补,不与之竞争。
