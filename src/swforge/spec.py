"""CLI/MCP 共用的 JSON 建模描述解析；本模块不连接 SolidWorks。"""

from __future__ import annotations

import inspect
import math
import os

from .modeling import PartBuilder

__all__ = ["builder_from_spec"]

_SHAPES = ("boxes", "tubes", "cylinders", "revolves", "stepped_shafts", "lofts", "springs", "auger_flights")
_SECTIONS = _SHAPES + ("cuts", "holes", "hole_grids", "fillets", "chamfers",
                      "linear_patterns", "circular_patterns", "mirrors", "shells", "ribs", "cosmetic_threads")


def _finite_json(value, location="spec"):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{location}: 不能包含 NaN 或 Infinity")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_json(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite_json(item, f"{location}[{index}]")


def builder_from_spec(out_path: str, spec: dict) -> PartBuilder:
    """完整校验并构造 DSL，成功返回后调用方才可执行 build()。

    基础体与放样先建，然后是切除、圆角和倒角，最后执行原生派生特征。
    seed/target 引用同一描述中的 tag。
    """
    if not isinstance(spec, dict):
        raise ValueError("spec 必须是 JSON 对象")
    design=None
    if 'parameters' in spec or 'requirements' in spec:
        import copy
        from .design import resolve_design
        design=copy.deepcopy(spec)
        spec=resolve_design(spec)['spec']
    unknown = set(spec) - {*_SECTIONS, "material", "merge", "feature_strategy"}
    if unknown:
        raise ValueError(f"未知 spec 字段: {', '.join(sorted(unknown))}")
    if not isinstance(out_path, str) or not out_path.strip() or not out_path.lower().endswith(".sldprt"):
        raise ValueError("out_path 必须是 .SLDPRT 文件路径")
    _finite_json(spec)
    material = spec.get("material", "Q235")
    if not isinstance(material, str) or not material.strip():
        raise ValueError("material 必须是非空字符串")
    merge = spec.get("merge", False)
    if not isinstance(merge, bool):
        raise ValueError("merge 必须是布尔值")
    builder = PartBuilder(os.path.abspath(out_path), material=material, merge=merge,
                          feature_strategy=spec.get('feature_strategy','compact'))
    builder.design_spec=design
    shape_count = 0
    for section in _SECTIONS:
        items = spec.get(section, [])
        if not isinstance(items, list):
            raise ValueError(f"{section} 必须是数组")
        for index, item in enumerate(items):
            location = f"{section}[{index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{location} 必须是对象")
            params = dict(item)
            if section == "boxes":
                params.setdefault("tag", f"体{index + 1}")
                method = builder.box
            elif section == "tubes":
                axis = params.pop("axis", "y")
                if axis not in ("x", "y", "z"):
                    raise ValueError(f"{location}.axis 必须是 x/y/z")
                _validate_tube(params, axis, location)
                method = getattr(builder, f"tube_{axis}")
            else:
                method = getattr(builder, {
                    "cylinders": "cylinder", "revolves": "revolve",
                    "stepped_shafts": "stepped_shaft",
                    "fillets": "fillet", "chamfers": "chamfer",
                    "cuts": "cut_box", "holes": "hole", "hole_grids": "hole_grid",
                    "lofts": "loft", "springs": "helix_spring", "auger_flights": "auger_flight", "linear_patterns": "linear_pattern",
                    "circular_patterns": "circular_pattern", "mirrors": "mirror",
                    "shells": "shell", "ribs": "rib", "cosmetic_threads": "cosmetic_thread",
                }[section])
            try:
                inspect.signature(method).bind(**params)
                method(**params)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{location}: {exc}") from exc
            if section in _SHAPES:
                shape_count += 1
    if not shape_count:
        raise ValueError("spec 没有任何形体")
    return builder


def _validate_tube(params, axis, location):
    wall = params.get("wall", 6.3)
    sizes = {"x": ("sy", "sz"), "y": ("sx", "sz"), "z": ("sx", "sy")}[axis]
    for name in ("wall", *sizes):
        value = wall if name == "wall" else params.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{location}.{name} 必须是有限正数")
    if any(params[name] <= 2 * wall for name in sizes):
        raise ValueError(f"{location}: 管壁厚必须小于截面尺寸的一半")
