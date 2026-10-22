# 测试说明

## 运行

```bash
tests/run.sh                 # 全部测试模块(约 3-4 分钟,282 个用例)
tests/run.sh test_release_integrity test_motion_capability_pins   # 只跑指定模块
```

`run.sh` 自动设置 `PYTHONPATH` 指向项目根,并按以下顺序选择解释器:
项目运行时解释器(`skill-development/runtime/talking-head-python*/`,
由 `project_python.py --prepare` 创建,自带 Pillow/NumPy)→ PATH 上最新的
>= 3.10(项目运行时代码使用 `zip(strict=True)` 等 3.10+ 语法)。

手动运行单个文件时需要自己带上:

```bash
PYTHONPATH=<项目根> python3 tests/test_job_initialization.py
```

## 依赖位置

- Python 依赖(Pillow/NumPy/OpenCV)统一维护在
  `skill-development/runtime/talking-head-python*/`,由
  `project_python.py --prepare` 装入,run.sh 自动挂到 PYTHONPATH。
- hyperframes 单仓测试所需的源码仓依赖位于参考项目克隆自身的
  node_modules(gitignored)。该仓库由 bun 管理:缺时任仓库根目录
  `bun install`(装依赖)再 `bun run build`(生成 node 运行条件
  所需的各包 dist)。

## 依赖与跳过

- 纯包内测试(发布完整性、注册表、示例 schema)不需要项目运行时。
- 依赖 `edit/hd` 运行时的模块在缺失环境下会**跳过**而不是崩溃;本机正常检出即全跑。
- 个别模块有额外环境门槛:node/Chrome(本地 canonical 执行测试,自带 skip 门)、
  git、macOS/Linux 的 `fcntl`。
- `render_*.py` 不是测试,是显式 CLI 资格化/验收维护工具,不会被 unittest 收集。

## 慢模块提示

全套约 3 分钟;其中 `test_verified_template_registry` 校验全部证据哈希,
约占 2 分钟,单独复跑时耐心等待。

## 新测试的写法

第一行环境引导用共享模块,不要再手写 `sys.path` 推导:

```python
import _env  # noqa: F401  (建好路径与 EDIT_HD_AVAILABLE)
import unittest

@unittest.skipUnless(_env.EDIT_HD_AVAILABLE, "edit.hd runtime is unavailable")
class MyTests(unittest.TestCase):
    ...
```

## 钉链护栏

`test_motion_capability_pins.py` 跨包校验能力索引钉值与磁盘一致。
任何触碰受钉脚本的重构后,用 `scripts/refresh_capability_pins.py`
(只读报告)审查,再 `--write` 重钉。
