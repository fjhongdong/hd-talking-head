# CineCode 原生无声 B-roll

使用 `vendor/cinecode/` 内的完整原仓库，固定提交 `c8a3e7552699360a2b0142c9620882af2069eedb`。包内源码归档由现有 `prepare_sources.py` 恢复。每镜的工程和输出保存在当前 Job，读取上游 `SKILL.md`、所选配方及其要求的原生说明。母 Skill 交接已批准的语义、素材、词锚、时窗、画幅和安全区。构图、灯光、运动和原生检查由 CineCode 决定。

`references/cinecode-template-catalog.json` 管理原生配方定位，`references/motion-capability-index.json` 管理语义标签。独立模板是写实工业场景（`cinematic-realistic`，以原生视觉预设为起点的完整场景创作）、抖线手绘（`line-boil`）、液态流动（`liquid-motion`）、连续形变（`shape-morph`）、贴纸科普（`sticker-explainer`）、综艺花字（`variety-captions`）、证据拼贴解说（`vox-explainer`）和图形推导（`visual-proof`）。工业场景的流转分流、抓取交接、机构联动、定位装配、检测判定、加工成形属于语义标签，运镜及换道场景不另计模板。写实工业样片验证的是扫码分流示意。真实检测结果、产品尺寸和资料引用必须依据本项批准的素材。

其余 51 套配方由 CineCode 原生目录收录自 Lemo。CineCode 与 Lemo 的执行、依赖和素材契约分别核对；跨渠道只按同源模板身份计数一次。完整口播语义只匹配一次。同义标签、相同配方来源和先前使用次数均不作为排除理由。排除时，在 `constraint_refs` 引用当前原话、语义或 `required_content/<id>`，摘录该路线 `limitations/<i>` 的原文（`limitation_quote`），点明无法呈现的原要求（`unmet`）及原因。不确定就留为待评审。合格候选联合最大化渠道，再最大化去重模板，最后核对 24fps 起止帧与原生动作是否能完整落位。确认表分别呈现真实渠道、去重模板和每镜调用路线。

对有素材要求的候选，先从目录返回的 `cinecode_branches` 中选分支。在候选评审的 `cinecode_input` 写入 `branch` 和该镜素材的 `{job_path, sha256, byte_count}` 描述符 `material`，以及人能核对的 `source`（例如馆藏页面）。综艺花字可选 `video`、`photo` 或 `drawn`；原生绘制只填写 `branch`，视频／照片也可用本镜清单内同类型生成 `step_id`。显微图、档案、卫星图、实测点云、真实产品和尺寸等必须依据对应的真实来源，不能用生成素材冒充。素材准备阶段读取该配方要求，已有合格的导出素材直接用；原生步骤需解析原始素材时，先核对当前 Job 的必要工具和数据再执行，原生 Skill 决定如何取景、重绘和预处理。准备完的 brief 写入同一 `cinecode_material_branch`，并在 `materials` 绑定对应素材。

通过 `motion_native_skill_adapter.py` 的 schema 2 brief、`native_task`、`capture_render` 和 `publish_completed` 执行。原生 `vendor/cinecode/scripts/capture.mjs --video` 输出 H.264 1080×1920、24fps、精确批准帧数和无音轨。已固定版本的 MathJax、Three.js 与 postprocessing 从主 Skill 资源复制到当前 Job；只本地化 Job 页面引用，不修改第三方模板、不开放浏览器外网。其他字体、模型、纹理或数据按所选原生配方放到 Job，使用本地路径并保留来源。完成记录绑定实际加载的入口、引用和输出关键帧；素材分支核对本项获准的文件或原生衍生记录，不能拿未加载的文件或空白片充作配方结果。关键帧供核对动作与内容，不是自动美观评分，也不新增用户确认。CineCode 当前输出是不透明整屏 B-roll，母片仍统一处理口播、字幕和圆窗。

样片和验证 Job 保存在 Skill 包外。一次原生出片只证明实际制作的配方和当前环境，独立样片也不等同于现有成片的人工终验。
