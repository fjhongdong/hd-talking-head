# hd-talking-head

完整的口播视频制作 Skill。执行规则与操作流程见 [SKILL.md](SKILL.md)。用户素材和 Job 输出放在包外。

首次使用时，在包根运行 `python3.12 run.py prepare`，再按 Skill 的流程启动任务并确认所需渠道。

- `scripts/`、`edit/`：制作脚本与剪辑运行代码。
- `references/`、`assets/`：流程说明、模板与证据。
- `vendor/`：第三方源码和子 Skill。
- `archives/`：源码和运行依赖归档。
- `runtime/`：本机准备的运行环境。
