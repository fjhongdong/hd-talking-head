# 音效库（导出时自动混入 MOV 音轨）

**自带 15 个默认音效**,在隔壁的 `public/sfx-default/`,全部可以商用、随仓库分发、不用署名
(13 个来自 Kenney 的 CC0 音效包,2 个是代码合成的)。来源见那个文件夹的「来源与授权.txt」。

这个文件夹(`public/sfx/`)是留给你放自己音效的。

## 换成自己的音效

1. 下载 mp3,下载前确认许可允许你的用途(比如 [Freesound](https://freesound.org/) 上标了 CC0 的)
2. 放进本文件夹,**和默认音效同名就会替换它**(比如放一个 `pop.mp3`,所有用 `pop` 的卡就换成你的声音)
3. 想加新的音效名:放进来,再在 `src/components/ParamsPanel.tsx` 的 `SFX_OPTIONS` 里加一行,下拉里就能选到

本文件夹有同名文件就优先用它,没有就用默认音效。默认音效那个文件夹不用动,
你放在这里的文件不会进仓库,更新时也不会冲突。

默认音效的名字:`pop-light` `pop` `pop-cluster` `click` `type` `ding` `chime` `sparkle`
`rise` `whoosh` `whoosh-soft` `hit-soft` `impact` `glitch` `shutter`。
特效类型 → 默认音效的对应关系写在 `scripts/export-frames.mjs` 的 `KIND_SFX`。

## 不想要音效

右栏「音效」选「🔇 无音效」即可。
