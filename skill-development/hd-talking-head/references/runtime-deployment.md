# 完整 Skill 的导出与运行

`runtime_bundle.py` 导出整个 Skill，包含剪辑代码、TalkCraft、模板、子 Skill、锁文件和历史证据。

```bash
python3 <implementation>/scripts/runtime_bundle.py export --project-root <package> --output <package.zip>
python3 <implementation>/scripts/runtime_bundle.py verify --bundle <package.zip>
python3 <implementation>/scripts/runtime_bundle.py install --bundle <package.zip> --project-root <new-package>
python3.12 <new-package>/run.py prepare
```

`<implementation>` 为 `<package>/skill-development/hd-talking-head`。压缩包放在包外，安装目标必须不存在。导出复用正式发布清单，包含已验证的 TalkCraft 固定运行依赖归档，不携带其他安装目录、缓存、密钥和用户 Job。复制完整文件夹也能取得相同代码与资源。

首次准备从包内归档恢复模板来源的真实 Git 身份，并恢复 TalkCraft 固定运行依赖，再安装其余锁定的 Python、npm 和浏览器依赖。模板源码无需原开发项目；环境安装仍需相应下载来源可访问。

## Python 首次初始化与常规检查

常规 Python 可用性检查的整个子进程固定限时 20 秒。只有同一次 `prepare` 初查确认 `cv2` 缺失，且 pip 明确成功安装 `opencv-python-headless`，随后的那一次安装后首调才预先固定为 60 秒。它仍在同一子进程完成模块导入和版本元数据查询，不先执行预热。Pillow、requests、NumPy、已有 OpenCV，以及仅其他包新装时的 OpenCV 复检仍为 20 秒。已有包损坏或任一检查失败即停止，不重装、不延长已失败进程、不自动重试，也没有 CLI 或清单超时配置。

这个差异来自 2026-10-31 的隔离首次准备取证：OpenCV 4.12.0.88 的 arm64 扩展随附 66 个动态库。目标导入停在原生扩展创建；同一时间的 macOS AMFI、XProtect 和系统策略日志显示主扩展与动态库逐项安全评估并放行。49 项已完成评估合计约 19.65 秒，20 秒截止时下一库仍在评估。按每库中位约 0.38 秒估计完整链约 26 秒；60 秒另留主扩展初始化和调度余量。这是首次初始化的有界预算，不是所有机器的时长保证。更早那次仅留下超时与人工继续记录，没有系统日志，不能据本次取证倒推其具体原因。

验收使用新包、新 Python 依赖位置和不继承系统包的 Python 3.12 venv，移除继承的 `PYTHONHOME`、`PYTHONPATH` 并设置 `PYTHONNOUSERSITE=1`。直接运行现有 `run.py prepare` 一次，不提前导入 cv2。现有准备报告保存 `probe_context`、`probe_timeout_seconds`、各阶段耗时、候选 `probe_candidate_path` 及成功导入后的 `probe_loaded_path`；15 秒单次有界堆栈诊断保留。失败保留现场后停止。一次通过只证明该环境本次新安装的首次准备通过，不声称操作系统缓存全冷，也不重签旧 Job 或旧样片。

仅随包提供所选源码文件的 HyperFrames 使用 `source-repositories/index.json` 中的固定提交和逐文件摘要核对版本，不复制完整 Git 历史。准备与绑定预检读取同一份来源登记；不得把 Skill 主仓库的提交误当作嵌套源码版本。
来源登记统一保存在包的 `source-repositories/index.json`，不向上游源码目录额外写入身份标记，避免原生检查把打包文件视为源码改动。

当前完整运行环境为 macOS arm64，需要 Python 3.12、Node 和 FFmpeg。其他系统尚未验证，包内 TalkCraft 原生依赖不适用于其他系统。

独立验证从仓库外的新目录调用该包，检查预检和一条本地短渲染。图片和视频生成渠道仍由用户选择并授权，打包验证不调用外部生成。旧 Job、用户素材和批准记录保留原位置；移动 Skill 不自动迁移或重签旧 Job。
