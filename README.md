**中文** | [English](https://github.com/mwdandoms/swforge/blob/main/README.en.md)

# swforge

**用 Python / 命令行 / MCP 驱动本机 SolidWorks —— 建模、配 GB 材质、装配配合、查干涉、出 GB 工程图，每一步都读回核对。**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2025%20SP5%20tested-red)]()
[![PyPI](https://img.shields.io/pypi/v/swforge)](https://pypi.org/project/swforge/)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/mwdandoms/swforge/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-mwdandoms.github.io-blue)](https://mwdandoms.github.io/swforge/)

[![swforge 演示：代码驱动 SolidWorks](https://raw.githubusercontent.com/mwdandoms/swforge/main/demo/poster.png)](https://github.com/mwdandoms/swforge/releases/download/v1.4.1/swforge-demo-2m21s-1080p60.mp4)

> ▶ **点图播放 2 分 21 秒完整演示**（6.7 MB）——从 SolidWorks 关闭状态开始，
> 建模 → 国标材质 → GB 工程图 → 尺寸 → 粗糙度 → 公差 → PDF → 装配 → 配合 → 干涉，
> **全程无人操作**。左边是建出来的零件，右边是同一套代码出的 GB 图。

---

## 为什么用它

| 用别的工具 | 用 swforge |
|---|---|
| 调用没报错就算成功，出错要人工去查 | 每步读回真实结果比对，对不上就停下报错 |
| 材质默认密度按水算，质量错 7.85 倍 | 内置国标材质库，赋完反算密度核对 |
| 出的图图框标题栏不对，车间不认 | GB 图框、标题栏、粗糙度、尺寸公差 |
| 干涉只告诉你「有 / 没有」 | 给精确体积，例如 4000.0 mm³ |

---

## 能做什么

**建模** — 矩形、板、方管（三轴）、圆柱、旋转体、圆角、倒角

**加工特征** — 指定实体的矩形切除、三轴正负向通孔 / 盲孔 / 平底沉孔、孔网格

**装配** — 组件定位、重合 / 同心 / 距离 / 角度 / 锁定配合、显式持久面引用配合、干涉检查

**工程图** — GB 三视图、剖视、局部放大、自动标尺寸、直径标注、表面粗糙度、尺寸公差、导出 PDF / DWG / DXF

**出图检查** — 视图越纸幅、视图重叠、悬空标注、必填属性、模型与图纸一致性

**其他** — BOM 明细表、批量出图、文档数上限保护

---

## 安装

```bash
pip install swforge              # 只装库
pip install "swforge[mcp,pdf]"   # 带 MCP 服务器和 PDF 预览
```

前提：Windows + 完整安装的 SolidWorks + Python 3.10 以上。**先手动启动 SolidWorks，再调用本库。**

实测环境为 SolidWorks 2025 SP5.0 / Windows 11 / Python 3.14。其他 SW 版本未验证。

---

## 三十秒例子

```python
from swforge import PartBuilder

b = PartBuilder(r"F:\out\plate.SLDPRT", material="Q235")
b.box("plate", 0, 100, 0, 20, 0, 60)
b.hole("mount", "plate", axis="y", x=30, y=20, z=30,
       diameter=10, through_all=True, direction=-1,
       counterbore_diameter=16, counterbore_depth=4)

r = b.build(keep_open=False)
assert r.ok, r.error
print(r.mass_kg, r.volume_mm3)   # 从 SolidWorks 读回来的真实值
```

---

## 先验一下环境

```bash
swforge selftest
```

在你自己的机器上实机跑一遍，逐项打印通过与否。

---

## 做不到的

- **形位公差**未实现
- **完整孔系标注**（孔位置、深度、孔表）未实现，目前只有圆边直径标注
- **焊件 / 切割清单**、**渐开线齿轮**未实现
- 图纸检查里的文字重叠是**近似提示**
- 只在 SolidWorks 2025 SP5.0 上实测过

细节见 [已知限制](https://github.com/mwdandoms/swforge/blob/main/docs/limitations.md) 与 [问题日志](https://github.com/mwdandoms/swforge/blob/main/docs/issue-log.md)（含未修复的问题）。

---

## 文档

[快速开始](https://github.com/mwdandoms/swforge/blob/main/docs/quickstart.md) ·
[功能矩阵](https://github.com/mwdandoms/swforge/blob/main/docs/features.md) ·
[文档站](https://mwdandoms.github.io/swforge/)

---

## 许可

MIT。
