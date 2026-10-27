# Lemo Wake 完整原生调用

渠道 `lemo-wake` → 唯一模板 `lemo-wake/wake` → 原图主体、动作、关系等标签。候选 ID 为 `lemo-wake:wake`。不把内部 11 类图、49 个 FX 或 27 个 reset 登记成模板。完整上游包在 `skill-development/vendor/lemo-wake`，固定提交 `f070df8bdf891d792012aabc054582b16e04f759`；原生入口为 `skills/wake/SKILL.md`。不改第三方文件，不执行其自动更新。

## 规划和确认

首镜使用本 Job 已批准 `04-cover/cover-delivery-raster.png`；正文 B-roll 必须有真实、可用、哈希绑定的图。没有图时列明缺口，先沿既有生成渠道准备，不能把 Wake 当作生图 API。父级交接语义、时钟和验收要求；原生 Skill 自己选择读图方法、拆层、DIRECTOR 和主体动作。父级不预设内部 FX、模型或生成代码。

`treatment.skill_selection.opening` 唯一声明 `{segment_id, component_id, candidate_id}`。首段从 t=0 开始，使用单一整屏 Wake 组件，隐藏 presenter，不带 avatar。首镜纳入 B-roll 列表、计数和一次完整清单确认。正文 Wake 项也参与同一次匹配和全片渠道/模板联合选择，不占用额外模板身份。

每项在 `native-inputs/` 写不可变计划 brief，由 `lemo_wake_adapter.validate_brief` 校验。字段为：

- `schema_version=1`、`job_id`、`source_binding={aroll_sha256,segment_id,start,end}`。
- `image={job_path,sha256,byte_count}`：Job 内已有原图。
- `purpose=opening|body`、`semantic_goal`、`composition={width:1080,height:1920,fps:24,frames}`。
- `template_request={semantic_family,information_units,numeric_values:[],numeric_scale:not_applicable}`。
- `result_record_path`：该项将来写入的 Job 内 `native-inputs/*.json` 完成记录路径。

来源图片、语义和时钟在确认前冻结；不要求提前完成动画。清单确认后，阶段入口返回 `execute_native_skill`，附上已批准的当前原话和局部词锚。原生子任务读取完整 Skill 后执行，不再要求用户确认。宿主只在所选渠道准备其依赖；缺本地模型时遵循原生同意流程，不代替用户同意下载。

## 原生执行与回传

原生子任务在本 Job 内创建自己的项目、DIRECTOR 和可读动画。默认示例缓推不是最终制作。完成静帧检查后，使用原生 `render.mjs`、`encode.py`、`qa.py`。单次播放，不运行 reset 或回环；编码 `--fps 24 --no-gif --no-webp --no-sticker`，QA `--no-loop --json <Job内报告> --src <原生src> --encode <原生encode.json>`。QA JSON 和编码输出放在 `src` 外。

自有薄桥仅记录原生命令和接收结果，不实现创作、渲染或编码：

```python
from lemo_wake_adapter import capture_call, publish_completed
# job_dir、brief_path、project_src 都来自本次 execute_native_skill action。
# argv 是原生 Skill 指示的完整原生命令数组，不使用 shell 拼接。
record = capture_call(job_dir, brief_path, 'render', argv, project_src)
# encode、qa 同理；3条成功记录共同绑定同一份项目源。
result = publish_completed(job_dir, brief_path, project_src, video, native_qa, calls)
```

`--capture render|encode|qa --argv-json <JSON数组>` 和 `--publish` 提供相同 CLI，`--help` 查看参数。完成记录绑定原图、原计划 SHA、原生项目、三条真实命令、原生 QA 和媒体规格。已存在的不同结果不覆盖。后续正式执行器冻结这些输入，只接收原视频字节，不重复制作；任何哈希、来源、时钟或原生 QA 失败会停止。

宿主观察实际首中尾及运动边界：封面完整、无重复人物、主体确实运动、中文无裁切重叠、切入正文自然。原生 QA 的 WARN 须分析；若是设计好的稳定阅读可接受，若是卡顿、裁字或重影则拒绝。技术 PASS 不替代视觉验收。将原生项目 entry、DIRECTOR、结果记录和源图加入该项的实际语义引用，更新 realization treatment 后重入阶段；计划 brief 和已确认绑定保持不变。

封面 PNG 仍作为平台封面。正式预览 `opening=None`，不开静态前贴；编号 1、原声和唯一字幕轨均从正文第 0 帧开始。现有成片与旧 Job 不迁移、不重签、不重做。
