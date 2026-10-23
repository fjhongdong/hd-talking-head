# Muyang Flat Animation

把一句中文口播、观点或抽象概念，制作成适合知识讲解视频的“纸上钢笔线稿 + 选择性彩铅填色”动画素材。

这个 Skill 使用三闸门工作流：

1. 先确认视觉命题、构图、动效与音效方案。
2. 再生成并确认动作完成后的静帧。
3. 最后调用 Gemini 生成视频，并进行逐帧和音轨检查。

它支持人物叙事与无人物内容可视化、9:16/16:9 等自定义尺寸、多套语义配色，以及带同步轻量音效或静音输出。


https://github.com/user-attachments/assets/c3c7dbb2-a076-44f3-b856-73acda1905a5

https://github.com/user-attachments/assets/68d74a64-3d5d-47c9-91e3-53e79a0b4aad

https://github.com/user-attachments/assets/535bb3c2-813c-4b4e-89d7-8efd35dd6b0c



## 动效特点

- 固定镜头，保持人物身份、物件设计和纸面构图稳定。
- 使用“主动作 + 接力响应 + 生命微动作 + 短暂强调”的分层动效。
- 允许人物眨眼、呼吸、手部操作，以及图标错峰接力和结构生长。
- 每条箭头或连接线都必须有明确的起点与终点，不生成无来源的杂乱线条。
- 生长动画表示对象从固定起点按自身结构形成，不专指植物。
- 默认生成适合知识讲解的轻量动作音效。
- 严格禁止铅笔、钢笔、马克笔、粉笔书写以及任何笔纸摩擦声。

## 安装

需要 Python 3.10+、FFmpeg、FFprobe 和可用的 Gemini API Key。

```bash
git clone https://github.com/yokel1121/muyang-flat-animation.git
pip install -r muyang-flat-animation/requirements.txt
```

将 Skill 目录复制到 Codex Skills 目录：

### Windows PowerShell

```powershell
Copy-Item -Recurse .\muyang-flat-animation "$env:USERPROFILE\.codex\skills\muyang-flat-animation"
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "你的_API_Key", "User")
```

### macOS / Linux

```bash
cp -R ./muyang-flat-animation ~/.codex/skills/muyang-flat-animation
export GEMINI_API_KEY="your_api_key"
```

检查环境：

```bash
python ~/.codex/skills/muyang-flat-animation/scripts/check_setup.py
```

Windows 可将上面的路径替换为 `%USERPROFILE%\.codex\skills\...`。

## 使用示例

```text
$muyang-flat-animation 16:9，制作：学会用 AI 放大自己的能力
```

```text
$muyang-flat-animation 无人物，9:16，制作：信息不是越多越好，而是越清楚越好
```

```text
$muyang-flat-animation 3:4，鼠尾草绿，无声，制作：把复杂流程整理清楚
```

Skill 会先停在动画方案确认阶段。回复“通过”或“继续”后生成静帧；静帧再次确认后才生成视频。

## 可配置项

| 参数 | 可选值 | 默认值 |
|---|---|---|
| 主体模式 | `character` / `content-only` | `character` |
| 配色 | 自动语义配色、内置预设或自定义色值 | `semantic-auto` |
| 画布 | 9:16、16:9、3:4、4:5、1:1 或明确像素 | 720×1280 |
| 声音 | `sfx` / `silent` | `sfx` |
| 时长 | Gemini 当前模型支持的整数秒数 | 6 秒 |

详细配色、画幅和动作语法位于 `muyang-flat-animation/references/`。

## 自定义画风参考

开源仓库不包含来源不明的参考插画。你可以把自己有权使用的图片放入：

```text
muyang-flat-animation/assets/references/style-reference-01.png
```

图片只会作为 style-only references，约束纸面、线稿、彩铅颗粒、留白和图解语言。没有图片时，Skill 会使用内置的完整文字画风规范。

不要提交无授权图片；该目录已默认加入 `.gitignore`。

## 直接运行视频生成器

创建 jobs JSON：

```json
[
  {
    "prompt": "Your complete motion prompt",
    "image": ["final-still.png"],
    "output": "final.mp4",
    "aspect_ratio": "16:9",
    "duration": 6
  }
]
```

运行：

```bash
python muyang-flat-animation/scripts/generate_video.py --batch jobs.json --concurrency 1
```

默认模型是 `gemini-omni-flash-preview`。模型名称、可用地区、额度和计费规则可能变化；遇到 `429 RESOURCE_EXHAUSTED` 时，请检查 Google AI Studio 项目余额或切换到有额度的 API Key。

## 输出检查

```bash
python muyang-flat-animation/scripts/inspect_video.py final.mp4 \
  --reference final-still.png \
  --output-dir qa
```

检查项包括镜头漂移、人物和手部一致性、随机线条、画风漂移、音轨存在性和输出规格。是否出现笔纸摩擦声仍需人工试听确认。

## 项目结构

```text
.
├── README.md
├── LICENSE
├── requirements.txt
└── muyang-flat-animation/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── evals/evals.json
    ├── references/
    └── scripts/
```

## 致谢

工作流参考 [pyang5166/gbro-collage-broll](https://github.com/pyang5166/gbro-collage-broll)。
## License

[MIT](LICENSE)
