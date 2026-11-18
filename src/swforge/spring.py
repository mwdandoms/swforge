# -*- coding: utf-8 -*-
"""圆柱螺旋压缩弹簧（等螺距、开放端）的受限几何。

为什么只做「受限几何」
====================
弹簧参数空间很大：变螺距、端圈并紧、端面磨平、锥形、拉簧带钩、扭簧带臂……
一次全做必然做不扎实。这里只做最常见的一种：

    等螺距 + 开放端 + 圆线截面 + 圆柱螺旋（无锥度）

其余一律在建之前就拒绝，并说明原因 —— 比建出来个错的强。

几何关系（解析值，用于回读校验）
================================
    中心线长度   L = √((π·D·n)² + H²)          D=中径 n=圈数 H=中心线轴向高度
    理论体积     V = π·(d/2)² · L              d=线径
    径向外廓     D + d
    轴向外廓     H + d·(π·D)/√((π·D)² + p²)    p=螺距（端部圆截面倾斜造成的超出量）

为什么用「中心线高度」而不是「自由高度」
----------------------------------------
自由高度是含端部圆截面倾斜超出量的外廓高度，会随螺距变化。用中心线高度
（即螺旋线本身的高度）作为输入，几何是确定的；自由高度另算，见
``expected_bounds_mm`` 的第三个分量。

来源说明
--------
``InsertHelix`` 与 ``InsertProtrusionSwept4`` 的参数语义、以及「扫掠第 18 参
CircularProfile=True 可省掉截面草图」这一关键结论，参考了 MIT 许可的
wzyn20051216/solidworks-automation-skill 项目（scripts/sw_spring.py），
并按 swforge 的约定重写。详见 THIRD_PARTY_NOTICES.md。
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

#: SW 螺旋线定义方式：1 = 高度和圈数
HELIX_DEFINED_BY_HEIGHT_AND_REVOLUTION = 1

#: 支持范围（超出直接拒绝，不静默生成）
TURNS_RANGE = (1.0, 20.0)
WIRE_RANGE = (0.1, 50.0)
MEAN_MAX = 500.0
HEIGHT_MAX = 2000.0
MEAN_OVER_WIRE_MIN = 4.0

#: 体积校验容差（相对）。扫掠是数值运算，0.5% 足够严
VOLUME_REL_TOL = 0.005


@dataclass(frozen=True)
class SpringSpec:
    """等螺距圆柱螺旋压缩弹簧（开放端）。单位 mm / 圈。"""

    wire_diameter_mm: float        # 线径 d
    mean_diameter_mm: float        # 中径 D
    height_mm: float               # 中心线轴向高度 H（不是自由高度）
    turns: float                   # 圈数 n
    clockwise: bool = False        # 旋向：True=右旋（顺时针）

    def to_dict(self) -> dict:
        return asdict(self)


def _positive(value, name: str) -> float:
    """必须是有限的非布尔正数。布尔是 int 的子类，不挡住会把 True 当 1 用。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为有限正数，不能是布尔值")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须为有限正数，收到 {value!r}") from None
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} 必须为有限正数，收到 {value!r}")
    return v


def validate(spec: SpringSpec) -> dict:
    """校验受限几何并给出解析值。不合法直接抛 ValueError。"""
    wire = _positive(spec.wire_diameter_mm, "线径")
    mean = _positive(spec.mean_diameter_mm, "中径")
    height = _positive(spec.height_mm, "中心线高度")
    turns = _positive(spec.turns, "圈数")
    if not isinstance(spec.clockwise, bool):
        raise ValueError("clockwise 必须为布尔值")

    lo, hi = TURNS_RANGE
    if not lo <= turns <= hi:
        raise ValueError(f"圈数需在 {lo:g}..{hi:g} 之间，收到 {turns:g}")
    lo, hi = WIRE_RANGE
    if not lo <= wire <= hi:
        raise ValueError(f"线径需在 {lo:g}..{hi:g} mm 之间，收到 {wire:g}")
    if mean > MEAN_MAX:
        raise ValueError(f"中径不得超过 {MEAN_MAX:g} mm，收到 {mean:g}")
    if height > HEIGHT_MAX:
        raise ValueError(f"中心线高度不得超过 {HEIGHT_MAX:g} mm，收到 {height:g}")
    if mean < wire * MEAN_OVER_WIRE_MIN:
        raise ValueError(
            f"中径至少为线径的 {MEAN_OVER_WIRE_MIN:g} 倍（否则圈与圈干涉），"
            f"收到 中径 {mean:g} / 线径 {wire:g}")

    pitch = height / turns
    if pitch < wire * 1.25:
        raise ValueError(
            f"螺距 {pitch:.3f} mm 小于线径的 1.25 倍（{wire * 1.25:.3f} mm），圈与圈会相碰")
    if pitch > mean * 0.5:
        raise ValueError(
            f"螺距 {pitch:.3f} mm 超过中径的一半（{mean * 0.5:.3f} mm），"
            f"超出「弹簧」的常规比例（这是拉簧/大螺距螺旋，不在本 API 范围）")

    circumference = math.pi * mean
    centerline_length = math.hypot(circumference * turns, height)
    ideal_volume = math.pi * (wire / 2) ** 2 * centerline_length
    return {
        "pitch_mm": pitch,
        "circumference_mm": circumference,
        "centerline_length_mm": centerline_length,
        "ideal_volume_mm3": ideal_volume,
        "wire_diameter_mm": wire,
        "mean_diameter_mm": mean,
        "height_mm": height,
        "turns": turns,
        "clockwise": spec.clockwise,
    }


def expected_bounds_mm(calculated: dict) -> list[float]:
    """三轴外廓尺寸（升序）。顺序与建模平面无关，便于与实测值逐项比较。"""
    wire = calculated["wire_diameter_mm"]
    mean = calculated["mean_diameter_mm"]
    height = calculated["height_mm"]
    circumference = calculated["circumference_mm"]
    pitch = calculated["pitch_mm"]
    # 端部圆截面在轴向的倾斜超出量
    end_axial_extent = wire * circumference / math.hypot(circumference, pitch)
    radial = mean + wire
    axial = height + end_axial_extent
    return sorted([radial, radial, axial])


def verify(volume_mm3: float, calculated: dict,
           *, rel_tol: float = VOLUME_REL_TOL) -> dict:
    """把实测体积与解析值对比。

    这是弹簧的**第一道校验**：扫掠成不成功、截面有没有按直径走，体积会立刻暴露。
    但体积验不出旋向（左右旋体积一样），旋向必须另外回读螺旋线定义。
    """
    ideal = calculated["ideal_volume_mm3"]
    actual = float(volume_mm3 or 0.0)
    if ideal <= 0:
        raise ValueError("解析体积必须为正")
    deviation = abs(actual - ideal) / ideal
    ok = deviation <= rel_tol
    return {
        "ok": ok,
        "ideal_volume_mm3": round(ideal, 3),
        "actual_volume_mm3": round(actual, 3),
        "deviation_ratio": round(deviation, 6),
        "deviation_pct": round(deviation * 100, 3),
        "rel_tol": rel_tol,
        "reason": (None if ok else
                   f"实测体积 {actual:.1f} mm³ 与解析值 {ideal:.1f} mm³ "
                   f"偏差 {deviation * 100:.2f}%，超过 {rel_tol * 100:.1f}% —— "
                   f"扫掠截面或螺旋参数与预期不符"),
    }


def describe(spec: SpringSpec) -> str:
    """给日志/报错用的一行摘要。"""
    return (f"弹簧 d{spec.wire_diameter_mm:g}×D{spec.mean_diameter_mm:g}"
            f"×H{spec.height_mm:g} n{spec.turns:g}"
            f" {'右旋' if spec.clockwise else '左旋'}")


def verify_bounds(actual_bounds, expected, *, rel_tol: float = 0.002,
                  abs_tol: float = 0.03) -> dict:
    """把实测三轴外廓与解析外廓比对（升序逐项）。

    体积校验看不出「旋向错了」这类问题（左右旋体积一样），
    外廓校验能补上尺寸层面的错误；旋向仍以螺旋线定义回读为准。
    """
    if actual_bounds is None:
        return {"ok": False, "reason": "没有实测外廓", "expected_mm": expected,
                "actual_mm": None}
    try:
        actual = sorted(float(v) for v in actual_bounds)
    except (TypeError, ValueError):
        return {"ok": False, "reason": f"实测外廓不是数值：{actual_bounds!r}",
                "expected_mm": expected, "actual_mm": None}
    if len(actual) != 3:
        return {"ok": False, "reason": f"实测外廓应有 3 个分量，收到 {len(actual)}",
                "expected_mm": expected, "actual_mm": actual}
    bad = []
    for i, (a, e) in enumerate(zip(actual, sorted(expected))):
        if not math.isclose(a, e, rel_tol=rel_tol, abs_tol=abs_tol):
            bad.append(f"第{i + 1}轴 实测 {a:.3f} vs 解析 {e:.3f} mm")
    return {
        "ok": not bad,
        "expected_mm": [round(v, 3) for v in sorted(expected)],
        "actual_mm": [round(v, 3) for v in actual],
        "rel_tol": rel_tol,
        "abs_tol_mm": abs_tol,
        "reason": (None if not bad else "外廓不符：" + "；".join(bad)),
    }

def create_spring(out_path, *, wire_diameter, mean_diameter, height, turns,
                  clockwise: bool = True, material: str = "65Mn") -> dict:
    """建一个弹簧并返回回读结果。CLI 与 MCP 共用这一入口。

    返回里的 ``volume_check`` 含两道校验：
      ① 解析体积对比（0.5% 容差）
      ② B-Rep 极值外廓对比（0.2% 容差）
    任一不过，``ok`` 为 False 并给出原因。
    """
    import os as _os

    from .modeling import PartBuilder

    if _os.path.splitext(str(out_path))[1].lower() != ".sldprt":
        return {"ok": False, "error": "输出文件必须使用 .SLDPRT 扩展名"}
    if _os.path.exists(out_path):
        return {"ok": False, "error": "输出文件已存在；请使用新路径，避免覆盖原模型"}

    spec = SpringSpec(wire_diameter_mm=wire_diameter, mean_diameter_mm=mean_diameter,
                      height_mm=height, turns=turns, clockwise=clockwise)
    try:
        calc = validate(spec)
    except ValueError as exc:
        return {"ok": False, "error": f"参数超出受限几何范围：{exc}"}

    spec = SpringSpec(calc["wire_diameter_mm"], calc["mean_diameter_mm"],
                      calc["height_mm"], calc["turns"], calc["clockwise"])
    builder = PartBuilder(out_path, material=material)
    builder.helix_spring("coil", wire_diameter=spec.wire_diameter_mm,
                         mean_diameter=spec.mean_diameter_mm, height=spec.height_mm,
                         turns=spec.turns, clockwise=spec.clockwise)
    result = builder.build(keep_open=False)
    check = (result.spring_checks or {}).get("coil") or {}
    return {
        "ok": bool(result.ok),
        "task_verified": bool(result.ok and check.get("ok")),
        "path": result.path,
        "output_semantics": "geometry_only",
        "native_history": False,
        "spec": spec.to_dict(),
        "model": describe(spec),
        "calculated": {k: (round(v, 4) if isinstance(v, float) else v)
                       for k, v in calc.items()},
        "bodies": result.bodies,
        "volume_mm3": round(result.volume_mm3, 3),
        "mass_kg": round(result.mass_kg, 6),
        "material_requested": result.material_requested,
        "material_applied": result.material_applied,
        "volume_check": check,
        "limitations": [
            "社区版交付无建模历史实体，不提供原生螺旋/扫掠特征或命名驱动尺寸；改参数请另存重新生成",
            "等螺距、开放端；端圈未并紧、未磨平",
            "中心线高度不等于实体自由高度（自由高度见 volume_check.bounds.expected_mm 第三轴）",
            "未验证刚度、压并高度、疲劳寿命或制造标准",
        ],
        "error": result.error or None,
    }
