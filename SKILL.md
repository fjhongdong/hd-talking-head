---
name: hd-talking-head
description: 完整口播视频制作 Skill。用户提供原始视频和文案后，完成口播清理、语义分析、贴片与 B-roll 匹配、字幕和成片交付。包含运行代码、模板、子 Skill 和必要资源，可从整个文件夹独立运行。
---

# HD 口播视频

这是唯一完整 Skill 文件夹。以本文件所在目录为包根，先读取[完整流程与执行合同](skill-development/hd-talking-head/SKILL.md)。运行代码、模板和已确认内容均在本包内；原目录关系保留，避免改变已有模板身份。

1. 检查本地环境，让用户确定图片生成渠道和视频生成渠道、精确模型及账号授权。两个渠道同时服务直接生成和模板内部调用。
2. 导入原视频与文案，保留原件，完成封面、口播转写、口播清理和剪辑。
3. 理解剪后语义，列出全部贴片与 B-roll：时间点、语义、标签，再按标签匹配动效模板。
4. 将完整列表及匹配模板交给用户一次确认。随后完成制作和内部检查，直接交付成片，不增加样片、字幕、预览或成片确认步骤。

新任务先运行：

```bash
python3.12 <包根>/run.py verify
python3.12 <包根>/run.py prepare
python3.12 <包根>/run.py initialize_video_job --jobs-root <独立工作目录> --title "<标题>" --video <视频绝对路径> --script <文案绝对路径>
```

通过 `run.py preflight` 检查 Job 环境，通过 `run.py run_stage` 执行正式阶段，通过 `run.py run_generation` 调用已选生成渠道。参数见[阶段入口](skill-development/hd-talking-head/references/stage-runner.md)和[发布合同](skill-development/hd-talking-head/references/release-contract.md)。

本包包含全部制作代码与固定资源。当前运行环境为 macOS arm64；TalkCraft 固定运行依赖随包提供。Python 3.12、Node、FFmpeg、浏览器和其余按锁文件安装的依赖属于机器环境；AI 服务使用用户选择的渠道与凭据。用户素材和 Job 输出存放在独立工作目录，原有确认记录不会因复制 Skill 被重写。
