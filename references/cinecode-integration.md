# CineCode 原生无声 B-roll

使用 `vendor/cinecode/` 内的完整原仓库，固定提交 `c8a3e7552699360a2b0142c9620882af2069eedb`。包内源码归档由现有 `prepare_sources.py` 恢复。每镜的工程和输出保存在当前 Job，读取上游 `SKILL.md`、所选配方及其要求的原生说明。母 Skill 交接已批准的语义、素材、词锚、时窗、画幅和安全区。构图、灯光、运动和原生检查由 CineCode 决定。

`references/cinecode-template-catalog.json` 管理原生配方定位，`references/motion-capability-index.json` 管理语义标签。独立模板是写实工业场景（`cinematic-realistic`，以原生视觉预设为起点的完整场景创作）、抖线手绘（`line-boil`）、液态流动（`liquid-motion`）、连续形变（`shape-morph`）、贴纸科普（`sticker-explainer`）、综艺花字（`variety-captions`）、证据拼贴解说（`vox-explainer`）和图形推导（`visual-proof`）。工业场景的流转分流、抓取交接、机构联动、定位装配、检测判定、加工成形属于语义标签，运镜及换道场景不另计模板。写实工业样片验证的是扫码分流示意。真实检测结果、产品尺寸和资料引用必须依据本项批准的素材。

其余 51 套配方由 CineCode 原生目录收录自 Lemo。CineCode 与 Lemo 的执行、依赖和素材契约分别核对；跨渠道只按同源模板身份计数一次。选型按完整口播语义匹配一次，保留适合的不同画法，再最大化真实渠道与独立模板，最后校时。涉及爆炸拆解、显微证据、真实 UI 等配方时，以该配方实际资料需求判断适配。

通过 `motion_native_skill_adapter.py` 的既有 schema 2 brief、`native_task`、`capture_render` 和 `publish_completed` 执行。原生公开入口 `vendor/cinecode/scripts/capture.mjs --video` 输出 H.264 1080×1920、24fps、精确批准帧数和无音轨。工程浏览器依赖使用当前 Job 内可冻结的本地文件。必要的本地视频源按 brief 授权绑定；综艺花字目前只开放有真实视频底图的整屏 B-roll。母片保持原声、字幕和圆窗布局，CineCode 当前出口为不透明整屏视频。

样片和验证 Job 保存在 Skill 包外。一次原生出片只证明实际制作的配方和当前环境，独立样片也不等同于现有成片的人工终验。
