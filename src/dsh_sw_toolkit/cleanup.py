# -*- coding: utf-8 -*-
"""导入清理 —— STEP/IGES 模型的体检与瘦身。

真实痛点
--------
供应商给的 STEP 常见两类问题：

1. **垃圾实体**：某个零件的坐标写错，出现 6 000 000 mm 量级的方块。
   导入后「缩放到适合」会把真实 2 m 的模型缩成一个点，看起来像空白文件。
2. **大堆孤立曲面体**：本该是一个实体，结果拆成几百个开放曲面。
   表现是模型全白 / 曲面错误 / 无法上色。

本模块把这两个诊断做成固定流程：先量包络，再按「尺寸阈值」
或「与主体的距离」挑出可疑体，删之前给出清单，删之后重新量包络。
"""

from __future__ import annotations

import math

from .session import get_session

__all__ = ["survey", "delete_bodies", "purge_giant", "purge_small"]

# swBodyType_e 的实测值（别信直觉：swAllBodies 是 -1 不是 2）
SW_SOLID = 0          # swSolidBody
SW_SHEET = 1          # swSheetBody
SW_ALL = -1           # swAllBodies


def _bodies(md, kind: int = SW_ALL) -> list:
    # COM failures are not an empty model: callers must not report success on a
    # stale handle or use an invented zero count as evidence of deletion.
    return list(md.GetBodies2(kind, False) or [])


def _bbox(body) -> dict | None:
    try:
        value = body.GetBodyBox
        b = tuple(value() if callable(value) else value)
    except Exception:                                    # noqa: BLE001
        return None
    if len(b) < 6 or not all(math.isfinite(float(x)) for x in b[:6]):
        return None
    return {
        "x0": b[0] * 1000, "x1": b[3] * 1000,
        "y0": b[1] * 1000, "y1": b[4] * 1000,
        "z0": b[2] * 1000, "z1": b[5] * 1000,
    }


def _size(box: dict) -> tuple[float, float, float]:
    return (box["x1"] - box["x0"], box["y1"] - box["y0"], box["z1"] - box["z0"])


def survey(include_boxes: bool = False, top_n: int = 20) -> dict:
    """量当前文档的包络与实体构成。"""
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 0:
        raise ValueError("top_n 必须是非负整数")
    sess = get_session()
    md = sess.sw().ActiveDoc
    if md is None:
        raise RuntimeError("没有打开的文档")

    solids = _bodies(md, SW_SOLID)
    sheets = _bodies(md, SW_SHEET)
    everything = solids + sheets

    x0 = y0 = z0 = 1e18
    x1 = y1 = z1 = -1e18
    items = []
    for b in everything:
        box = _bbox(b)
        if box is None:
            continue
        x0 = min(x0, box["x0"]); x1 = max(x1, box["x1"])
        y0 = min(y0, box["y0"]); y1 = max(y1, box["y1"])
        z0 = min(z0, box["z0"]); z1 = max(z1, box["z1"])
        sx, sy, sz = _size(box)
        items.append({
            "name": str(b.Name),
            "box": box,
            "size_mm": [round(sx, 1), round(sy, 1), round(sz, 1)],
            "max_dim": round(max(sx, sy, sz), 1),
        })

    items.sort(key=lambda d: -d["max_dim"])
    res = {
        "ok": len(items) == len(everything),
        "solid_bodies": len(solids),
        "sheet_bodies": len(sheets),
        "total_bodies": len(everything),
        "envelope_mm": {
            "x": [round(x0, 1), round(x1, 1), round(x1 - x0, 1)],
            "y": [round(y0, 1), round(y1, 1), round(y1 - y0, 1)],
            "z": [round(z0, 1), round(z1, 1), round(z1 - z0, 1)],
        } if items else None,
        "unmeasured_bodies": len(everything) - len(items),
        "largest": [
            {"name": d["name"], "max_dim": d["max_dim"], "size_mm": d["size_mm"]}
            for d in items[:top_n]
        ],
    }
    if include_boxes:
        res["bodies"] = items
    return res


def _select_bodies(md, targets) -> int:
    md.ClearSelection2(True)
    n = 0
    for b in targets:
        try:
            if b.Select(True, 0):       # ★ Append=True，否则只剩最后一个
                n += 1
        except Exception:                                # noqa: BLE001
            pass
    return n


def delete_bodies(md, targets) -> dict:
    """删除一批 body（用 InsertDeleteBody2，生成可回滚的删除特征）。"""
    targets = list(targets)
    if not targets:
        return {"ok": True, "deleted": 0, "before": None, "after": None}
    before = len(_bodies(md))
    n = _select_bodies(md, targets)
    if n != len(targets):
        md.ClearSelection2(True)
        return {"ok": False, "selected": n, "deleted": 0,
                "before": before, "after": before,
                "error": "部分实体选择失败，未执行删除"}
    feat = None
    try:
        feat = md.FeatureManager.InsertDeleteBody2(False)
    except Exception as exc:                             # noqa: BLE001
        return {"ok": False, "deleted": 0, "error": str(exc),
                "before": before, "after": len(_bodies(md))}
    finally:
        md.ClearSelection2(True)
    try:
        rebuild = md.EditRebuild3
        if callable(rebuild):
            rebuild()
    except Exception:                                    # noqa: BLE001
        pass
    after = len(_bodies(md))
    success = feat is not None and before - after == len(targets)
    return {
        "ok": success,
        "selected": n,
        "deleted": before - after,
        "feature": str(feat.Name) if feat is not None else None,
        "before": before,
        "after": after,
        "error": "" if success else "删除结果与请求实体数不一致，请检查删除特征",
    }


def purge_giant(md, threshold_mm: float = 5000.0, dry_run: bool = True) -> dict:
    """删掉最大边长超过阈值的「垃圾体」。

    典型场景：导入后模型只有几个像素大 —— 因为另有一个 6 km 的方块
    把包络撑爆了。阈值默认 5 m，比绝大多数整机都大。
    """
    if not math.isfinite(threshold_mm) or threshold_mm <= 0:
        raise ValueError("threshold_mm 必须是有限正数")
    targets = []
    detail = []
    for b in _bodies(md):
        box = _bbox(b)
        if box is None:
            continue
        m = max(_size(box))
        if m > threshold_mm:
            targets.append(b)
            detail.append({"name": str(b.Name), "max_dim": round(m, 1)})
    if dry_run or not targets:
        return {"ok": True, "dry_run": dry_run, "candidates": detail}
    r = delete_bodies(md, targets)
    r["candidates"] = detail
    return r


def purge_small(md, max_dim_mm: float = 120.0, min_y_mm: float | None = None,
                dry_run: bool = True) -> dict:
    """删掉零碎小体（导入后常见的「碎片」）。

    `min_y_mm` 可限定只处理某个高度以上的碎片，避免误删标准件。
    """
    if not math.isfinite(max_dim_mm) or max_dim_mm <= 0:
        raise ValueError("max_dim_mm 必须是有限正数")
    if min_y_mm is not None and not math.isfinite(min_y_mm):
        raise ValueError("min_y_mm 必须是有限数")
    targets = []
    detail = []
    for b in _bodies(md):
        box = _bbox(b)
        if box is None:
            continue
        m = max(_size(box))
        if m <= 0 or m >= max_dim_mm:
            continue
        if min_y_mm is not None and box["y0"] <= min_y_mm:
            continue
        targets.append(b)
        detail.append({"name": str(b.Name), "max_dim": round(m, 1),
                       "y": [round(box["y0"], 1), round(box["y1"], 1)]})
    if dry_run or not targets:
        return {"ok": True, "dry_run": dry_run, "candidates": detail}
    r = delete_bodies(md, targets)
    r["candidates"] = detail
    return r

