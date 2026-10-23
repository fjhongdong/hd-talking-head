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

当前完整运行环境为 macOS arm64，需要 Python 3.12、Node 和 FFmpeg。其他系统尚未验证，包内 TalkCraft 原生依赖不适用于其他系统。

独立验证从仓库外的新目录调用该包，检查预检和一条本地短渲染。图片和视频生成渠道仍由用户选择并授权，打包验证不调用外部生成。旧 Job、用户素材和批准记录保留原位置；移动 Skill 不自动迁移或重签旧 Job。
