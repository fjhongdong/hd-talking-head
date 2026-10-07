# 视觉修订：只重建变化镜头

本合同适用于支持 `segment-inputs` 的正式合成器及带 `segment_input_identities` 的资产清单。它只约束媒体复用；用户资料替换与撤回统一遵循 [权威素材使用回执与变更事务](material-usage-contract.md)，不另设处理分支。

## 执行顺序

1. 恢复同一个 Job，核对当前 runtime/release 和已批准文件，不新建任务、不重新提炼关键词或生成封面。
   同时读取 `manifests/confirmed-content.json`，从当前正式计划增量修改；禁止以较早样片或快照重建全片、覆盖后来增加的内容。新增贴片或样片被用户要求保留后，立即将原生调用、词锚和对应组件提交到同一 Job 的正式 director，并追加保留记录。局部预览不能代替这一步。
2. 文案、来源、时码、字体、头像或配方需要修改时，通过 `state.revise` 返回最早受影响阶段。只有重试同一冻结配方时才直接修订 `visual_assets`，可使用 `artifact_scope=("seg-xxx",)` 指定强制重做段。
3. 修改后的 `visual_direction` 仍须报审。新 canary 选取受影响的代表镜头及必要边界，总长不超过 30 秒，并使用正式配方；用户批准后才能进入正式资产。
4. 调用原有 `visual_assets.prepare_visual_assets` / `visual_assets_v2.prepare_visual_assets_v2`。runner 自动判定复用，不手工复制文件、修改 identity 或冒充批准。
5. 正式资产完成后，展示新 manifest 中的 `reused_formal_segment_ids` 和 `reused_canary_segment_ids`。其余 ID 是本轮合成段；是否真正发出外部请求另以执行器 receipt/ledger 为准，不能用合成段数冒充请求数。
6. 复核片段/关键帧 SHA、当前计划身份和完整视觉轨；按正常人工门推进。整轨仍需组装，字幕、preview、delivery 仍按现有 DAG 重新验证，不能把“没有重渲染未变镜头”说成“全部下游都不失效”。

## 复用判据

跨计划复用必须同时满足：

- 同一 Job、同一实际合成器合同。旧 manifest 与 workflow 的 artifacts/lineage 文件集合、大小和哈希一致；丢失、损坏或多出未知文件均停止。
- manifest 冻结的逐段输入指纹一致：完整 segment（含时码、可见文案、视觉意图、策略、来源、ShotRecipe、头像和动效）以及内容分析、剪辑计划、时间轴、A-roll SHA 和画布身份。只看 ID、文件名或是否出现在修改列表中不够。
- 现有严格 replay 校验通过：组件配方与原执行证据匹配，组件文件、A-roll、片段媒体、三态关键帧的路径、字节数、SHA 和媒体合同仍有效。
- 未被当前 `artifact_scope` 显式要求重做。计划变更后，当前计划新批准的 canary 字节优先于旧正式资产，即使该镜头配方没有变化也不能回退。其余镜头复用合格的正式资产；同一计划内重试时才保持“当前正式资产优先于更早 canary”的顺序。没有合格产物时执行冻结配方。

片段的 `generation_identity` 绑定完整 segment、A-roll、组件证据与 renderer；父级资产/canary manifest 继续绑定整份已批准 VisualPlan SHA。这样修改其他镜头不会改变本片段身份，但本片段文案、时码、来源或裁切的变化仍会触发重建。复用保存原片段字节和组件调用证据，不伪造新的供应商调用。

损坏不是普通缓存未命中：不能通过重新生成覆盖错误并继续。真正发生的输入变更会使指纹不一致，正常重建该段；旧批准证据损坏则先停止并保留现场。

## 已确认内容的保留检查

首次进入正式 `visual_direction` 前建立本 Job 的 `manifests/confirmed-content.json`；没有指定保留项时使用空数组，不复制其他 Job 的记录。宿主依据本次用户要求、已认可样片或当前正式批准计划填写，不把未认可候选自动称作用户批准。每次认可新增内容立即追加，之后不要从较早快照覆盖此文件。

```json
{
  "schema_version": 1,
  "job_id": "<当前Job ID>",
  "source_words": [{"index": 0, "text": "<指定保留的原转写词>"}],
  "visuals": [{
    "component_id": "<稳定组件ID>",
    "composition_family": "aroll_with_overlay",
    "visible_text": ["<已确定可见文案>"],
    "binding": {"dependency_id": "<实际依赖>", "template_id": "<实际模板>"}
  }]
}
```

`source_words` 绑定源转写词，不绑定易变化的剪后秒数；`visuals` 绑定组件 ID、构图家族、文案及需要保持的来源字段。代码组件可冻结入口、模板与源码身份；已完成 AI 视频可冻结 provider、模型、generation ID 和媒体 SHA。不冻结整个 brief、A-roll SHA、策略 revision 或起止时间，使合法的时钟重绑定仍能通过。

`edit.hd.tools.confirmed_content.check_confirmed_content` 在正式视觉发布前及正式预览入口检查缺失组件、文案/来源变化和指定词被删除。Skill 管理的 Job 缺少这份记录也停止；检查不重新生成资产、不替代现有配方/媒体核验。用户明确要求删除或替换某项时，才依据这次真实修改同步更新对应保留项，再走正式修订；不能为通过检查清空清单。该检查保障内容不漏项，真实动画、美观与时机仍须检查实际成片。

## 版本与未实现边界

- 升级前的合成器和资产没有此合同，不自动重新签署旧 manifest 或把旧输出当作新合同产物。恢复旧 Job 时遵循 [发布与调用合同](release-contract.md)，明确处理差异；历史成片保持不变。
- 主项目与工作树的合成器版本可以不同，不能相互冒充；启动记录必须绑定实际源码。文件中出现 `segment-inputs` 字样也不能替代发布核验和功能回归。
- 本次未实现选择性保留所有下游批准，也未实现 canary 本身的跨计划自动缓存。短样片重新报审和完整交付校验仍保留。
- 运行采用串行；一次只处理一个片段。复用不调用生成模型，不要求重做用户已批准的整片测试。
