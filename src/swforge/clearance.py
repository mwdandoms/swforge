# -*- coding: utf-8 -*-
"""装配净距与干涉（1.9.3 新增）。

为什么不用 `check_interference()`
================================
`assembly.check_interference()` 走的是
`AssemblyDoc.InterferenceDetectionManager`。本机 SW2025 SP5 实测（见
`interference.py` 首注）它对**确定重叠 500 mm³** 的两个立方体返回 0 个干涉；
上一轮绞龙三档净距更是出现 0/2/1 条明细、外层 `ok` 全为 True 的读数，
**不能当判据**。

SW 自带的「间隙验证」管理器也没法用：`AssemblyDocument.ClearanceVerificationManager`
在本机能取到对象，`SetMinimumAcceptableClearance` 返回 True、`SetComponentsOrFacesToCheck`
返回 True（错误码 0），但 `CalculateClearances()` 无论怎么调（改门限、先选择组件、
不选择直接算）都返回**空数组**。实测记录见文档 47。

本模块走的是两条能出数的路
==========================
1. **净距**：`IModelDoc2.ClosestDistance(组件A, 组件B, out 点1, out 点2)`
   直接返回装配坐标系下的最近距离（米）与两个最近点。
   实测：⌀56 轴配 ⌀60 内孔 → 1.99965 mm；贴合 → 3.5e-15 mm；过盈 → 0。
2. **干涉体积**：两件最近距离为 0 时，取各自实体 `Copy2` → `ApplyTransform(Transform2)`
   搬到装配坐标系 → `Operations2(SWBODYINTERSECT, 另一体)`，累加交集体积。
   实测：⌀64 轴配 ⌀60 内孔 → 1371.78 mm³（不是「有几处干涉」这种计数）。

坐标系的坑
==========
`IComponent2.GetBodies2()` 返回的实体在**组件坐标系**里（实测：两个同名 20 mm
立方体，插入位置差 0.1 mm 后包围盒仍都是 0~20）。要进装配坐标系必须
`body.ApplyTransform(component.Transform2)`。直接拿两件的体做布尔求交，
在零件之间有相对位移时会算错：绞龙过盈样件上两种做法差 **3.26 mm³**
（1368.53 vs 1371.78，后者与装配坐标系一致）。

判定口径
========
- `clearance_mm`：量出来的最小距离，不是估算；
- `interference_volume_mm3`：精确交集体积，0 表示不重叠；
- `verdict`：`clear`（有间隙）/ `touch`（贴死，0 间隙 0 体积）/ `interference`（真过盈）；
- `meets_minimum`：`interference_volume≈0 且 clearance_mm >= minimum_mm`。
  **贴合不算合格**：0 间隙在工程上等于没有装配余量。
"""
from __future__ import annotations

import os

from .native_bridge import run_native, target_document

__all__ = ["check_clearance"]

TOUCH_MM = 1e-6


def _non_negative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def check_clearance(assembly_path, *, minimum_mm: float = 1.0, components=None,
                    keep_open: bool = False) -> dict:
    """量装配体的最小净距，并对 0 间隙的配对算精确干涉体积。

    `minimum_mm` 是**要求的净距下限**（判定用，不是报告门限）：
    每一对都会量，`meets_minimum` 按 `clearance_mm >= minimum_mm` 算。
    `components` 可给 0~2 个组件名（`Name2`，或零件文件名）：
    给两个就只量这一对，给一个就量它与其余组件的最近距离，
    不给就量全部组件两两之间。
    `keep_open=False`（默认）时，本次调用自己打开的装配结束就关掉。

    返回：`min_clearance_mm`、`pairs[]`（每对的 `clearance_mm`、最近点、
    `interference_volume_mm3`、`verdict`、`meets_minimum`）、
    `interfering_pairs`、`touching_pairs`、`meets_all`。
    """
    minimum_mm = _non_negative(minimum_mm, "minimum_mm")
    assembly_path = os.path.abspath(os.fspath(assembly_path))
    if not assembly_path.lower().endswith(".sldasm"):
        raise ValueError("check_clearance only accepts .sldasm assemblies")
    if not os.path.isfile(assembly_path):
        raise ValueError("Assembly does not exist: " + assembly_path)
    if components is None:
        picked = []
    else:
        if isinstance(components, str):
            raise ValueError("components must be a list of component names")
        picked = list(components)
        if len(picked) > 2:
            raise ValueError("At most two components can be named")
        for name in picked:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Component names must be non-empty strings")

    from .session import get_session, _value

    md = None
    was_open = False
    try:
        sw = get_session().sw()
        was_open = sw.GetOpenDocumentByName(assembly_path) is not None
    except Exception:                                        # noqa: BLE001
        pass

    try:
        _, md, target = target_document(assembly_path, 2)
        result = run_native(dict(target, mode="clearance", minimum_mm=minimum_mm,
                                 components=picked))
    except Exception as exc:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "path": assembly_path}
    finally:
        if md is not None and not was_open and not keep_open:
            try:
                get_session().sw().CloseDoc(str(_value(md, "GetTitle")))
            except Exception:                                # noqa: BLE001
                pass

    result["path"] = assembly_path
    result["minimum_mm"] = minimum_mm
    if result.get("ok"):
        rows = result.get("pairs") or []
        result["below_minimum_count"] = sum(1 for r in rows if not r.get("meets_minimum"))
        result["meets_all"] = bool(rows) and not result["below_minimum_count"]
        if result.get("min_clearance_mm") is not None:
            result["min_clearance_mm"] = round(float(result["min_clearance_mm"]), 4)
    else:
        result["meets_all"] = False
        if result.get("inconclusive_pairs"):
            result["error"] = "Interference calculation inconclusive for one or more component pairs"
    return result
