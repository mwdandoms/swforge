---
name: swforge
description: >-
  SolidWorks 建模、装配、出工程图的默认工具（本项目自研 swforge，版本以 import swforge; swforge.__version__ 为准）。
  每一步把 SolidWorks 的原生结果读回来核对，对不上就停下报错。
  凡是建模 / 生成 .sldprt / 参数化改型 / 装配配合 / 查干涉 / 出 GB 图纸 /
  算质量 / 批量出图，一律先用它，不要用 sw_bridge.py。
whenToUse: >-
  用户要求用 SolidWorks 建模、画零件、生成三维模型、参数化改尺寸、装配、
  出工程图、算重量、验证干涉、批量出图、改材质、查标准型材素材库。
source: swforge
provider: filesystem
---

**停工交接：v1.6未完成整体验收。剖视重叠已修复，但真实中心切孔/剖面线未确认（GetFaceHatchCount=0）。当前安装仍1.5.1；未生成最终wheel/sdist、未安装1.6、未发布。以35号交接日志为准。**


# swforge —— SolidWorks 驱动库（默认首选）

v1.6 目前是未发布的本地候选：移植时安装本地 v1.6 wheel，并核对 `swforge.__version__` / `swforge.__file__`。直接 `pip install swforge` 获取公开版本，不能据此宣称已有本地1.6功能。新版本发布须用户明确确认。

> **硬规则**：所有 SolidWorks 建模操作默认走 swforge。
> `<工程模式根目录>\tools\sw_bridge.py` 只用于 swforge 不覆盖的能力：
> DWG/DXF 导出细节、CADX 校验、conn-gate 连通性探测、模板路径探测。

## 0. 安装与接入

```bash
pip install swforge                # 只装库
pip install "swforge[mcp,pdf]"     # 带 MCP 服务器和 PDF 预览
```

给 AI 智能体用（二选一）：

```bash
swforge install-skill              # 把本 skill 装进 ~/.dsh/skills/
```

或在 MCP 客户端里配：

```json
{
  "mcpServers": {
    "swforge": { "command": "python", "args": ["-m", "swforge.server"] }
  }
}
```

## 0b. 开工前三个动作

```python
import swforge                     # pip install swforge  即可
```

1. **连不上就先跑 `swforge start`**（或 `from swforge.startup import ensure_running`）。
   它先用 tasklist 看进程，没起来就从注册表读真实 exe 路径自己启动，
   再等 COM 就绪 —— 专门解决 `CO_E_SERVER_EXEC_FAILURE`。
2. **连上后立刻 `sw.Visible = True`** —— CreateInstance 起的隐藏实例调
   `InsertSketch` 会抛 `RPC_E_SERVERFAULT (0x80010105)`，什么都建不出来。
3. **先记录文档状态**（测试上限 8 个，平时 1–5 个）。只清理本轮明确创建的文档，保护用户原有和未保存工作。

```python
from swforge.session import get_session
sw = get_session().sw()
sw.Visible = True
from swforge import document_inventory
baseline = document_inventory(sw)
# 保留 baseline 中的全部用户文档；只按本轮拥有的输出路径关闭新文档。
```

## v1.6 焊件与齿轮

优先使用 `create_weldment_frame` / `create_spur_gear`，或 MCP 的
`sw_create_weldment_frame` / `sw_create_spur_gear`；不要用四块板冒充原生结构构件，也不要用普通星形多边形冒充渐开线。
输出路径必须全新；默认关闭本轮文档。参数变型用 `create_mechanical_variant` 重生成副本，保护源模型。详见包内 `docs/workflows-v1.6.md`。
随 wheel 分发的完整调用说明见 [mechanical-v16.md](references/mechanical-v16.md)。

方管框架限十二杆理想SHS、直角平切。齿轮限零变位外直齿，根部径向简化，未做加工/强度/啮合认证。工程图自动补中心孔直径；有轮毂时补轮毂直径和剖视，不自动编造公差/粗糙度。

## 1. 单位

| 场景 | 单位 |
|---|---|
| 建模坐标、尺寸、公差偏差 | **mm** |
| 图纸标注位置 | **m** |
| COM 内部返回值 | **m**（乘 1000 换算） |

## 2. 建之前先分析结构 —— 不要上来就堆方块

先按 `references/structure.md` 分类，再决定怎么建：

```
体积 / 包围盒体积 ≈ 1.0   → 实心板，直接 box
体积 / 包围盒体积 < 0.5   → 空心方管，外壳 + 内腔切除
多块薄板围成封闭截面       → 是一根箱型梁，合并成一根建
```

**反例（本项目真踩过）**：把 150×250 的横柱拆成 4 块板散布建模。
**正解**：识别为 150×250×6.3 矩形方管，一根建完。

颜色/外观也要跟着构件保留，不能建成一片同色。

## 3. 建模

```python
from swforge import PartBuilder

b = PartBuilder(r"F:\out\part.SLDPRT", material="Q235")
b.box("底板", 0, 100, 0, 20, 0, 60)          # x0,x1, y0,y1, z0,z1
b.hole("孔", "底板", axis="y", x=30, y=20, z=30,
       diameter=10, through_all=True, direction=-1,
       counterbore_diameter=16, counterbore_depth=4)

r = b.build(paint=False, keep_open=False)
assert r.ok, r.error
print(r.volume_mm3, r.mass_kg)
```

详见 `references/modeling.md`。

> **切除方向**：孔口开在上表面 y=20、料在下方时，必须 `direction=-1`。
> 方向写反会报「孔口/方向未与目标相交」——这是库的**正确行为**，不是 bug。

## 4. 每一步读回核对

| 环节 | 核对什么 |
|---|---|
| 建模 | 实体数、体积、特征错误码 |
| 赋材质 | 质量 ÷ 体积 反算密度，确认不是 1000（水） |
| 切除 | 体积必须减少；圆孔另核对圆柱面位置和直径 |
| 标注 | 尺寸数量、公差上下偏差回读、粗糙度附着实体数 |
| 配合 | 间隙、平行误差、干涉体积 |

**对不上就停，不要往下走。**

## 5. 材质

国标牌号直接用，不许近似成欧美标。详见 `references/materials.md`。

## 6. 装配 / 出图 / 检查

- 装配与干涉 → `references/assembly.md`
- GB 工程图与标注 → `references/drawing.md`
- 出图自检与交付 → `references/audit.md`

## 7. 踩过的坑（建模前必读）

`references/pitfalls.md` —— 7 条本机实测过的 COM 陷阱，包括
`Visible`、文档上限、`RPC_E_DISCONNECTED`、`SelectByID2` 失效、
`GetBox` 不可用、零参方法退化成属性。

## 标准型材：一律用 create_standard_member

方管、矩型管、圆管、角钢、H型钢、槽钢、工字钢这类**标准型材**，
不要用 `PartBuilder` 从零画，用这个入口（它默认先查素材库）：

```python
from swforge import create_standard_member
r = create_standard_member(out, shape="shs", a=150, b=150, t=6.3,
                           length=3000, material="Q235")
print(r["profile_resolution"]["source"])
```

返回值里的 `profile_resolution.source`：

| 值 | 含义 | 该怎么做 |
|---|---|---|
| `library` | 复用了素材库轮廓（真型材截面） | 正常，继续 |
| `generated_fallback` | 库里有同型号但轮廓不能当结构构件 | **必须告知用户** |
| `generated` | 库里没有该型号 | 看 `advice` 的最接近候选，让用户确认 |

本机素材库：**1306 个 GB 轮廓**，`F:\sw基础材料库`，25 个分类。

```bash
swforge member out.sldprt --shape shs --a 150 --b 150 --t 6.3 --length 3000
swforge lib-find --shape shs --a 150 --b 150 --t 6.3     # 只查不建
swforge lib-scan                                          # 看有哪些分类
```

框架整体用 `create_weldment_frame`（同样默认 `use_library=True`）。

只有**非标准型材**（自制异形件、焊接组合件、钣金件）才用 `PartBuilder`。
详见 `references/library.md`。
