# -*- coding: utf-8 -*-
"""实体干涉精确计算（零件级布尔求交）。

为什么不用装配级干涉检测
------------------------
本机 SW2025 SP5.0 实测：`AssemblyDoc.InterferenceDetectionManager` 与
`ToolsCheckInterference2` 对**确定重叠 500 mm³** 的两个立方体，
两者都返回 0 个干涉。API 可达但结果不可用，因此不作为判据。

本模块改走**零件级布尔求交**：
`IBody2.Operations2(SWBODYINTERSECT, 另一体, out err)` 返回交集实体，
再读它的质量属性拿体积。这个路径可精确验证（重叠体积可解析算出来）。

用法
----
把要检查的实体放进**同一个零件**（多实体），然后：

    from swforge.interference import body_interference, check_all_pairs
    body_interference(part_path, "A", "B")   # -> {"volume_mm3": 500.0, ...}
    check_all_pairs(part_path)               # -> 所有实体两两求交

装配体的两个零件如果都要查，用 `assembly_to_part_bodies()` 把它们
按各自位置塞进同一个零件再查（本版未实现，见 v0.8 计划）。
"""

from __future__ import annotations

import pythoncom

from .session import get_session, _value

__all__ = ["body_interference", "check_all_pairs", "SWBODYINTERSECT"]

SWBODYINTERSECT = 15901

# swBodyOperationError_e 常用码（实测 1 是「不是 API 临时体」，必须先用 Copy2）
BODY_OP_ERRORS = {
    0: "swBodyOperationNoError",
    1: "swBodyOperationNonApiBody",
    2: "swBodyOperationWrongType",
    3: "swBodyOperationFailGeomCondition",
    5: "swBodyOperationDisjointBodies",
    6: "swBodyOperationEmptyBody",
    1058: "swBodyOperationBooleanFail",
    1067: "swBodyOperationNoIntersect",
}


def _as_int(v, default: int = 0) -> int:
    """VARIANT / int / None 统一转 int（byref VARIANT 的 .value 可能是嵌套 VARIANT）。"""
    try:
        cur = getattr(v, "value", v)
        while hasattr(cur, "value"):
            cur = cur.value
        return int(cur)
    except Exception:                                    # noqa: BLE001
        return default


def _bodies(md):
    """取当前零件的实体列表（界面/后期绑定两种形态都兼容）。"""
    fn = getattr(md, "GetBodies2", None)
    if fn is None:
        fn = _value(md, "GetBodies2")
    return fn(0, False) or []          # 0 = swSolidBody


def _wrap(b):
    import win32com.client

    return b if hasattr(b, "GetMassProperties") else win32com.client.Dispatch(b)


def _body_volume_mm3(body) -> float:
    """用密度 1.0 取质量属性，第 4 项是体积（m³）。"""
    mp = body.GetMassProperties(1.0)
    if mp is None or len(mp) < 4:
        return 0.0
    return float(mp[3]) * 1e9


def _activate_part(part_path: str):
    """打开并激活零件文档。

    注意：`sw.ActivateDoc` 在这台机器上不一定真的切换活动文档，
    必须用带 byref 的 `ActivateDoc3` 并回读确认，否则后续
    `md.GetBodies2` 会落到别的文档上报 `<unknown>.GetBodies2`。
    """
    import os

    from win32com.client import VARIANT

    sw = get_session().sw()
    target = os.path.normcase(os.path.abspath(part_path))
    title = None
    for d in (_value(sw, "GetDocuments") or []):
        try:
            cur = str(_value(d, "GetPathName"))
        except Exception:                                # noqa: BLE001
            continue
        if cur and os.path.normcase(os.path.abspath(cur)) == target:
            title = str(_value(d, "GetTitle"))
            break
    if title is None:
        doc = sw.OpenDoc(part_path, 1)
        if doc is None:
            raise RuntimeError(f"打不开零件：{part_path}")
        title = str(_value(doc, "GetTitle"))

    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    sw.ActivateDoc3(title, False, 0, err)
    md = sw.ActiveDoc
    cur = str(_value(md, "GetPathName")) if md is not None else ""
    if not cur or os.path.normcase(os.path.abspath(cur)) != target:
        raise RuntimeError(f"激活零件失败：{part_path}（当前 {cur or '无'}）")
    return md


def body_interference(part_path: str | None = None,
                      tag_a: str | None = None,
                      tag_b: str | None = None) -> dict:
    """两个实体的精确干涉体积。

    `tag_a` / `tag_b` 是实体名（`IBody2.Name`）。
    都给时只算这一对；都不给时取前两个实体。
    """
    sw = get_session().sw()
    md = sw.ActiveDoc if part_path is None else _activate_part(part_path)
    if md is None or _value(md, "GetType") != 1:
        return {"ok": False, "error": "当前文档不是零件"}

    bodies = [_wrap(b) for b in _bodies(md)]
    if len(bodies) < 2:
        return {"ok": False, "error": f"实体不足两个（当前 {len(bodies)}）",
                "bodies": len(bodies)}

    def pick(name, fallback):
        for b in bodies:
            if str(_value(b, "Name")) == name:
                return b
        return bodies[fallback]

    a = pick(tag_a, 0)
    b = pick(tag_b, 1)
    name_a, name_b = str(_value(a, "Name")), str(_value(b, "Name"))

    # 包围盒先粗筛：不相交就不必做布尔运算
    try:
        ba = list(a.GetBodyBox())
        bb = list(b.GetBodyBox())
        overlap = all(min(ba[i + 3], bb[i + 3]) > max(ba[i], bb[i]) for i in range(3))
    except Exception:                                    # noqa: BLE001
        overlap = True

    vol_a = _body_volume_mm3(a)
    vol_b = _body_volume_mm3(b)

    from win32com.client import VARIANT

    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    inter_vol = 0.0
    pieces = 0
    if overlap:
        # 关键：Operations2 只接受「临时体」。直接拿文档里的体去求交，
        # 会返回 swBodyOperationNonApiBody(1) 且结果为 None。
        # Copy2() 产生的副本 IsTemporaryBody()==True，之后就正常了。
        try:
            ta = _wrap(a.Copy2(False))
            tb = _wrap(b.Copy2(False))
            if not ta.IsTemporaryBody() or not tb.IsTemporaryBody():
                return {"ok": False, "error": "Copy2 未产生临时体，无法求交",
                        "a": name_a, "b": name_b}
            # out 参数必须传普通 int（传 VARIANT 会 TypeError）；
            # 返回值是 (结果数组, 错误码)
            res = ta.Operations2(SWBODYINTERSECT, tb, 0)
            arr, code = (res if isinstance(res, tuple) and len(res) == 2
                         else (res, 0))
            if code not in (0, None):
                return {"ok": False,
                        "error": f"布尔求交错误码 {code}（{BODY_OP_ERRORS.get(code, '未知')}）",
                        "a": name_a, "b": name_b}
            if arr is not None:
                items = list(arr) if isinstance(arr, (tuple, list)) else [arr]
                for x in items:
                    while hasattr(x, "value"):
                        x = x.value
                    inter_vol += _body_volume_mm3(_wrap(x))
                pieces = len(items)
        except Exception as exc:                         # noqa: BLE001
            return {"ok": False, "error": f"布尔求交失败: {type(exc).__name__}: {exc}",
                    "a": name_a, "b": name_b}

    return {
        "ok": True,
        "a": name_a, "b": name_b,
        "volume_a_mm3": round(vol_a, 3),
        "volume_b_mm3": round(vol_b, 3),
        "bbox_overlap": bool(overlap),
        "interference_volume_mm3": round(inter_vol, 3),
        "intersection_pieces": pieces,
        "interfere": inter_vol > 1e-6,
        "error_code": code if overlap else 0,
        "note": "干涉体积由实体布尔求交精确计算，不是包围盒估算",
    }


def check_all_pairs(part_path: str | None = None) -> dict:
    """所有实体两两求交，返回有干涉的对。"""
    sw = get_session().sw()
    md = sw.ActiveDoc if part_path is None else _activate_part(part_path)
    if md is None or _value(md, "GetType") != 1:
        return {"ok": False, "error": "当前文档不是零件"}
    bodies = [_wrap(b) for b in _bodies(md)]
    names = [str(_value(b, "Name")) for b in bodies]
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            r = body_interference(part_path, names[i], names[j])
            if r.get("ok") and r.get("interfere"):
                pairs.append(r)
    return {"ok": True, "bodies": len(names), "names": names,
            "interfering_pairs": pairs, "count": len(pairs)}
