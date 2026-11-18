**中文** | [English](README.en.md)

# swforge

**让 SolidWorks 少一点重复操作，多一点可复用成果。**

从参数化零件、材料配色，到装配、工程图、BOM 和 PDF，swforge 把常用机械设计步骤串起来，方便重复执行，也方便核对结果。

[![PyPI](https://img.shields.io/pypi/v/swforge)](https://pypi.org/project/swforge/) [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 2.0 社区版的侧重点

本次重点补齐原生建模、可编辑尺寸与基础螺旋生成，并适配 SolidWorks 2019 SP5 / 2025 SP5。工程图、GB、审图和批量交付保留 1.7 已公开功能范围，加入必要的版本兼容与可靠性修复。

| 你的工作 | swforge 可以提供 |
|---|---|
| 同类零件反复画 | JSON 参数建模；板件、空心方管、圆柱、回转体、台阶轴、切除、孔、圆角和倒角 |
| 重复结构与特征 | 线性/圆周阵列、镜像、等厚抽壳、加强筋、圆截面放样和装饰螺纹 |
| 常用尺寸需要调整 | 常用轮廓的原生驱动尺寸、明确参数关联、重建回读与另存变型 |
| 弹簧与绞龙需要快速生成 | 圆柱压缩弹簧、等螺距绞龙叶片；社区版交付无建模历史实体，改参数后重新生成 |
| 材料、颜色和装配反复整理 | GB 牌号材质与配色回读、组件与明确面配合、干涉及基础净距检查、BOM |
| 工程图和文件交付 | 三视图、剖视、局部放大、基础标注与 GB 模板、批量出图、多页图册和格式导出，沿用 1.7 范围 |
| 用 AI 助手协助设计 | Python API、CLI 和 MCP；先发现操作，再查看参数并调用 |

**侧重本机执行、原生结果和回读核对。** 常用零件保留可修改的原生尺寸；螺旋件采用实体交付。参数关联为显式配方关系，不等同于跨文件原生方程。文件保护、失败提示和基础校验继续包含在社区版。

## 安装与开始

需要 Windows、Python 3.10+，以及你已有的 SolidWorks 安装和使用授权。

```bash
pip install swforge
pip install "swforge[mcp,pdf]"
swforge --help
```

双版本并装时，在启动 Python/CLI/MCP 前设置目标年份：

```powershell
$env:SWFORGE_SW_YEAR = '2019'  # 或 '2025'
swforge ping
```

先打开对应版本并等待就绪；同一进程内保持同一目标版本。2019 原生文件应在 2019 中生成。

```python
from swforge import PartBuilder

result = (PartBuilder(r"F:\out\plate.SLDPRT", material="Q235")
          .box("plate", 0, 120, 0, 80, 0, 20)
          .build(keep_open=False))
print(result.ok)
```

使用新输出路径并保留原模型。默认文档上限为 8 份，建议保持 1–5 份。

## 社区版范围

**GitHub 与 PyPI Community 版继续采用 MIT，允许商业使用。** 2.0 为社区版最后一次计划内功能更新。后续仍将持续进行版本兼容适配，分阶段推进 SolidWorks 2018–2026 支持，并维护缺陷与安全问题；各版本以公布的实测范围为准。

弹簧与绞龙输出不含原生螺旋/扫掠历史或命名驱动尺寸，仍可测量、装配及进行实体编辑；含螺旋件的混合零件也按整体实体交付。社区包不包含绞龙下料计算、机械连接复核及新版高级工程图/审图实现。

2019 SP5 / 2025 SP5 的实测覆盖范围见[验证说明](docs/validation-community.md)；不能据此推断所有操作均已逐项验证。基础 GB 检查不构成完整国标、强度或制造认证，最终图纸仍需工程审核。

## 后续订阅与企业定制

后续商业订阅将侧重增强工程图、GB 规则更新、审图与批量任务管理，并逐步提供可编辑螺旋建模与下料复核；企业定制可按需提供图框规范、专用件库、参数化产品生成及 PDM/ERP 对接。具体范围与交付另行说明，不影响已开源版本的 MIT 使用权。

## 致谢与反馈

保留原项目及依赖许可。感谢 [AssetMate MechDog](https://github.com/wudahua/Solidworks_AssetMate_MechDog) 等开源项目。问题反馈请附 SW 版本、最小示例和回读结果，避免附带企业敏感模型。
