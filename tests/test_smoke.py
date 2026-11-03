# -*- coding: utf-8 -*-
"""冒烟测试：不需要 SolidWorks 的部分。跑：

    python -m pytest tests -q
    # 或者
    python tests/test_smoke.py
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_import():
    import dsh_sw_toolkit as t
    assert t.__version__
    assert "PartBuilder" in t.__all__


def test_colors_mapping():
    from dsh_sw_toolkit.modeling import COLORS, Material
    assert COLORS["yellow"] == Material.YELLOW
    assert len(Material.SILVER) == 3


def test_builder_rejects_bad_box():
    from dsh_sw_toolkit.modeling import PartBuilder
    b = PartBuilder(os.path.join(tempfile.gettempdir(), "x.SLDPRT"))
    try:
        b.box("坏", 10, 10, 0, 5, 0, 5)
    except ValueError:
        pass
    else:
        raise AssertionError("应当对零尺寸抛 ValueError")


def test_builder_counts():
    from dsh_sw_toolkit.modeling import PartBuilder
    b = PartBuilder(os.path.join(tempfile.gettempdir(), "y.SLDPRT"))
    b.box("底", 0, 100, 0, 10, 0, 100)
    b.tube_y("柱", 10, 500, 0, 0, 50, 50, wall=5)     # 4 块板
    b.tube_x("梁", -100, 100, 500, 0, 60, 60, wall=5)  # 4 块板
    assert b.box_count == 1 + 4 + 4


def test_codegen_contains_calls():
    from dsh_sw_toolkit.modeling import PartBuilder
    b = PartBuilder(r"C:\tmp\z.SLDPRT")
    b.box("底板", 0, 10, 0, 10, 0, 10, "steel")
    cs = b.render_cs()
    assert "class Bld_" in cs
    assert "FeatureExtrusion3" in cs
    assert "底板" in cs


def test_rule_matching():
    from dsh_sw_toolkit.colors import FaceRule
    box = {"x0": -10, "x1": 10, "y0": 0, "y1": 20, "z0": -10, "z1": 10}
    assert FaceRule("a", (0, 0, 0), ymax_lt=30).matches(box, 0.0)
    assert not FaceRule("b", (0, 0, 0), ymax_lt=10).matches(box, 0.0)
    assert FaceRule("c", (0, 0, 0), normal_y_gt=0.8).matches(box, 0.95)
    assert not FaceRule("d", (0, 0, 0), normal_y_gt=0.8).matches(box, 0.1)
    assert FaceRule("e", (0, 0, 0), size_lt=100).matches(box, 0.0)


def test_atlas_without_solidworks():
    from dsh_sw_toolkit.drawing import make_atlas
    out = os.path.join(tempfile.gettempdir(), "atlas_test.pdf")
    r = make_atlas(
        [
            {"type": "cover", "title": "测试图集"},
            {"type": "text", "title": "一、说明",
             "lines": ["■ 标题", "正文第一行", "正文第二行"]},
        ],
        out, title="测试图集", subtitle="冒烟测试",
        cover_items=[("项目", "值")],
    )
    assert r["ok"] and os.path.isfile(out) and r["pages"] == 2


if __name__ == "__main__":
    ok = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                ok += 1
            except Exception as exc:                     # noqa: BLE001
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{ok} passed")
    raise SystemExit(0 if ok >= 7 else 1)
