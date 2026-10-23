# 花叔历史执行记录核实（2026-10-24）

已恢复 6 份 `execution-v8` receipt 为 提交 `d5fb95aa` 中的原始字节。它们的历史入口哈希均为 `67700153cbc84195875c1f72bb57406e3c4ba6e05523c5d839a5543b16aa0e90`，与各自 `source-registry.json` 中保存的 v7 native-source 适配器快照一致。

证据链：

- `9ba8f6d`（2026-10-22 16:08:10）保存了这 6 份执行记录及其原始产物证据。
- `a97fc2a`（2026-10-23 15:13:30）修改花叔适配器，隔离 `PYTHONPATH`，产生新代码哈希 `b8f6840c63fc1afe89d79caf0cd2eca4c947c0f1c1fa03d0b304a454bf366742`。
- `e317f8f`（2026-10-23 23:07:18）打包时把 6 份 receipt 的入口哈希改成新哈希；没有发现对应的重新执行日志。此次恢复保留历史证据，不表示当前适配器已重新验证。

6 份恢复文件的 SHA256、进程 ID、产物哈希和字节数如下：

| case | receipt SHA256 | invocation_id | output SHA256 | bytes |
|---|---|---|---|---:|
| t2_keynote_ui/1 | `8e6f5946afab77acc47d993e1dc94fca71f33d3cccac22992c3c9dca69d6c7cf` | `process-3c242ca0838a9d93f653f5cad62affad` | `826b44789e29c562a7ef81ee3fe1a8f037f928aea391e45660666db414040fe5` | 8576680 |
| t2_keynote_ui/2 | `19c2ff01770c19b95dd509b6885f2a9c31b655a2f986ed41df9e086205c60a51` | `process-4bfc03b7410fa970d0948413d7f7febf` | `10c4d684e31e0b6e8775846903631bc17c00f5aa164fd4ec4941d8c8a4f5e75a` | 8656224 |
| y1_kurzgesagt/1 | `0c0808084e0bfb781213a1c64092f096d2a9b39f22bbfe52d235c9e4c6e3a037` | `process-e072d7ca22d0f550cee9e45ca4e1c4b0` | `a1dfdaab892a43b218ca5fede11285ea2edcd9b9973d01cd633e76af144d928e` | 2264410 |
| y1_kurzgesagt/2 | `6664a8a25fc85cc447d1e94bc255dba80377987387ecb8c6614eb7c8b075de00` | `process-f12719c7bda2fc3fab9110ee9e73c223` | `b2fc85367d47b015ea365222b2ff315d0be8fb5cc04c15fb0c431283a61ba8ef` | 2291551 |
| y2_vox/1 | `b7e3b8373039fba0e070bdcfec9718c9f891853182f4563493c99e4a078ad379` | `process-b1431b4dcd8782bf8b73eee57fa7b2a9` | `9c9591be572713f67c444a5c0bd78d2ceaef84f997fc320707959e499540b8fa` | 9950290 |
| y2_vox/2 | `2eaf0e68607b6315246226298052fe67f45a56d7fd247ac56cb388e32064e66d` | `process-6769f8c6eb5ffa826f5fa6ef0108d4d7` | `9b3c2dea31fcbbdd95afb63f3d5312e19d9e1bea6affdf085325288e637ab60d` | 10072271 |

当前模板注册表的 6 个回执引用摘要及 3 个派生 verification_id 随恢复内容同步更新；历史 source registry、人工确认和已批准媒体未修改。历史校验读取原始 source registry 的不可变代码快照；当前执行仍固定实际代码与启动器身份。未调用当前适配器重新渲染，历史样片不能证明新启动器已实测。
