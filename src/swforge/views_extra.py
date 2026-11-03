# -*- coding: utf-8 -*-
"""剖视图与局部放大。

为什么单独一个模块
------------------
这两个视图和普通投影视图的生成方式完全不同：

- 三视图：`CreateDrawViewFromModelView3(model, "*前视", x, y, 0)` → 一步到位
- 剖视图：必须先**在某个视图上画一条剖切线**，再调 `CreateSectionViewAt*`
- 局部放大：必须先**在某个视图上画一个圆**，再调 `CreateDetailViewAt*`

所以它们需要「先画辅助几何，再生成视图」这个两步流程。

实测踩过的坑（v1.2）
--------------------
1. `CreateSectionViewAt5` 的最后一个参数是 `SectionDepth`（剖切深度）。
   传 `0.0` 时在某些状态下返回 None。`CreateSectionViewAt4` 没有这个参数，
   更稳。默认用 At4。

2. 画完剖切线之后**不要**先去调 `SelectByID2` 选这选那——
   选不中会抛 `com_error`，把选择状态搞乱，导致随后的
   `CreateSectionViewAt5` 返回 False。画完直接生成就行。

3. 草图必须画在**激活的视图**里，所以要先 `md.ActivateView(视图名)`。
   不激活的话草图会画到图纸层面，剖切线与视图没关联。
"""

from __future__ import annotations

import os

__all__ = [
    "add_section_view",
    "add_detail_view",
    "SECTION_VERTICAL",
    "SECTION_HORIZONTAL",
]

# 剖切线方向
SECTION_VERTICAL = "vertical"      # 竖线 → 得到左/右剖视
SECTION_HORIZONTAL = "horizontal"  # 横线 → 得到上/下剖视


def _value(obj, name, default=None):
    """取 COM 属性或方法。带 _oleobj_ 的（COM 对象）不要当函数调。"""
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


def _open_drawing(sw, drawing_path):
    md = sw.ActiveDoc if not drawing_path else None
    if drawing_path:
        if not os.path.isfile(drawing_path):
            return None, f"工程图不存在：{drawing_path}"
        md = sw.OpenDoc(drawing_path, 3)               # 3 = swDocDRAWING
        if md is None:
            sw.ActivateDoc(drawing_path)
            md = sw.ActiveDoc
        else:
            sw.ActivateDoc(drawing_path)
            md = sw.ActiveDoc
    if md is None or _value(md, "GetType") != 3:
        return None, "当前文档不是工程图"
    return md, ""


def _pick_view(md, view_name=None):
    """按名字或默认第一个模型视图。"""
    from .drawing import _view_list

    views = _view_list(md)
    if view_name:
        for v, nm in views:
            if nm == view_name:
                return v, nm, ""
        return None, "", f"找不到视图：{view_name}"
    for v, nm in views:
        # Type 7 是模型视图（投影视图）
        if _value(v, "Type") in (7, 4, 2):
            return v, nm, ""
    if views:
        return views[0][0], views[0][1], ""
    return None, "", "工程图里没有视图"


def add_section_view(drawing_path: str | None = None,
                     view_name: str | None = None,
                     label: str = "A",
                     direction: str = SECTION_VERTICAL,
                     offset: float = 0.20,
                     offset_y: float = -0.10,
                     depth: float = 0.0) -> dict:
    """在工程图上加一个剖视图。

    参数
    ----
    view_name   在哪个视图上画剖切线；省略则用第一个模型视图
    label       剖视图字母（GB 用 A、B、C……）
    direction   'vertical' 竖剖切线 / 'horizontal' 横剖切线
    offset      剖视图相对源视图中心的水平偏移（米，0.20 ≈ 200mm）
    offset_y    纵向偏移。**必须有**，因为新视图和源视图位置重叠时
                SolidWorks 会静默返回 None，看起来像"功能不支持"。
    depth       剖切深度，0 = 不指定。**注意传非 0 可能让生成失败**，
                默认走不带深度参数的 CreateSectionViewAt4

    返回 `{ok, name, view_count_before, view_count_after, error}`
    """
    from .session import get_session
    from .drawing import _view_list

    sw = get_session().sw()
    md, err = _open_drawing(sw, drawing_path)
    if md is None:
        return {"ok": False, "error": err}

    src, src_name, err = _pick_view(md, view_name)
    if src is None:
        return {"ok": False, "error": err}

    before = len(_view_list(md))
    o = [float(x) for x in (_value(src, "GetOutline") or [])]
    if len(o) < 4:
        return {"ok": False, "error": "取不到源视图轮廓"}
    cx = (o[0] + o[2]) / 2.0
    cy = (o[1] + o[3]) / 2.0

    try:
        # 草图必须画在激活的视图里
        md.ActivateView(src_name)
        md.ClearSelection2(True)
        md.SketchManager.InsertSketch(True)

        if direction == SECTION_HORIZONTAL:
            md.SketchManager.CreateLine(o[0] - 0.008, cy, 0, o[2] + 0.008, cy, 0)
        else:
            md.SketchManager.CreateLine(cx, o[1] - 0.008, 0, cx, o[3] + 0.008, 0)

        md.SketchManager.InsertSketch(True)
        # 注意：退出草图后**不要**再 ClearSelection2。
        # 剖切线必须保持选中，CreateSectionViewAt* 靠它知道剖在哪。
        # 清掉选择后 API 直接返回 None，不报任何错。

        # 位置必须和源视图错开。实测：new 位置和源视图重叠时
        # CreateSectionViewAt4 直接返回 None，什么错都不报。
        px, py = cx + offset, cy + offset_y

        if depth and depth > 0:
            new_view = md.CreateSectionViewAt5(
                px, py, 0, label, 0, None, float(depth))
        else:
            new_view = md.CreateSectionViewAt4(
                px, py, 0, label, 0, None)
    except Exception as exc:                           # noqa: BLE001
        return {"ok": False,
                "error": f"{type(exc).__name__}: {exc}"}

    after = len(_view_list(md))
    if new_view is None:
        return {"ok": False, "error": "CreateSectionView 返回 None，剖视图未生成",
                "view_count_before": before, "view_count_after": after}

    return {
        "ok": after > before,
        "name": str(_value(new_view, "Name") or ""),
        "label": label,
        "direction": direction,
        "view_count_before": before,
        "view_count_after": after,
        "error": "" if after > before else "视图数没有增加",
    }


def add_detail_view(drawing_path: str | None = None,
                    view_name: str | None = None,
                    label: str = "I",
                    scale: float = 2.0,
                    radius: float = 0.012,
                    offset_x: float = 0.18,
                    offset_y: float = -0.12) -> dict:
    """加一个局部放大视图。

    参数
    ----
    view_name   在哪个视图上画放大圆圈；省略则用第一个模型视图
    label       放大图标签（GB 用 I、II……）
    scale       放大倍数
    radius      圆圈半径（米，0.012 ≈ 12mm）
    offset_x/y  放大图相对源视图中心的偏移

    返回 `{ok, name, view_count_before, view_count_after, error}`
    """
    from .session import get_session
    from .drawing import _view_list

    sw = get_session().sw()
    md, err = _open_drawing(sw, drawing_path)
    if md is None:
        return {"ok": False, "error": err}

    src, src_name, err = _pick_view(md, view_name)
    if src is None:
        return {"ok": False, "error": err}

    before = len(_view_list(md))
    o = [float(x) for x in (_value(src, "GetOutline") or [])]
    if len(o) < 4:
        return {"ok": False, "error": "取不到源视图轮廓"}
    cx = (o[0] + o[2]) / 2.0
    cy = (o[1] + o[3]) / 2.0

    try:
        md.ActivateView(src_name)
        md.ClearSelection2(True)
        md.SketchManager.InsertSketch(True)
        md.SketchManager.CreateCircle(cx, cy, 0, cx + radius, cy, 0)
        md.SketchManager.InsertSketch(True)
        # 同上：放大圆圈要保持选中

        # 同样：位置不能和源视图重叠，否则返回 None
        px, py = cx + offset_x, cy + offset_y
        new_view = md.CreateDetailViewAt4(
            px, py, 0,
            0,                       # Style
            float(scale), float(scale),
            label,
            0,                       # Showtype
            True,                    # FullOutline
            False,                   # JaggedOutline
            False,                   # NoOutline
            1,                       # ShapeIntensity
        )
    except Exception as exc:                           # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    after = len(_view_list(md))
    if new_view is None:
        return {"ok": False, "error": "CreateDetailViewAt4 返回 None",
                "view_count_before": before, "view_count_after": after}

    return {
        "ok": after > before,
        "name": str(_value(new_view, "Name") or ""),
        "label": label,
        "scale": scale,
        "view_count_before": before,
        "view_count_after": after,
        "error": "" if after > before else "视图数没有增加",
    }
