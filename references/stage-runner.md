# 阶段执行与续做

按 [SKILL.md](../SKILL.md) 的唯一流程和[阶段合同](stage-contracts.md)执行。使用包内 `run.py` 与已有实际入口，传入本 Job 真实素材、词时钟、所选渠道及经用户确认的完整清单和费用。原生工作流独立镜头可并行；制作完成后一次完整合成并交片。

保持真实状态：生产完成是 `completed`，用户人工终验接受才是 `accepted`。不得自动写 `approved` 或补造人工确认。封面实图、试听、样片、canary、逐镜 OCR／量框、额外抽帧或逐阶段质量审批均不是默认继续条件；原生 Skill 自身流程和技术 QA 不变。用户明确要求封面单独确认时，按[封面合同](cover-contract.md)执行独立展示和等待，不因文件已生成或正文已确认而跳过本期封面确认。

只检查文件可用、必要尺寸帧数时长与导出成功；保护原始素材。收费请求须处于已确认授权内，避免重复提交，结果未知时先核实。执行失败先定位并最小修本 Skill，再恢复受影响分支；无关素材不等待。审美、直观和听感问题在成片后接收用户反馈并按原编号局部返修，不重做无关镜头。历史 Job、成片与记录不迁移、不重签。

## 查询、返修与终验

以下命令均通过包内入口执行，`<job-dir>` 取本 Job 的实际目录：

```bash
python3.12 <skill-root>/run.py job status --job <job-dir>
python3.12 <skill-root>/run.py job revise --job <job-dir> --stage visual_assets --reason <本次反馈> --artifact-scope <segment-id>
python3.12 <skill-root>/run.py run_stage --job-context <workspace>/job-context.json --review-json <本版真实用户反馈.json>
```

`--artifact-scope` 可重复，实际编号先解析到当前清单的 segment，不重编号。制作继续使用 `run_stage`；不提供通用人工 `approve`、手工 `ready/complete` 或第二套初始化入口。终验 JSON 标识本 Job、`stage=delivery`、用户看到的当前成片与交付 manifest，以及实际用户原话。默认入口和显式 `--stage delivery` 使用同一处理逻辑；旧版反馈拒绝，不静默丢弃。

交付身份来自当前阶段登记的 `12-delivery/delivery-manifest.json` 文件 SHA。稳定交片保存在 `delivered/<身份>/final.mp4`，回执位于 `manifests/delivery/<身份>/delivered.json` 与 `accepted.json`。以返回的 `delivery_file` 交片，后续返修不能覆盖它。全局工作流计数变化不使同一版验收失效；新交付身份必须重新终验。查询只读当前阶段身份，不扫描历史记录猜最新版，也不写回执。
