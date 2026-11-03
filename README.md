# dsh-sw-toolkit

**用 Python / 命令行 / MCP 驱动本机 SolidWorks —— 建模、配 GB 材质、装配配合、查干涉、出 GB 标准工程图，每一步都有回读验证。**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2025%20SP5%20tested-red)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-124%20passed-brightgreen)]()

> 本项目只在 **SolidWorks 2025 SP5.0 + Windows + Python 3.14** 上做过完整实测。
> 版本兼容（目标下探到 2019）是下一版的主要目标，见路线图。

---

## 它解决什么问题

SolidWorks 自动化有三类工具，各有各的坑：

| 做法 | 批量建模 | 出工程图 | 分色 | 装配配合 |
|---|---|---|---|---|
| VBA / COM 脚本 | 慢（IDispatch 每次往返） | 各写各的 | 体级赋值经常静默失效 | 能写，很啰嗦 |
| 商业插件 | 快 | 强 | 强 | 强 |
| **本项目** | 生成 C# 早期绑定，快 | **GB 图框 + 自动标注 + 总尺寸** | **面级写入 + 回读，100%** | **同心/重合，自动选面** |

具体解决这些真问题：

1. **AI 会产出非法参数** → `spec.py` 在执行前校验，报 `cylinders[0]: cylinder.axis 必须为 x/y/z`，而不是崩在 COM 里
2. **建完不知道对不对** → 实体数、包络、逐面颜色、材质、质量、体积全部回读
3. **配色设了不生效** → 面级写入 + 回读比对，实测 126/126 面
4. **GB 牌号赋值静默失败** → 实测默认密度退回 **1000 kg/m³（水）**，质量错 7.85 倍；本项目自带 20 个 GB 牌号的材质库并自动部署
5. **工程图是英寸、没图框** → 自动选中文 `gb_<纸张>.drwdot`，带图框、标题栏、材料、重量、比例
6. **没有总尺寸** → `dims.py` 按视图可见顶点极值显式补总长/总高
7. **干涉查不出来** → 装配级 API 在本机对 500 mm³ 重叠返回 0，改用**零件级布尔求交**，精确到 500.000 mm³
8. **文档越开越多把 SW 拖垮** → 三档资源守卫 + 安全清扫

---

## 核心数字

| 项目 | 数值 |
|---|---|
| 源码 | **约 4 400 行** Python，14 个模块 |
| 测试 | **124 项**（95 离线 + 29 实机） |
| MCP 工具 | **22 个** |
| 公开导出 | **41 项** |
| GB 牌号 | **20 个**（密度 / 弹性模量 / 泊松比 / 国标出处） |
| 几何能力 | box / plate / tube(XYZ) / cylinder(XYZ) / revolve(XYZ) / fillet / chamfer |
| 实测环境 | SolidWorks 2025 SP5.0 (33.5.0) + Python 3.14.3 |

---

## 安装

```powershell
git clone https://github.com/<you>/dsh-sw-toolkit.git
cd dsh-sw-toolkit
python -m pip install -e ".[mcp,pdf]"
```

**要求**：Windows + SolidWorks（实测 2025 SP5.0）+ Python 3.10+

可选依赖：

| extras | 提供 |
|---|---|
| `[mcp]` | MCP 服务器（22 个工具） |
| `[pdf]` | PDFium 内容验证 |
| `[mechdog]` | 委托 MechDog 做深度标注与制造审核 |

---

## 快速开始

### 一条命令自检

```powershell
dsh-sw capabilities
```

输出当前 SW 版本、连接延迟、MechDog 是否可用。

### 建模 + GB 材质

```python
from dsh_sw_toolkit import PartBuilder

b = PartBuilder(r"D:\out\支架.SLDPRT", material="Q235")
b.box("底板", 0, 160, 0, 20, 0, 100, "steel")
b.tube_y("立柱", 20, 140, 60, 0, 40, 40, wall=6, color="yellow")
b.cylinder("孔", axis="y", x=80, y=20, z=50, r=8, h=20, color="gray")

r = b.build()
print(r.ok, r.bodies, r.mass_kg, r.volume_mm3)
# True 10 3.281 417920.0
```

### 出工程图（GB 图框 + 自动标注 + 总尺寸）

```python
from dsh_sw_toolkit import produce, add_dimensions, normalize_layout, export_pdf

produce(model, drawing, paper="A3")          # 自动选 gb_a3.drwdot
add_dimensions(drawing, overall=True)        # 模型尺寸 + 总长/总高
normalize_layout(drawing)                    # 长对正 / 高平齐 / 间距 ≥35 mm
export_pdf(drawing, r"D:\out\图纸.pdf")
```

出的图包含：GB 图框（A~F / 1~8）、标题栏（材料 / 重量 / 比例）、
毫米标注、总尺寸、三视图按长对正高平齐排列。

### 装配 + 配合 + 干涉

```python
from dsh_sw_toolkit import AssemblyBuilder, MateBuilder, body_interference

a = AssemblyBuilder(r"D:\out\总装.SLDASM")
a.add(r"D:\out\底座.SLDPRT", 0, 0, 0, fixed=True)   # 坐标单位 mm
a.add(r"D:\out\销.SLDPRT",  60, 0, 0)
a.build()

m = MateBuilder(r"D:\out\总装.SLDASM")
m.concentric(0, 1)        # 自动找等径圆柱面
res = m.apply()
# 销从 60 mm 被拉到 0 mm，同轴

body_interference(part, "A", "B")
# {'interfere': True, 'interference_volume_mm3': 500.0}
```

### MCP

```json
{
  "mcpServers": {
    "dsh-sw": { "command": "solidworks-dsh-sw.exe" }
  }
}
```

22 个工具：`sw_build_part` `sw_apply_colors` `sw_produce_drawing` `sw_layout_views`
`sw_export_pdf` `sw_overall_dimensions` `sw_body_interference` `sw_resource_status` …

---

## 设计原则

1. **不假成功** —— `ready_for_manufacture` 恒为 `False`，`review_required` 恒为 `True`，有测试守着
2. **破坏性操作默认 dry-run** —— `purge_*`、`sweep_documents` 只列不删
3. **不碰用户文档** —— 只关闭本次自己新建的；有未保存修改的一律跳过
4. **不编造工程数据** —— 基础图不自动加公差；材质用国标表并注明出处
5. **判据必须独立回读** —— `errStatus`、返回值 `ok` 都可能是假信号（详见踩坑记录）

---

## 踩过的坑（也是本项目最大的资产）

| 现象 | 真相 |
|---|---|
| `AddMate5` 的 `errStatus=1` | 不是失败，`swAddMateError_NoError = 1` |
| `Operations2` 返回 `(None, 1)` | 文档体不是 API 临时体，要先 `Copy2()` |
| `FixComponent()` 返回 None | 其实成功了，判据要看 `IsFixed` |
| `material="Q235"` 接受 | 但没赋给 SW，质量按水（1000 kg/m³）算 |
| `IFace2.GetSurface()` 报「找不到成员」 | pywin32 后期绑定取不到，必须走 C# 早期绑定 |
| SW 由 COM 后台拉起时连不上 | 不在 ROT，`GetActiveObject` 失败，要 fallback 到 `CreateInstance` |
| 装配零件被放到 60 米外 | `AddComponent5` 内部要**米**，项目约定是**毫米** |

更多见 `docs/pitfalls.md`。

---

## 已知限制

* 只在 SolidWorks 2025 SP5.0 实测，**2019~2024 未验证**
* 生成的 `.SLDPRT` 是当前版本格式，低版本 SW 打不开（未做版本降级保存）
* 自动标注插的是模型驱动尺寸，会跨视图去重，上限约 18 个；总尺寸由 `dims.py` 单独补
* 右视/俯视的总尺寸选点可能落在内轮廓上（待修）
* 公差与粗糙度**不自动生成**（设计决策：不编造工程要求）
* 装配级干涉 API 在本机不可用，干涉判定走零件级布尔
* 建模约 **2.65 s/形体**，100 形体约 4.5 分钟

详见 `docs/limitations.md`。

---

## 目录结构

```
src/dsh_sw_toolkit/
├── session.py       统一会话：探针 + 分类重试 + 单 STA 串行化
├── modeling.py      DSL → C# 早期绑定建模 + 面级配色
├── colors.py        规则式面级分色 + 回读
├── cleanup.py       STEP 导入体检与垃圾体清理
├── gb_materials.py  20 个 GB 牌号 + 材质库生成
├── assembly.py      装配插入 + 固定
├── mates.py         配合：同心 / 重合（自动选面）
├── interference.py  实体干涉精确体积
├── dims.py          总长 / 总高显式标注
├── drawing.py       出图 + 模板选型 + 自动标注 + 排版 + PDF
├── resources.py     三档资源守卫
├── spec.py          JSON 描述校验
├── server.py        MCP 服务器（22 工具）
└── cli.py           命令行
```

---

## 开发

```powershell
# 只跑离线测试（不需要 SolidWorks，CI 用）
python -m pytest tests -q -m "not sw"

# 全量（需要 SolidWorks 在运行）
$env:DSH_SW_LIVE = "1"
python -m pytest tests -q
```

**SolidWorks 必须先手动启动并出现主窗口**，否则实机测试会失败。

---

## 路线图

| 版本 | 主题 | 状态 |
|---|---|---|
| v0.5 | 连接 fallback、GB 材质、诚实性测试 | ✅ |
| v0.6 | 三轴旋转、自动标注、装配 | ✅ |
| v0.7 | GB 图框、毫米单位 | ✅ |
| v0.8 | 总尺寸、配合、精确干涉 | ✅ |
| **v0.9** | **SW 版本兼容（2019+）** | 计划中 |
| v1.0 | 公差/粗糙度、BOM、装配爆炸 | 规划 |

---

## 许可

MIT。见 [LICENSE](LICENSE)。

本项目可选依赖 [MechDog](https://github.com/wudahua/Solidworks_AssetMate_MechDog)（同样 MIT），
只在其 Python API 层调用，不复制其代码。
