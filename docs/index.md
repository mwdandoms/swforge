---
layout: default
---

# swforge

**用 Python / 命令行 / MCP 驱动本机 SolidWorks。**
建模、配 GB 材质、装配配合、查干涉、出 GB 标准工程图 —— 每一步都回读验证。

---

## 一句话

> **不确定结果对不对的自动化，不算自动化。**

同类工具普遍是「调用没报错就算成功」。swforge 是**每一步都把结果读回来核对**：
建完读实体数和体积，赋完材质读密度，加完配合读位置变没变，出完图读尺寸值对不对。

---

## 30 秒判断适不适合你

| 你的情况 | 适合吗 |
|---|---|
| 有一批 SolidWorks 零件要出图 | ✅ 批量出图，5 个零件约 16 秒 |
| 想让 Claude / Cursor / DSH 直接操作 SolidWorks | ✅ 标准 MCP，22 个工具 |
| 需要国标材质和国标图框 | ✅ 20 个 GB 牌号，GB 图框 |
| 需要精确的干涉体积 | ✅ 实测 4000.000 mm³，偏差 0.00% |
| 需要**公差、粗糙度、形位公差**自动标注 | ❌ 没有，需人工补 |
| 需要图纸**直接投产** | ❌ 不行 |
| 用 macOS / Linux | ❌ 只能 Windows + SolidWorks |
| 不是 SolidWorks 2025 SP5 | ⚠️ 未测试，先跑 `swforge selftest` |

---

## 装

```powershell
pip install "swforge[mcp,pdf]"
```

前提：Windows + SolidWorks 2025 + Python 3.10+，**且 SolidWorks 要先手动启动**。

---

## 先自检

```powershell
swforge selftest
```

九项检查全在真实 SolidWorks 上跑：

```
[PASS] 连接与版本                  0.00s  SolidWorks 33.5.0，往返 1 ms
[PASS] 文档切换后真正激活            7.52s  3 次切换全部正确（每次都回读标题）
[PASS] 资源守卫与清扫               11.37s  峰值 3/8，清扫后 0
[PASS] 几何回读准确                 3.61s  体积 100000.0 mm³，偏差 0.000%
[PASS] 材质真的赋上（密度≠1000）      3.59s  密度反算 7850 kg/m³
[PASS] 干涉体积精确                 11.61s  体积 4000.0 mm³，偏差 0.00%
[PASS] 配合真正加成功               11.34s  X=[0.0,60.0] → [0.0,0.0]
[PASS] 出图与尺寸值正确              6.05s  6 个尺寸 [20.0, 100.0, 160.0]
[PASS] API 反射探测                 0.43s  探测 28 项，可用 28 项

结果：9 通过 / 0 失败   耗时 56.2s
```

**失败时它会指出是哪一环、对应同类项目的哪个已知问题**，不是笼统的「失败」。

---

## 最小示例

```python
from swforge import PartBuilder

b = PartBuilder("底板.SLDPRT", material="Q235")
b.box("底板", 0, 160, 0, 20, 0, 100)
r = b.build()

print(r.ok, r.bodies, r.mass_kg, r.volume_mm3)
# True 1 2.512 320000.0
```

读回来的 `bodies` / `mass_kg` / `volume_mm3` 才是重点 ——
**不是「调用没抛异常」，是真的读到了几何。**

---

## 文档

- [v1.4 交接文档](handover-v1.4.md) —— 给接手的开发者（粗糙度/公差）
- [功能清单](features.md) —— v1.1 全部能力一览（含实测数据）
- [快速开始](quickstart.md) —— 装、连、建第一个零件
- [自检说明](selftest.md) —— 九项检查各验证什么
- [BOM 明细表](bom.md) —— 从装配读清单，同零件合并计数 —— 九项检查各验证什么
- [已知限制](limitations.md) —— **先说清楚做不到什么**
- [踩过的坑](pitfalls.md) —— 实现层面的技术细节
- [问题日志](issue-log.md) —— 开发中发现并修复的真实问题
- [为什么不用 GetActiveObject](why-getactiveobject-fails.md) —— 花了很久才搞清的行为
- [路线图](roadmap.md) —— 下一阶段方向和退出条件
- [竞品分析](competitive-analysis.md) / [竞品 issue 分析](competitor-issues-analysis.md)

---

## 数据可信度

所有公开数字都是本机实测，注明环境：

| 数字 | 来源 |
|---|---|
| 批量出图 5 件 15.7 秒 | SolidWorks 2025 SP5.0 实测 |
| 干涉 4000.000 mm³ | 两个 20mm 立方重叠 10mm，理论核对 |
| 密度 7850 kg/m³ | mass/volume 反算，与 GB/T 700 一致 |
| 尺寸 22 → 9 个 | 同一支架改版前后对比 |

**没做过的验证，不写成做过。**
