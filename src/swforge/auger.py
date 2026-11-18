"""Geometry and public entry point for a single-start, constant-pitch auger flight."""
import math

from ._native_features import scalar


def flight_geometry(inner_diameter, outer_diameter, pitch, turns, thickness, clockwise):
    """Validate in mm and derive the midsurface area and normal-offset solid volume."""
    inner = scalar(inner_diameter, "inner_diameter", True)
    outer = scalar(outer_diameter, "outer_diameter", True)
    pitch = scalar(pitch, "pitch", True)
    turns = scalar(turns, "turns", True)
    thickness = scalar(thickness, "thickness", True)
    if type(clockwise) is not bool:
        raise ValueError("clockwise must be boolean")
    r, R = inner/2, outer/2
    height = pitch*turns
    if not 1 <= turns <= 5 or not 10 <= pitch <= 500 or height > 1500:
        raise ValueError("use 1–5 turns, 10–500 mm pitch and at most 1500 mm rise")
    if r < 5 or R-r < 3 or outer > 600:
        raise ValueError("inner diameter must be at least 10 mm, radial width at least 3 mm, outer diameter at most 600 mm")
    if not .2 <= thickness <= min(pitch/8, r/4, (R-r)/3):
        raise ValueError("thickness must be at least 0.2 mm and at most min(pitch/8, inner radius/4, width/3)")
    k = pitch/(2*math.pi)

    def area_primitive(x):
        return .5*(x*math.hypot(x,k)+k*k*math.asinh(x/k))

    # Integrate the normal-offset Jacobian 1 + K*z² over the total thickness.
    angle = 2*math.pi*turns
    area = angle*(area_primitive(R)-area_primitive(r))
    curvature = -angle*(R/math.hypot(R,k)-r/math.hypot(r,k))
    volume = area*thickness+curvature*thickness**3/12
    radial_span = 2*math.hypot(R, thickness/2*k/math.hypot(R,k))
    axial_span = height+thickness*R/math.hypot(R,k)
    return dict(inner_diameter_mm=inner, outer_diameter_mm=outer, pitch_mm=pitch, turns=turns,
                thickness_mm=thickness, rise_mm=height, clockwise=clockwise,
                area_mm2=area, volume_mm3=volume, spans_mm=[radial_span,axial_span,radial_span])


def create_auger_flight(out_path, *, inner_diameter, outer_diameter, pitch, turns, thickness,
                        clockwise=True, material="Q235", keep_open=False, max_documents=8):
    """Generate a constant-pitch flight; Community saves geometry without native history."""
    from .modeling import PartBuilder
    try:
        b = PartBuilder(out_path, material=material)
        b.auger_flight("flight", inner_diameter=inner_diameter, outer_diameter=outer_diameter,
                       pitch=pitch, turns=turns, thickness=thickness, clockwise=clockwise)
        result = b.build(keep_open=keep_open, max_documents=max_documents)
        check = (result.auger_checks or {}).get("flight", {})
        return dict(result.__dict__, task_verified=bool(result.ok and check.get("ok")))
    except (TypeError, ValueError) as exc:
        return {"ok":False,"error":str(exc)}
