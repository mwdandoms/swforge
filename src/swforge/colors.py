# -*- coding: utf-8 -*-
"""规则式分色 —— 按几何位置/尺寸给面着色。

为什么是「面级」而不是「体级」
------------------------------
SolidWorks 里 `IBody2.MaterialPropertyValues` 对 **开放曲面体**
完全不生效（渲染仍然用系统「曲面」色），而且体级赋值有概率静默丢失。
真正可靠的是 `IFace2.SetMaterialPropertyValues2(v, 1, None)` —— 逐面写，
写完回读能验证。本模块统一走面级。

规则的匹配对象是 **面的包围盒**（`IFace2.GetBox`）和 **面法向**，
所以「底部轮子」「四层料盘」「侧壁」这类区域规则都能表达。
"""

from __future__ import annotations

import math
import os

from .session import get_session

__all__ = ["apply_rules", "FaceRule", "read_back"]

# 9 元素：R G B Ambient Diffuse Specular Shininess Transparency Emission
_AMBIENT = 0.78
_DIFFUSE = 0.42


def _rgb9(rgb, ambient=_AMBIENT):
    values = tuple(float(x) for x in rgb)
    if len(values) != 3 or not all(math.isfinite(x) and 0 <= x <= 1 for x in values):
        raise ValueError("颜色必须是 3 个 0~1 的有限 RGB 数值")
    return [*values, ambient, _DIFFUSE, 0.16, 0.22, 0.0, 0.0]


def _value(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) and not hasattr(value, "_oleobj_") else value


def _part_document(sw, part_path=None):
    """Resolve the exact full path; another open part is never a substitute."""
    md = sw.ActiveDoc
    if part_path is None:
        if md is None or _value(md, "GetType") != 1:
            raise RuntimeError("当前文档不是零件")
        return md
    target = os.path.normcase(os.path.abspath(part_path))
    current = os.path.normcase(os.path.abspath(str(_value(md, "GetPathName")))) if md else None
    if md is None or current != target or _value(md, "GetType") != 1:
        md = sw.OpenDoc(target, 1)
    if md is None or _value(md, "GetType") != 1:
        raise RuntimeError(f"打不开零件：{part_path}")
    if os.path.normcase(os.path.abspath(str(_value(md, "GetPathName")))) != target:
        raise RuntimeError(f"打开的零件与请求路径不一致：{part_path}")
    return md


def _face_rgb(face):
    try:
        values = face.GetMaterialPropertyValues2(1, None)
    except (AttributeError, TypeError):
        values = _value(face, "MaterialPropertyValues")
    if values is None or len(values) < 3:
        return None
    rgb = tuple(float(x) for x in values[:3])
    return rgb if all(math.isfinite(x) and 0 <= x <= 1 for x in rgb) else None


def _save(md):
    from win32com.client import VARIANT
    import pythoncom

    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = bool(md.Save3(1, err, warn))
    return success and not err.value, int(err.value), int(warn.value)


class FaceRule:
    """一条面级配色规则。

    条件字段（全部可选，全部以 **mm** 计，AND 关系）::

        xmin_gt / xmax_lt / ymin_gt / ymax_lt / zmin_gt / zmax_lt
        size_lt / size_gt          最大边长范围
        normal_y_gt                面法向 |ny| 下限（0~1）
        center_x_gt / center_x_lt / center_y_gt / center_y_lt
        center_z_gt / center_z_lt
    """

    __slots__ = ("name", "color", "cond", "rgb")

    def __init__(self, name: str, color, **cond):
        allowed = {"xmin_gt", "xmax_lt", "ymin_gt", "ymax_lt", "zmin_gt", "zmax_lt",
                   "size_lt", "size_gt", "normal_y_gt", "center_x_gt", "center_x_lt",
                   "center_y_gt", "center_y_lt", "center_z_gt", "center_z_lt"}
        if set(cond) - allowed:
            raise ValueError(f"未知的配色条件：{', '.join(sorted(set(cond) - allowed))}")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in cond.values()):
            raise ValueError("配色条件必须是有限数值")
        if "normal_y_gt" in cond and not 0 <= cond["normal_y_gt"] <= 1:
            raise ValueError("normal_y_gt 必须在 0~1 范围内")
        self.name = name
        self.rgb = _rgb9(color)
        self.color = tuple(self.rgb[:3])
        self.cond = cond

    def to_dict(self) -> dict:
        return {"name": self.name, "color": list(self.color), "cond": self.cond}

    def matches(self, box: dict, normal_y: float) -> bool:
        c = self.cond
        if "xmin_gt" in c and not box["x0"] > c["xmin_gt"]:
            return False
        if "xmax_lt" in c and not box["x1"] < c["xmax_lt"]:
            return False
        if "ymin_gt" in c and not box["y0"] > c["ymin_gt"]:
            return False
        if "ymax_lt" in c and not box["y1"] < c["ymax_lt"]:
            return False
        if "zmin_gt" in c and not box["z0"] > c["zmin_gt"]:
            return False
        if "zmax_lt" in c and not box["z1"] < c["zmax_lt"]:
            return False
        size = max(box["x1"] - box["x0"], box["y1"] - box["y0"], box["z1"] - box["z0"])
        if "size_lt" in c and not size < c["size_lt"]:
            return False
        if "size_gt" in c and not size > c["size_gt"]:
            return False
        if "normal_y_gt" in c and not normal_y > c["normal_y_gt"]:
            return False
        cx = (box["x0"] + box["x1"]) / 2
        cy = (box["y0"] + box["y1"]) / 2
        cz = (box["z0"] + box["z1"]) / 2
        if "center_x_gt" in c and not cx > c["center_x_gt"]:
            return False
        if "center_x_lt" in c and not cx < c["center_x_lt"]:
            return False
        if "center_y_gt" in c and not cy > c["center_y_gt"]:
            return False
        if "center_y_lt" in c and not cy < c["center_y_lt"]:
            return False
        if "center_z_gt" in c and not cz > c["center_z_gt"]:
            return False
        if "center_z_lt" in c and not cz < c["center_z_lt"]:
            return False
        return True


def _face_box(face) -> dict | None:
    try:
        gb = face.GetBox                      # 后期绑定下 GetBox 是属性，早期绑定是方法
        b = tuple(gb() if callable(gb) else gb)
    except Exception:                                    # noqa: BLE001
        return None
    if not b or len(b) < 6:
        return None
    return {
        "x0": b[0] * 1000, "x1": b[3] * 1000,
        "y0": b[1] * 1000, "y1": b[4] * 1000,
        "z0": b[2] * 1000, "z1": b[5] * 1000,
    }


def apply_rules(part_path: str, rules: list[FaceRule],
                default_color=None, dry_run: bool = False) -> dict:
    """把规则套到已打开（或按路径打开）的零件上。

    返回统计：每条规则命中多少面、总共写了多少面、是否有回读失败。
    后写的规则优先（顺序敏感：先通用后特例）。
    """
    if len({r.name for r in rules}) != len(rules):
        raise ValueError("配色规则名称不能重复")
    fallback = _rgb9(default_color) if default_color is not None else None
    md = _part_document(get_session().sw(), part_path)

    from win32com.client import VARIANT
    import pythoncom

    hits = {r.name: 0 for r in rules}
    written = 0
    failed = 0
    verified = 0
    skipped = 0
    faces_total = 0

    bodies = md.GetBodies2(-1, False) or []
    for body in bodies:
        faces = body.GetFaces() or []
        for face in faces:
            faces_total += 1
            box = _face_box(face)
            if box is None:
                skipped += 1
                continue
            ny = 0.0
            try:
                n = _value(face, "Normal")
                if n:
                    ny = abs(n[1])
            except Exception:                            # noqa: BLE001
                pass
            chosen = None
            for rule in rules:
                if rule.matches(box, ny):
                    chosen = rule
            if chosen is None:
                if fallback is None:
                    continue
                chosen_rgb = fallback
            else:
                hits[chosen.name] += 1
                chosen_rgb = chosen.rgb
            if dry_run:
                continue
            try:
                face.SetMaterialPropertyValues2(
                    VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, chosen_rgb), 1, None
                )
                written += 1
                actual = _face_rgb(face)
                if actual is not None and all(abs(a - b) <= 1 / 255 + 1e-9 for a, b in zip(actual, chosen_rgb)):
                    verified += 1
                else:
                    failed += 1
            except Exception:                            # noqa: BLE001
                failed += 1

    saved = None
    save_error = ""
    if not dry_run and written:
        try:
            _value(md, "EditRebuild3")
            saved, err, warn = _save(md)
            if not saved:
                save_error = f"保存失败（错误 {err}，警告 {warn}）"
        except Exception as exc:                         # noqa: BLE001
            saved = False
            save_error = str(exc)

    return {
        "ok": failed == 0 and skipped == 0 and saved is not False,
        "faces_total": faces_total,
        "written": written,
        "verified": verified,
        "failed": failed,
        "skipped": skipped,
        "saved": saved,
        "save_error": save_error,
        "hits": hits,
        "dry_run": dry_run,
    }


def read_back(part_path: str | None = None, sample: int = 12) -> list[dict]:
    """回读若干面的颜色，用于验证分色是否真的写进去了。"""
    if isinstance(sample, bool) or not isinstance(sample, int) or sample < 0:
        raise ValueError("sample 必须是非负整数")
    md = _part_document(get_session().sw(), part_path)
    out = []
    n = 0
    for body in (md.GetBodies2(-1, False) or []):
        for face in (body.GetFaces() or []):
            if n >= sample:
                return out
            try:
                v = _face_rgb(face)
            except Exception:                            # noqa: BLE001
                v = None
            box = _face_box(face)
            out.append({
                "face": n,
                "rgb": [round(x, 3) for x in v[:3]] if v else None,
                "box": {k: round(x, 1) for k, x in box.items()} if box else None,
            })
            n += 1
    return out


