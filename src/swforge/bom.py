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
    """取属性或方法，两种情况都试。

    SolidWorks 的 COM 接口在后期绑定下，无参方法会以属性形式暴露。
    直接按方法调用会抛 TypeError（这个坑在干涉检查里已经踩过一次）。
    """
    try:
        v = getattr(obj, name)
    except Exception:                                  # noqa: BLE001
        return default
    if callable(v):
        try:
            return v()
        except Exception:                              # noqa: BLE001
            return default
    return v


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
            by_path[key] = {
                "name": str(c.get("name") or os.path.basename(path)),
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
    # IAssemblyDoc.GetComponents(Boolean ToplevelOnly) 需要 1 个参数，
    # 不能当成无参方法用。_value 对 COM 方法只做 getattr 不调用，所以这里手动传参。
    raw = _v(md, "GetComponents")
    if callable(raw):
        raw = raw(False)          # False = 包含子装配里的组件

    for c in (raw or []):
        try:
            name = str(_value(c, "Name2") or "")
            path = str(_value(c, "GetPathName") or "")
            # 材料：优先用户可见名（如 Q235），退回内部 ID
            mat = _value(c, "GetMaterialUserName")
            if not mat:
                mat = _value(c, "GetMaterialIdName")
            mat = str(mat or "").strip()
            # SolidWorks 没赋材质时会返回空或者 "Default"
            if mat.lower() in ("", "default", "unspecified"):
                mat = ""
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
                     timeout_s: int = 300) -> dict:
    """在工程图里插入原生 BOM 表。

    用 InsertBomTable6 —— 参数最多的那个版本，能控制编号方式和是否展开子装配。

    参数
    ----
    anchor    'bottom-left' / 'top-left' / 'top-right' / 'bottom-right'
    template  表格模板路径，留空用 SolidWorks 默认
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
            False,             # UseAnchorPoint=False 时用 x,y
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
