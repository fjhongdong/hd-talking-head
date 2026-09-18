# 运行时代码导出与跨目录部署

此入口仅用于维护者授权的代码交接，不是旧 Job 自动迁移器。

```bash
python3 <skill>/scripts/runtime_bundle.py export --project-root <source-project> --output <new-runtime.zip>
python3 <skill>/scripts/runtime_bundle.py verify --bundle <new-runtime.zip>
python3 <skill>/scripts/runtime_bundle.py install --bundle <new-runtime.zip> --project-root <new-project>
```

`<new-project>` 必须不存在，父目录必须存在。已有项目不可覆盖安装；部署后显式选择新根路径。输出 ZIP 也必须不存在。安装前完整验证清单 SHA-256、文件集合、重复项、路径与文件类型；拒绝 symlink、路径穿越、额外文件和覆盖。SHA-256 证明字节完整性，不证明来源可信；只安装可信维护者提供的包。不要导入未知来源的 Python。

代码包仅含可选的 `edit/__init__.py`（允许 namespace package）、`edit/hd/__init__.py`、`edit/hd/tools/` 直接下的 Python 模块，以及 `edit/v5/tools/{openlux_images,bold_subtitles,build_visual_plan,bold_layouts,style_tokens}.py` 五个必需辅助模块。当前运行时不需要其他项目固定资产；模板证据和适配器属于另行完整传输的唯一 Skill 包。不携带媒体、Job、`.env`、密钥、缓存、参考仓库、项目测试或历史成片。若以后增加运行时固定资产依赖，应先更新明确白名单和测试，不扩大为复制项目目录。

在源项目之外的目录，以新进程设置 `PYTHONPATH=<new-project>`，导入 `edit.hd.tools.startup` 并调用 `runtime_identity(Path(<new-project>))`；同时导入本次阶段所需 runner，检查模块 `__file__` 均来自新根。此验证只是干净导入，不运行 FFmpeg、不生成媒体、不证明新机器具备生产环境。

新机器需要 Pillow 才能导入封面/字幕模块；导入测试应使用已选定并完成预检的解释器。不复制整个 V5 项目。

设置 `HD_RUNTIME_PROJECT_ROOT=<source-project>` 后执行 `python3 <skill>/tests/test_runtime_bundle.py`，会导出真实源码、安装到临时新根，并在新根之外以独立进程导入全部 HD tools，逐个核对模块来源。未设置该变量时，此集成项明确显示 skipped，不能把普通单元测试结果算作真实运行时部署验证。

V5 辅助模块未发现另外的项目内固定资产读取：文件读写消费调用参数、计划、媒体或安全配置；字幕字体按系统路径寻找。模板附件、中文字体、FFmpeg、provider 连接和实际素材仍必须依赖预检及阶段检查，代码导入成功不代表这些动态执行依赖已就绪，也不是独立可生产包的验收。

新机器仍需校验完整 Skill 发布包、按依赖预检合同检查 Python/FFmpeg/字体/外部依赖及 provider，并为新 Job 完成本次配置确认。路径、Python 或源码身份变化会使旧 Job 身份不一致；保留原批准资产，明确决定受控迁移，不重签旧 `job-context.json`、workflow 或发布身份。安装失败的非空新目录保留供检查，不自动清理或继续覆盖。
