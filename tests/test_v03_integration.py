"""Opt-in real SW2025 verification, including independent geometric measurements.

DSH_SW_LIVE=1 python -m pytest tests -m sw
DSH_SW_EVIDENCE optionally retains models and measurement JSON outside pytest tmp.
"""
import json
import math
import os
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
pytestmark = pytest.mark.sw


def value(obj, name):
    result = getattr(obj, name)
    return result() if callable(result) else result


@pytest.fixture
def live(tmp_path):
    if os.environ.get("DSH_SW_LIVE") != "1":
        pytest.skip("设置 DSH_SW_LIVE=1 后运行实机测试")
    from dsh_sw_toolkit import get_session
    session = get_session()
    assert session.ping()["ok"]
    out = Path(os.environ.get("DSH_SW_EVIDENCE", tmp_path))
    out.mkdir(parents=True, exist_ok=True)
    return session.sw(), out


def measure(md):
    bodies = md.GetBodies2(0, False) or []
    bounds = [list(value(b, "GetBodyBox")) for b in bodies]
    bbox = ([min(b[i] for b in bounds) * 1000 for i in range(3)] +
            [max(b[i] for b in bounds) * 1000 for i in range(3, 6)]) if bounds else []
    # Official IBody2.GetMassProperties: index 3 is volume in cubic metres.
    volume = sum(b.GetMassProperties(1.0)[3] for b in bodies) * 1e9
    return {"body_count": len(bodies), "bbox_mm": bbox, "volume_mm3": volume}


def build_measured(live, name, populate, expected_bodies=1):
    from dsh_sw_toolkit import PartBuilder
    sw, out = live
    path = out / f"{name}_{uuid.uuid4().hex[:6]}.SLDPRT"
    builder = PartBuilder(str(path))
    populate(builder)
    result = builder.build()
    report = dict(result.__dict__)
    if result.ok:
        report["measured"] = measure(sw.ActiveDoc)
    path.with_suffix(".verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result.ok, result.error + "\n" + result.log
    assert result.features_failed == 0
    assert result.bodies == expected_bodies
    assert report["measured"]["body_count"] == expected_bodies
    assert result.color_coverage >= 0.99, result.paint_error
    assert not result.paint_error
    return builder, result, report["measured"]


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_cylinder_axis_negative_start_volume(live, axis):
    _, _, measured = build_measured(live, f"cylinder_{axis}", lambda b:
        b.cylinder("轴", axis=axis, x=-40, y=-30, z=25, r=7, h=32, color="blue"))
    low, high = [-47, -37, 18], [-33, -23, 32]
    index = "xyz".index(axis)
    low[index] = [-40, -30, 25][index]
    high[index] = low[index] + 32
    assert measured["bbox_mm"] == pytest.approx(low + high, abs=0.08)
    assert measured["volume_mm3"] == pytest.approx(math.pi * 7**2 * 32, rel=1e-6)


def test_revolve_hollow_ring_volume(live):
    _, _, measured = build_measured(live, "revolve_ring", lambda b:
        b.revolve("环", [(8, 0), (18, 0), (18, 12), (8, 12)],
                  x=20, y=-15, z=35, color="yellow"))
    assert measured["bbox_mm"] == pytest.approx([2, -15, 17, 38, -3, 53], abs=0.08)
    assert measured["volume_mm3"] == pytest.approx(math.pi * (18**2 - 8**2) * 12, rel=1e-6)


def test_partial_revolve_volume(live):
    _, _, measured = build_measured(live, "revolve_half", lambda b:
        b.revolve("半环", [(5, 0), (15, 0), (15, 10), (5, 10)], angle=180, color="blue"))
    assert measured["volume_mm3"] == pytest.approx(math.pi * (15**2 - 5**2) * 10 / 2, rel=1e-6)


@pytest.mark.parametrize("operation", ["fillet", "chamfer"])
def test_edge_finishing_reduces_volume(live, operation):
    def populate(b):
        b.box("block", 0, 40, 0, 30, 0, 25, color="green")
        getattr(b, operation)("block", 2)
    _, result, measured = build_measured(live, operation, populate)
    assert result.features_ok == 2
    assert 0 < measured["volume_mm3"] < 40 * 30 * 25


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_tube_true_length_and_open_section(live, axis):
    def populate(b):
        if axis == "x":
            b.tube_x("tube", -20, 80, 0, 0, 30, 40, wall=3)
        elif axis == "y":
            b.tube_y("tube", -20, 80, 0, 0, 30, 40, wall=3)
        else:
            b.tube_z("tube", -20, 80, 0, 0, 30, 40, wall=3)
    _, _, measured = build_measured(live, f"tube_{axis}", populate, expected_bodies=4)
    assert measured["volume_mm3"] == pytest.approx((30 * 40 - 24 * 34) * 100, rel=1e-6)
    i = "xyz".index(axis)
    assert measured["bbox_mm"][i] == pytest.approx(-20, abs=0.08)
    assert measured["bbox_mm"][i + 3] == pytest.approx(80, abs=0.08)


def test_asymmetric_box_coordinates(live):
    _, _, measured = build_measured(live, "negative_box", lambda b:
        b.box("定位块", -23, 37, -12, 18, 11, 43, "orange"))
    assert measured["bbox_mm"] == pytest.approx([-23, -12, 11, 37, 18, 43], abs=0.08)
    assert measured["volume_mm3"] == pytest.approx(60 * 30 * 32, rel=1e-6)


def test_merge_reports_actual_body_count(live):
    def populate(b):
        b.merge = True
        b.box("base", 0, 40, 0, 20, 0, 30, "steel")
        b.box("overlap", 10, 30, 10, 40, 5, 25, "steel")
    _, result, measured = build_measured(live, "merged", populate)
    assert result.features_ok == 2
    assert measured["volume_mm3"] == pytest.approx(40 * 20 * 30 + 20 * 20 * 20, rel=1e-6)


def test_cleanup_default_preview_and_actual_count(live):
    from dsh_sw_toolkit import purge_giant
    sw, _ = live
    def populate(b):
        b.box("giant", 0, 8000, 0, 10, 0, 10, "gray")
        b.box("keep", -30, -10, 0, 10, 0, 10, "green")
    build_measured(live, "cleanup_v03", populate, expected_bodies=2)
    md = sw.ActiveDoc
    preview = purge_giant(md, threshold_mm=5000)
    assert preview["dry_run"] is True
    assert len(preview["candidates"]) == 1
    assert measure(md)["body_count"] == 2
    applied = purge_giant(md, threshold_mm=5000, dry_run=False)
    assert applied["ok"], applied
    assert measure(md)["body_count"] == 1


def test_colors_target_saved_path_and_persist(live):
    from dsh_sw_toolkit import FaceRule, apply_rules, read_back
    sw, _ = live
    _, first, _ = build_measured(live, "color_target", lambda b:
        b.box("target", 0, 10, 0, 10, 0, 10, "red"))
    _, second, _ = build_measured(live, "color_bystander", lambda b:
        b.box("other", 0, 10, 0, 10, 0, 10, "blue"))
    green = (0.16, 0.70, 0.34)
    changed = apply_rules(first.path, [FaceRule("all", green)])
    assert changed["ok"], json.dumps(changed, ensure_ascii=False)
    assert changed["written"] == 6
    assert all(f["rgb"] == pytest.approx(green, abs=1/255 + 1e-9)
               for f in read_back(first.path, sample=6))
    blue = (0.52, 0.74, 0.90)
    assert all(f["rgb"] == pytest.approx(blue, abs=1/255 + 1e-9)
               for f in read_back(second.path, sample=6))
    # Reopen the target from disk: appearance must survive the save.
    sw.CloseDoc(first.path)
    import pythoncom
    from win32com.client import VARIANT
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    assert sw.OpenDoc6(first.path, 1, 1, "", err, warn) is not None
    assert all(f["rgb"] == pytest.approx(green, abs=1/255 + 1e-9)
               for f in read_back(first.path, sample=6))
