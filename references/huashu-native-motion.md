# Huashu Art Motion 原生调用

固定官方来源 `8a0d7d72ca65fcce6f8ba82c4a6c8dfe35b8422c`，使用完整原版 Skill。父级交接语义、完整原话、真实词钟、已有素材、画布和当前费用授权；原生流程负责设计、场景、材质、主题动作与技术 QA。不修改第三方文件。

当前入口为 `scripts/motion_native_skill_adapter.py`，schema 2 brief、schema 3 result、producer 2.0.0。依赖 ID 为 `huashu-art-motion`，输出按当前 composition 区分不透明视频或真实 alpha。`scripts/huashu_motion_adapter.py` 中的 `native_templates`、`native_workflow_instructions`、`prepare_native_project` 和 `native_render_command` 只做原生调用接缝，不再作为旧固定模板的生产入口。

`references/huashu-art-motion-template-catalog.json` 保留 62 个原生定位。当前竖屏生产模板为 8 个 grammar 和 35 个已成型风格，共 43 个。17 个 research 卡未具备原生质量资格；generic scene 是完整工作流，不增加模板数；37 Rick/Morty 要使用独立 SVG renderer，固定 1920×1080 且没有竖屏参数，本协议不把它伪装为竖屏模板。保留全部原文，不重写 renderer 或通过拉伸改变角色。

主模板、`native_options` 和实际 `native_usage` 的执行声明统一限于这 43 个合格模板；仍可完整阅读研究方法和 generic scene 说明，供原生自由创作。

完整读取原生 SKILL、选中配方、跨场景风格方法及实际引用说明。grammar 输入保留原生 theme、finish、safe zones、data、cues、images、character/frame 等公共字段，不降为固定黑白文字。场景由原生流程在本期工程编写 eras、scenes 和素材；原版 renderer、lib、clips、engine.js 等保持原样。旧 gallery 内容不能替代当前主题创作。

原生 `engine/render.py` 接收当前真实宽高、fps 和时长。grammar 的透明输出必须使用原生 `--alpha` 和 MOV/ProRes 4444，场景输出不透明 MP4。调用 `capture_render` 记录真实命令，执行原生所需 lint/QA，再用 `publish_completed` 记录本次实际使用的卡及工程引用。`load_result` 与正式消费者读取同一实际产物，不把任务描述当成已完成媒体。

运行依赖使用项目隔离目录 `runtime/handdraw-python312`，不改变既有 Pillow 12 环境。使用已安装的 Python 3.12 执行 `run.py prepare --dependency-id huashu-art-motion`：按 `handdraw-python312-requirements.txt` 只补缺失普通包，已有版本不符时停止；复用现有 Playwright 准备入口检查或准备当前选中渠道所需浏览器，不要求先选择 Barty。通过 `PYTHONPATH` 使用该目录，通过 `PLAYWRIGHT_BROWSERS_PATH` 使用该项目浏览器，并设置 `PYTHONDONTWRITEBYTECODE=1`。运行身份直接从本次 Python、FFmpeg、浏览器和包读取，不依赖历史私有 JSON。不安装模型、ASR、TTS或生成素材；Python、Node、npm、FFmpeg 和 ffprobe 仍须预装。调用检查沿现有 `run.py` 与 dependency preflight。

同一 grammar 的贴片与 B-roll 共用模板身份；标签仅帮助语义检索，不替原生 Skill 编舞。历史 3 个窄固定模板已退出现行索引和资格注册，历史源码、样片与交付保留，不重签旧验收。
