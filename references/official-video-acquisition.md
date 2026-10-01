# 官方视频下载 Skill 调用与验收

适用于已按语义选中 `official_material` 视频、但当前 Job 尚无已验证本地媒体的段落。先核对 Job 用户资料，已有相同素材不重复下载。优先找发布者的课程页、演讲页或其链接的官方播放器；核对发布者、人物、时间和台词，不能把搜索摘要、字幕或第三方搬运当作原片。

## 上游能力

项目内上游是 OpenMontage 的 [`video-download`](../../vendor/OpenMontage-video-download/.agents/skills/video-download/SKILL.md)，来源 `https://github.com/calesthio/openmontage`，本次验证提交 `08e2151fa02de28a5d6a312b3d575692bf147ad7`。新 Job 开始时检查该 Skill 文件与 Git 提交；目录缺失时从来源仓库克隆、切到固定提交、只检出 `.agents/skills/video-download` 到 `skill-development/vendor/OpenMontage-video-download`；目录已存在但异常、版本不同或文件不全时停止，不覆盖用户文件、不改全局 Skill。首次获取前检查 `yt-dlp`、`ffmpeg` 可用，缺失时补齐执行依赖。只读说明不是调用：完整读取上游 Skill 后，按其 `metadata → formats → download / subtitles` 入口执行当前来源，并保存本次调用、版本、退出码和产物路径。父 Skill 只负责来源选择、Job 绑定与验收，不另写下载器。

站点变化时可按 yt-dlp 官方说明更新运行时；YouTube 遇到 JavaScript 挑战时，使用带 `yt-dlp-ejs` 的当前 `yt-dlp[default]` 与受支持的 Node 运行时。浏览器登录状态只能在本机临时读取，不导出 cookie 文件、不记录凭据。每次先列出实际可用格式，再选符合用途的最高可下载格式；不要仅凭格式表或扩展名宣称已成功。只下载当前已确认的必要区间，放入当前 Job 的 `edit/downloads/`；来源不明确、权限拒绝或下载失败时报告并停在该来源，不伪造成功、不自动换其他来源类别。

下载工具可独立使用项目内 `edit/hd/integrations/video-download-runtime/` 的 Python 环境，不改变已锁定的剪辑 Python 或全局安装。当前 yt-dlp 不再支持旧剪辑环境的 Python 3.9 时，在已获依赖安装许可的范围内，用本机受支持的 Python 创建该环境并安装 `yt-dlp[default]`。之后 metadata、formats、download 都使用此环境的 `bin/yt-dlp`，YouTube 显式传入 `--js-runtimes node`；不再调用旧 `python3 -m yt_dlp`。依赖预检优先检查此路径的真实 `--version`，存在但损坏时停止，不静默退回旧版。版本检查仍不证明站点可下载，实际视频文件才是下载结果。下载日志不保留 Googlevideo 临时签名 URL、浏览器 cookie 或其它凭据；只保存公开来源 URL、选中格式、工具版本、退出码和本地文件身份。

## 下载后验收

对本地文件运行 FFprobe，记录视频/音频流、尺寸、帧率、时长、SHA-256 和对应来源 URL、发布者、原片时间区间；抽看入口、关键台词与出口，核对人物和事实语境。字幕仅用于定位和复核，不能替代画面。把可用文件作为当前 Job 的 `official_material` 来源绑定，继续接受 `visual_canary` 的实际合成 QA；下载成功不等于片段或成片获批。

清晰度按真实文件判断：即使原录播只有低清，B-roll 仍由官方资料占据整屏版式，口播人物只能在同步小窗。低清原片可保留横屏比例作为版式里的主视觉，周围用可核实的来源信息和从该资料派生的弱化背景填满竖屏；不得反过来让 A-roll 全屏、资料只占小窗，也不得把上采样伪称原生高清。若放大后人物或关键内容不可辨，保持来源待处理并报告限制，不假装通过正式画质门。
