# -*- coding: utf-8 -*-
"""BOM 明细表 —— 从装配体读组件清单，按零件合并，带材料。

为什么单独做一个模块
--------------------
机械图纸的明细表不是"把零件名列一下"那么简单：

- 同一个零件装多次要合并成一行、数量累加（不是列 5 行同一个垫片）
- 材料列必须是真的材料名，不能是空的或者 "Default"
- 序号要和图上的气泡号对得上

数据从哪来
----------
不打每个零件。`IComponent2.GetMaterialUserName()` 能直接从装配里的组件读材料，
而组件对应的零件在装配打开时就已加载，不需要额外开文档。
这点很重要：SolidWorks 默认只有 8 个文档名额，逐个打开零件很快就用光了。

用到的 API（都经过反射确认存在）
--------------------------------
IComponent2.GetMaterialUserName()   读材料名
IComponent2.GetPathName()           读零件路径（用来判重）
IComponent2.get_Name2()             读组件名
IView.InsertBomTable6(...)          在工程图插原生 BOM 表
"""

from __future__ import annotations

import csv
import io
import os
import re

__all__ = [
    "collect_bom",
    "material_of",
    "insert_bom_table",
    "bom_to_markdown",
    "bom_to_csv",
    "group_components",
]

# InsertBomTable6 的 AnchorType 取值
# swBOMConfigurationAnchor_TopLeft = 0
# swBOMConfigurationAnchor_TopRight = 1
# swBOMConfigurationAnchor_BottomLeft = 2
# swBOMConfigurationAnchor_BottomRight = 3
_ANCHOR_TOP_LEFT = 0
_ANCHOR_BOTTOM_LEFT = 2

# BomType: swBOMType_TopLevel = 1（只列顶层，不展开子装配）
_BOM_TOP_LEVEL = 1


def _value(obj, name, default=None):
    """取属性或方法。

    这里有一个**很容易踩的坑**：COM 对象本身也是 callable 的。
    如果 getattr 拿到的已经是一个文档对象（比如 GetModelDoc2 在后期绑定下
    直接返回 CDispatch），再对它调 v() 会尝试把整个对象当函数执行，
    结果是 None —— 而且不会报错。

    所以判断顺序是：
        1. 带 _oleobj_ 的（已经是个 COM 对象）     -> 原样返回
        2. 其他 callable（真的方法）               -> 调用
        3. 都不是                                  -> 原样返回
    """
    try:
        v = getattr(obj, name)
    except Exception:                                  # noqa: BLE001
        return default
    if hasattr(v, "_oleobj_"):
        return v
    if callable(v):
        try:
            return v()
        except Exception:                              # noqa: BLE001
            return default
    return v



def material_of(model_doc) -> str:
    """从零件/装配文档读材料名。

    实测结论（SolidWorks 2025 SP5.0）：
        IComponent2.GetMaterialUserName()      -> 空字符串（读不到）
        IComponent2.GetMaterialIdName()        -> 空字符串（读不到）
        ModelDoc2.MaterialIdName               -> "swforge_gb_materials|Q235|9015"
        ModelDoc2.GetMaterialPropertyName2()   -> "Q235"   ← 这个才对

    注意 GetMaterialPropertyName2 的第二个参数是**字符串出参**，
    必须传 VARIANT(VT_BSTR | VT_BYREF)，直接传普通字符串会报「类型不匹配」。
    """
    if model_doc is None:
        return ""

    # 首选：GetMaterialPropertyName2 + VARIANT 出参
    try:
        import pythoncom
        import win32com.client
        db = win32com.client.VARIANT(pythoncom.VT_BSTR | pythoncom.VT_BYREF, "")
        name = model_doc.GetMaterialPropertyName2("", db)
        if name:
            text = str(name).strip()
            if text.lower() not in ("", "default", "unspecified"):
                return text
    except Exception:                                  # noqa: BLE001
        pass

    # 退回：MaterialIdName 是 "数据库|牌号|内部ID" 的复合字符串
    try:
        mid = getattr(model_doc, "MaterialIdName", "")
        mid = mid() if callable(mid) else mid
        if mid:
            parts = str(mid).split("|")
            if len(parts) >= 2 and parts[1].strip():
                return parts[1].strip()
    except Exception:                                  # noqa: BLE001
        pass

    return ""


def group_components(components, include_suppressed: bool = False) -> list:
    """把组件列表按零件路径合并成明细行。

    纯函数，不碰 SolidWorks，可以离线测。

    参数 components: [{'name','path','material','suppressed'}, ...]
    返回 [{seq, name, qty, material, path}, ...]
    """
    by_path: dict[str, dict] = {}
    order: list[str] = []

    for c in components or []:
        path = str(c.get("path") or "")
        if not path:
            continue
        # 压缩的组件默认不算进 BOM —— 图上看不到，列出来会误导。
        # 但调用方可以要求包含（比如做「全零件清单」而不是「图上清单」）。
        if c.get("suppressed") and not include_suppressed:
            continue
        # SolidWorks 允许把某个组件标成「从明细表排除」，
        # 这是用户的明确意图，必须尊重，否则 BOM 会多出他不想看到的件。
        if c.get("exclude_from_bom"):
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key not in by_path:
            # 用**零件名**（文件名去掉扩展名），不是组件实例名。
            # 组件名带实例序号（垫片-1 / 垫片-2 / 垫片-3），
            # 合并成一行后写成"垫片-3 ×3"是错的——车间要的是"垫片 ×3"。
            stem = os.path.splitext(os.path.basename(path))[0]
            by_path[key] = {
                "name": stem or str(c.get("name") or path),
                "material": str(c.get("material") or ""),
                "path": path,
                "qty": 0,
            }
            order.append(key)
        by_path[key]["qty"] += 1
        # 材料取第一个非空的（同一个零件不会有两份材料）
        if not by_path[key]["material"] and c.get("material"):
            by_path[key]["material"] = str(c["material"])

    rows = []
    for i, key in enumerate(order, start=1):
        r = by_path[key]
        rows.append({
            "seq": i,
            "name": r["name"],
            "qty": r["qty"],
            "material": r["material"] or "未指定",
            "path": r["path"],
        })
    return rows


def collect_bom(assembly_path: str | None = None,
                include_suppressed: bool = False) -> dict:
    """从装配体读明细。

    返回 `{ok, assembly, rows:[...], distinct_parts, total_items, missing_material}`

    `missing_material` 列出没有材料的零件 —— 这在 BOM 里是必须知道的信息，
    因为材料缺失时 SolidWorks 会退回水的密度（1000），质量会错 7.85 倍。
    """
    from .session import get_session, _value as _v

    sw = get_session().sw()
    md = sw.ActiveDoc

    if assembly_path:
        if not os.path.isfile(assembly_path):
            return {"ok": False, "error": f"装配文件不存在：{assembly_path}"}
        md = sw.OpenDoc(assembly_path, 2)              # 2 = swDocASSEMBLY
        if md is None:
            # 已经在文档里打开的情况下 OpenDoc 可能返回 None
            sw.ActivateDoc(assembly_path)
            md = sw.ActiveDoc
        else:
            sw.ActivateDoc(assembly_path)
            md = sw.ActiveDoc

    if md is None or _v(md, "GetType") != 2:
        return {"ok": False, "error": "当前文档不是装配体"}

    # 逐个组件读材料与路径。不用逐个打开零件——
    # 组件对应的零件在装配打开时已加载，直接问组件即可。
    comps = []
    # IAssemblyDoc.GetComponents(Boolean ToplevelOnly) 需要 1 个参数。
    # 不能走 _value 那套「属性还是方法」的猜测——它会在无参情况下直接调用，
    # 抛 COM 的「非选择性的参数」（DISP_E_PARAMNOTOPTIONAL）。
    # 这里有明确的签名，直接传参最可靠。
    try:
        raw = md.GetComponents(False)      # False = 包含子装配里的组件
    except Exception as exc:               # noqa: BLE001
        return {"ok": False,
                "error": f"读组件清单失败：{type(exc).__name__}: {exc}"}

    for c in (raw or []):
        try:
            name = str(_value(c, "Name2") or "")
            path = str(_value(c, "GetPathName") or "")
            # 材料：从组件关联的零件文档读。
            # 实测 IComponent2 自己的 GetMaterialUserName / GetMaterialIdName
            # 都返回空字符串，只有走 ModelDoc2.GetMaterialPropertyName2 才读得到。
            pdoc = _value(c, "GetModelDoc2", None)
            mat = material_of(pdoc)
            suppressed = bool(_value(c, "IsSuppressed", False))
            # 从明细表排除：SolidWorks 的原生 BOM 会跳过这些组件，我们也要跳过
            excl = _value(c, "ExcludeFromBOM", False)
            comps.append({"name": name, "path": path, "material": mat,
                          "suppressed": suppressed,
                          "exclude_from_bom": bool(excl)})
        except Exception:                              # noqa: BLE001
            continue

    rows = group_components(comps, include_suppressed=include_suppressed)

    missing = [r["name"] for r in rows if r["material"] == "未指定"]
    return {
        "ok": True,
        "assembly": str(_v(md, "GetPathName") or ""),
        "rows": rows,
        "distinct_parts": len(rows),
        "total_items": sum(r["qty"] for r in rows),
        "missing_material": missing,
        "note": ("材料缺失时 SolidWorks 默认密度是 1000 kg/m³（水），"
                 "质量会错约 7.85 倍。missing_material 非空就该先补材料。"
                 if missing else ""),
    }


def insert_bom_table(drawing_path: str | None = None,
                     x: float = 0.0, y: float = 0.0,
                     anchor: str = "bottom-left",
                     template: str = "",
                     use_anchor: bool = True,
                     timeout_s: int = 300) -> dict:
    """在工程图里插入原生 BOM 表。

    用 InsertBomTable6 —— 参数最多的那个版本，能控制编号方式和是否展开子装配。

    参数
    ----
    anchor      'bottom-left' / 'top-left' / 'top-right' / 'bottom-right'
    template    表格模板路径，留空用 SolidWorks 默认
    use_anchor  True 时用图纸模板里定义的 BOM 锚点定位（推荐）。
                实测 UseAnchorPoint=False 时给的 x,y 会让表格落在图框外，
                而且 TableAnnotation 在后期绑定下读不到也改不了位置，
                所以锚点模式是唯一可靠的做法。

    **实测结论（v1.2）**：锚点模式工作正常，表会插在标题栏上方
    （GB 明细表的标准位置）。之前看起来"表不存在"有两个原因：

      1. 工程图模板不对。装配图模板 `gb_assembly.drwdot` 不存在时
         会回退到 `gb_a0.drwdot`，A0 图纸太大，表在缩放后小到看不见。
         → 用 `produce()` 或明确指定 A3 模板。
      2. 插入后没重新缩放，视图还停在模型上，表在视野之外。
         → 现在插入后会自动调用 `ViewZoomtofit2()`。

    `ITableAnnotation` 上**没有** `GetPosition` / `SetPosition`，
    位置由 `Anchored` + `AnchorType` 控制；`AnchorType` 在 pywin32 下
    可读但赋值不生效（读了还是 2）。所以想控制位置，
    只能靠锚点 + 正确幅面的模板，不能靠坐标。
    """
    from .session import get_session, _value as _v

    sw = get_session().sw()
    if drawing_path:
        md = sw.OpenDoc(drawing_path, 3)               # 3 = swDocDRAWING
        if md is None:
            sw.ActivateDoc(drawing_path)
            md = sw.ActiveDoc
        else:
            sw.ActivateDoc(drawing_path)
            md = sw.ActiveDoc
    else:
        md = sw.ActiveDoc

    if md is None or _v(md, "GetType") != 3:
        return {"ok": False, "error": "当前文档不是工程图"}

    anchors = {
        "bottom-left": _ANCHOR_BOTTOM_LEFT,
        "top-left": _ANCHOR_TOP_LEFT,
        "top-right": 1,
        "bottom-right": 3,
    }
    anchor_type = anchors.get(anchor, _ANCHOR_BOTTOM_LEFT)

    # 第一张图纸的第一个视图是 BOM 表的宿主
    sheet = _v(md, "GetFirstView")
    view = _v(sheet, "GetNextView") if sheet is not None else None
    if view is None:
        return {"ok": False, "error": "工程图里没有视图，无法插入 BOM"}

    try:
        table = view.InsertBomTable6(
            bool(use_anchor),  # True = 用模板里定义的 BOM 锚点
            float(x), float(y),
            anchor_type,
            _BOM_TOP_LEVEL,
            "",                # Configuration：空 = 当前配置
            template or "",
            False,             # Hidden
            1,                 # IndentedNumberingType
            False,             # DetailedCutList
            False,             # DissolvePartLevelRows
            False,             # DisplayAsOneItem
        )
    except Exception as exc:                           # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if table is None:
        return {"ok": False,
                "error": "InsertBomTable6 返回 None —— 表格没建出来"}

    # 插完表必须重新缩放。
    # 实测：表是插在标题栏上方的（GB 明细表的标准位置），
    # 但插入时视图还停在模型上，表在视野之外——
    # 看起来像"表没建出来"，其实是没缩放过去。
    try:
        md.ViewZoomtofit2()
    except Exception:                                  # noqa: BLE001
        pass

    # 回读：行数必须 > 0，否则表是空的
    rows = 0
    try:
        rows = int(_value(table, "RowCount") or 0)
    except Exception:                                  # noqa: BLE001
        rows = 0

    return {
        "ok": rows > 0,
        "rows": rows,
        "columns": int(_value(table, "ColumnCount") or 0) or None,
        "anchor": anchor,
        "error": "" if rows > 0 else "表格建出来了但行数为 0",
    }


def bom_to_markdown(rows) -> str:
    """导出 Markdown 表格。不碰 SolidWorks。"""
    lines = ["| 序号 | 名称 | 数量 | 材料 |", "|---:|---|---:|---|"]
    for r in rows or []:
        lines.append(f"| {r.get('seq', '')} | {r.get('name', '')} | "
                     f"{r.get('qty', '')} | {r.get('material', '')} |")
    return "\n".join(lines)


def bom_to_csv(rows, path: str | None = None) -> str:
    """导出 CSV（Excel 可直接打开）。不碰 SolidWorks。

    带 UTF-8 BOM，否则中文在 Excel 里会乱码——这是国内用户最先遇到的问题。
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["序号", "名称", "数量", "材料", "路径"])
    for r in rows or []:
        w.writerow([r.get("seq"), r.get("name"), r.get("qty"),
                    r.get("material"), r.get("path")])
    text = buf.getvalue()
    if path:
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(text)
    return text
