# 2.0 Community 验证范围

2026-11-18 在本机 Windows、Python 3.14.3、SolidWorks 2019 SP5（27.5.0）与 2025 SP5（33.5.0）进行验证。实际导入版本为 2.0.0，导入路径和原始报告在本地验收包内记录；本地候选版尚未发布。

| 专项 | 2019 SP5 | 2025 SP5 |
|---|---|---|
| 七类原生特征，加反向、Z 轴及部分角度阵列 | 10 个场景通过 | 10 个场景通过 |
| 左右旋弹簧、左右旋绞龙、含螺旋混合体、普通改尺寸 | 6 个场景通过 | 6 个场景通过 |
| A3 基础三视图、保存重开、PDF 导出及逐页解析渲染 | 通过 | 通过 |
| 已知 10 mm 净距、相切、2,000 mm³ 重叠体积 | 3 个场景通过 | 3 个场景通过 |
| 正方形轮廓独立改尺寸并保存重开 | 20→21 mm，体积 8,400 mm³ | 20→21 mm，体积 8,400 mm³ |
| 实际 gateway 调用 JSON 建模、弹簧与绞龙操作 | 3 个入口通过 | 3 个入口通过 |
| 对应版本 Interop 的原生引擎编译 | 17 个通过 | 17 个通过 |

螺旋件先核对旋向、体积与精确外廓，再转换为实体；保存重开后检查实体数、特征错误、体积，以及不存在螺旋、扫掠、加厚、截面草图和驱动参数。普通轮廓检查原生尺寸改值、重建、体积及保存重开。

离线回归 **397 项通过**，含真实 MCP stdio 子进程协议、目录注册和商业边界检查。33 项历史 `sw` 标记测试未全量执行；上表是本轮独立实机专项，不据此宣称所有 72 项操作均已验收。其他 Python 版本和其他 SW 年份/补丁未在本轮实测。

各专项均从 0 份打开文档回到 0 份，仅关闭本轮文件。原始失败尝试保留在本地证据目录；2019 早期综合报告中出图失败，最终出图专项已通过，不把早期整份报告标成通过。源码及 wheel/sdist 商业边界另外按文件白名单和 SHA-256 核对。

## 复现

先打开对应 SW，并为每项指定全新输出目录：

```powershell
$env:SWFORGE_SW_YEAR='2019'  # 或 2025
python tools/acceptance_v20.py --year 2019 --out '<新目录1>'
python tools/validate_v191_features.py '<新目录2>'
python tools/acceptance_v20_clearance.py --year 2019 --out '<新目录3>'
python tools/acceptance_v20_gateway.py --year 2019 --out '<新目录4>'
python tools/compile_community_engines.py --year 2019 --out '<新目录5>'
python -m pytest -q -m 'not sw'
python tools/verify_community_release.py
```

机器可读汇总见 [validation-community.json](validation-community.json)。基础图纸仍须设计审核；上述检查不构成完整 GB、强度或制造认证。
