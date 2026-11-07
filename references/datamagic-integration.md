# DataMagic 竖屏榜单

原生仓库为 [HKUSTDial/DataMagic](https://github.com/HKUSTDial/DataMagic)，固定提交 `3a66365b6dcab798efc76baf54a3039d0b273f2c`。完整快照随包，展开到 `vendor/DataMagic/`。选中时读取原生 `skills/datamagic/SKILL.md`、`cards/recipes/PortraitRankedReveal.md` 及其输入结构和实现。首次使用按其锁文件在 `vendor/DataMagic/cards/` 运行 `npm ci`，用现有 Chrome 和 FFmpeg。运行时检查由本次选中模板触发。

`datamagic:portrait-ranked-reveal` 对应 `datamagic/portrait-ranked-reveal`。当前限定两个同口径、非负的真实数据对象和完整 6 秒词窗。按数值从低到高揭晓，比较结论须由输入数据支持。真实对象、数值、单位、结论、出处和揭晓时间传入原生 `props`。本路线使用原生纯数据版式。

完整清单注明模板的固定眉题「DATAMAGIC CARDS / 竖屏榜单」及其揭晓、结论标签。结论和出处保持简短，正文放在圆窗左侧，出处另附可核对的原始链接。

采用 `scripts/datamagic_native_adapter.py` 的正式引用适配器。brief 含 `schema_version`、`source_binding`、`composition`、`template_request` 和 `props`。`composition` 为 1080×1920、24 帧、144 帧总长。`template_request` 使用 `numeric_comparison`、两个信息单元、与 `props.rows` 顺序相同的原始数值及 `linear` 尺度。

原生默认演示是 10 秒、30 帧。当前调用通过 Remotion 原生参数设为 144 帧、24 帧并关闭音轨，保留完整设问、揭晓和结论。源画面输出全范围像素时，母级仅做等时有限范围转换。字幕放在两行榜单和结论之间，保留底部资料来源与右下圆窗。只有符合该布局和时窗的全屏 B-roll 可用。
