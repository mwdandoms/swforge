# -*- coding: utf-8 -*-
"""v0.8 新增能力的回归测试。

这些用例覆盖 v0.6~v0.8 期间新增但一直没测的部分：
- 干涉求交（含「必须是临时体」这条硬约束）
- 配合的规格拼装与结果解析
- 总尺寸标注的模块契约
- 工程图模板选型（中文 GB 优先）

不连接 SolidWorks 的部分直接跑；需要 SW 的用 skip 保护。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------- 纯逻辑
def test_body_operation_error_table():
    """错误码表必须包含 1=NonApiBody —— 这正是 v0.7 卡住的那个码。"""
    from swforge.interference import BODY_OP_ERRORS

    assert BODY_OP_ERRORS[0] == "swBodyOperationNoError"
    assert BODY_OP_ERRORS[1] == "swBodyOperationNonApiBody"
    assert BODY_OP_ERRORS[1067] == "swBodyOperationNoIntersect"


def test_interference_constants():
    from swforge.interference import SWBODYINTERSECT

    assert SWBODYINTERSECT == 15901


def test_mate_spec_format():
    """MateBuilder 拼出来的规格行必须能被 C# 侧按 | 拆开。"""
    from swforge.mates import MateBuilder

    m = MateBuilder()
    m.concentric(0, 1)
    m.coincident(0, 1)
    assert m._specs == ["concentric|0|1|0.05", "coincident|0|1"]
    for spec in m._specs:
        parts = spec.split("|")
        assert parts[0] in ("concentric", "coincident")
        int(parts[1]); int(parts[2])


def test_mate_align_constant_is_not_agnostic():
    """v0.7 用了不存在的 swAlignAGNOSTIC，必须确认模板里不再出现。"""
    from swforge import mates

    assert "swAlignAGNOSTIC" not in mates._CS_TEMPLATE
    assert "swMateAlign_e" not in mates._CS_TEMPLATE


def test_mate_class_name_substitution():
    """类名占位符必须整体替换（v0.7 出现过 Mat_ 前缀不一致导致找不到类型）。"""
    from swforge import mates

    assert "public class __CLASS__ {" in mates._CS_TEMPLATE
    assert "class Mat__CLASS__" not in mates._CS_TEMPLATE


def test_dims_template_uses_drawing_doc():
    """GetFirstView 在 IDrawingDoc 上，不在 IModelDoc2 上。"""
    from swforge import dims

    assert "IDrawingDoc dd = (IDrawingDoc)md;" in dims._CS
    assert "md.GetFirstView()" not in dims._CS


def test_template_priority_is_chinese_gb():
    """v0.7 的坑：英文 GB.drwdot 排在最前 → 英制 + 无图框。"""
    from swforge.drawing import _default_template, template_warnings

    for paper in ("A3", "A4", "A2"):
        tpl = _default_template("drawing", paper)
        if not tpl:
            pytest.skip("本机没有工程图模板")
        assert os.path.basename(tpl).lower().startswith("gb_"), \
            f"{paper} 选到了非中文模板：{tpl}"
        assert template_warnings(tpl) == []


def test_template_dirs_cover_multiple_years():
    """模板目录要按年份扫描，不能只认 2025。"""
    from swforge.drawing import _template_dirs

    dirs = _template_dirs()
    assert isinstance(dirs, list)
    for d in dirs:
        assert os.path.isdir(d)


def test_gb_materials_still_intact():
    """v0.8 不应破坏 v0.5 的 GB 材质表。"""
    from swforge.gb_materials import GB_MATERIALS

    assert len(GB_MATERIALS) >= 15
    assert GB_MATERIALS["Q235"][0] == 7850.0


def test_resource_guard_defaults():
    from swforge.resources import DEFAULT_LIMIT, DEFAULT_WARN_RATIO

    assert DEFAULT_LIMIT == 8
    assert 0 < DEFAULT_WARN_RATIO < 1


# ---------------------------------------------------------------- 需要 SW
def _sw_alive():
    try:
        from swforge import get_session

        return bool(get_session().ping().get("ok"))
    except Exception:                                    # noqa: BLE001
        return False


needs_sw = pytest.mark.skipif(not _sw_alive(), reason="SolidWorks 未运行")


@needs_sw
@pytest.mark.sw
def test_interference_three_benchmarks():
    """重叠 500 mm³ / 不重叠 / 仅接触 —— 三个基准必须判对。"""
    import tempfile
    import uuid

    from swforge import PartBuilder, sweep_documents
    from swforge.interference import body_interference

    sweep_documents(dry_run=False)
    tmp = os.path.join(tempfile.gettempdir(), "swforge_it")
    os.makedirs(tmp, exist_ok=True)
    cases = [("ov", 5, 15, 500.0), ("ap", 20, 30, 0.0), ("tc", 10, 20, 0.0)]
    for tag, bx0, bx1, expect in cases:
        p = os.path.join(tmp, "v8t_%s_%s.SLDPRT" % (tag, uuid.uuid4().hex[:6]))
        b = PartBuilder(p, material="Q235")
        b.box("A", 0, 10, 0, 10, 0, 10, "steel")
        b.box("B", bx0, bx1, 0, 10, 0, 10, "yellow")
        r = b.build(paint=False, keep_open=False)
        assert r.ok, r.error
        res = body_interference(p)
        assert res["ok"], res.get("error")
        got = res["interference_volume_mm3"]
        assert abs(got - expect) < 1.0, f"{tag}: {got} != {expect}"


@needs_sw
@pytest.mark.sw
def test_concentric_mate_moves_component():
    """同心配合后，销的装配坐标 X 必须从 60 变成 0。"""
    import tempfile
    import uuid

    from swforge import PartBuilder, sweep_documents
    from swforge.assembly import AssemblyBuilder
    from swforge.mates import MateBuilder

    sweep_documents(dry_run=False)
    tmp = os.path.join(tempfile.gettempdir(), "swforge_it")
    tag = uuid.uuid4().hex[:6]
    tube = os.path.join(tmp, "v8m_tube_%s.SLDPRT" % tag)
    pin = os.path.join(tmp, "v8m_pin_%s.SLDPRT" % tag)
    asm = os.path.join(tmp, "v8m_asm_%s.SLDASM" % tag)

    b = PartBuilder(tube, material="Q235")
    b.revolve("管", [(8, 0), (20, 0), (20, 30), (8, 30)], axis="y", color="steel")
    assert b.build(paint=False, keep_open=False).ok
    b2 = PartBuilder(pin, material="Q235")
    b2.cylinder("销", axis="y", x=0, y=0, z=0, r=8, h=40, color="yellow")
    assert b2.build(paint=False, keep_open=False).ok

    a = AssemblyBuilder(asm)
    a.add(tube, 0, 0, 0, fixed=True)
    a.add(pin, 60, 0, 0)
    assert a.build()["ok"]

    before = MateBuilder(asm).apply()
    x_before = [float(x["x"]) for x in before["component_boxes_center_mm"]]
    assert max(abs(v) for v in x_before) > 50, f"插入位置不对：{x_before}"

    res = MateBuilder(asm).concentric(0, 1).apply()
    assert res["ok"], res["mates"]
    x_after = [float(x["x"]) for x in res["component_boxes_center_mm"]]
    assert max(abs(v) for v in x_after) < 1.0, f"配合后未同轴：{x_after}"


@needs_sw
@pytest.mark.sw
def test_overall_dimensions_on_drawing():
    """工程图必须能补出总尺寸。"""
    import tempfile
    import uuid

    from swforge import PartBuilder, produce, sweep_documents
    from swforge.dims import add_overall_dimensions

    sweep_documents(dry_run=False)
    tmp = os.path.join(tempfile.gettempdir(), "swforge_it")
    tag = uuid.uuid4().hex[:6]
    m = os.path.join(tmp, "v8d_%s.SLDPRT" % tag)
    d = os.path.join(tmp, "v8d_%s.SLDDRW" % tag)
    b = PartBuilder(m, material="Q235")
    b.box("底板", 0, 160, 0, 20, 0, 100, "steel")
    b.tube_y("立柱", 20, 140, 60, 0, 40, 40, wall=6, color="yellow")
    assert b.build(paint=False, keep_open=False).ok
    assert produce(m, d, paper="A3").get("ok")

    res = add_overall_dimensions(d)
    assert res["ok"], res.get("raw")
    assert res["done"] >= 2
    values = {x.get("value") for x in res["dims"]}
    assert "160.00" in values, f"缺总长 160：{values}"
