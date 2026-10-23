# HD Talking Head

复制整个目录即可取得完整 Skill，包括剪辑运行代码、字幕、贴片、B-roll 模板、子 Skill、来源信息和固定资源。

入口是 [SKILL.md](SKILL.md) 和 `run.py`。原实现位于 `skill-development/hd-talking-head/`，保持模板相对路径；它是本包内部目录，无需另一个项目。

```bash
python3.12 /absolute/path/hd-talking-head/run.py verify
python3.12 /absolute/path/hd-talking-head/run.py prepare
python3.12 /absolute/path/hd-talking-head/run.py --help
```

当前完整运行环境为 macOS arm64，需 Python 3.12、Node 和 FFmpeg。TalkCraft 的固定运行依赖随包提供，首次启动恢复；其余依赖按包内锁定版本安装。开始任务时确认生图、生视频渠道，素材和成片保存到独立 Job 目录。详见[发布与调用说明](skill-development/hd-talking-head/references/release-contract.md)。
