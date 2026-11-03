# -*- coding: utf-8 -*-
"""集成测试 —— 需要 SolidWorks 在运行。

跑法：
    pytest tests -m sw            # 只跑需要 SW 的
    pytest tests -m "not sw"      # 只跑纯逻辑（CI 用）
    pytest tests                  # 全跑

没有 SW 时这些用例会 skip，不会失败。
临时文件用随机后缀，避免被上次运行残留的 SW 文档锁住。
"""

import os
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytestmark = pytest.mark.sw


def _tmp(name):
    d = os.path.join(tempfile.gettempdir(), "swforge_it")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s_%s.SLDPRT" % (name, uuid.uuid4().hex[:8]))


def _sw_alive():
    try:
        from swforge import get_session
        return bool(get_session().ping().get("ok"))
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_live_sw():
    # Collection must never start SW (including pytest -m 'not sw').
    if os.environ.get("SWFORGE_LIVE") != "1":
        pytest.skip("设置 SWFORGE_LIVE=1 后运行实机测试")
    if not _sw_alive():
        pytest.fail("已要求实机验证，但 SolidWorks 无法连接")


_needs_sw = pytest.mark.sw


@_needs_sw
def test_ping_roundtrip():
    from swforge import get_session
    r = get_session().ping()
    assert r["ok"] is True
    assert r["roundtrip_ms"] > 0


@_needs_sw
def test_build_three_bodies():
    """建 3 个形体，校验实体数与文件落盘。"""
    from swforge import PartBuilder
    out = _tmp("三体")
    b = PartBuilder(out)
    b.box("底", 0, 100, 0, 10, 0, 100, "steel")
    b.box("中", 10, 90, 10, 20, 10, 90, "yellow")
    b.box("顶", 20, 80, 20, 30, 20, 80, "brown")
    r = b.build()
    assert r.ok, r.error
    assert r.features_ok == 3
    assert r.features_failed == 0
    assert os.path.isfile(out)


@_needs_sw
def test_build_paint_coverage():
    """v0.2 关键指标：配色覆盖率必须 >= 99%。"""
    from swforge import PartBuilder
    out = _tmp("配色")
    b = PartBuilder(out)
    b.box("底板", -150, 150, 0, 12, -100, 100, "steel")
    for i, (cx, cz) in enumerate([(-100, -60), (100, -60), (-100, 60), (100, 60)]):
        b.tube_y("立柱%d" % (i + 1), 12, 812, cx, cz, 40, 40, wall=4.0, color="yellow")
    b.tube_x("横梁", -130, 130, 800, 0, 60, 60, wall=5.0, color="brown")
    r = b.build()
    assert r.ok, r.error
    assert r.color_coverage >= 0.99, "配色覆盖率只有 %.1f%%" % (r.color_coverage * 100)
    assert r.color_faces > 0


@_needs_sw
def test_survey_after_build():
    from swforge import PartBuilder, survey
    out = _tmp("体检")
    b = PartBuilder(out)
    b.box("体", 0, 50, 0, 50, 0, 50, "silver")
    b.build()
    s = survey()
    assert s["ok"] is True
    assert s["solid_bodies"] >= 1
    assert s["envelope_mm"]["x"][2] > 0


@_needs_sw
def test_apply_colors_and_readback():
    from swforge import FaceRule, PartBuilder, apply_rules, read_back
    out = _tmp("分色")
    b = PartBuilder(out)
    b.box("底", 0, 100, 0, 10, 0, 100, "steel")
    b.box("上", 0, 100, 10, 200, 0, 100, "yellow")
    b.build()
    r = apply_rules(out, [
        FaceRule("上半", (0.16, 0.70, 0.34), ymin_gt=100),
        FaceRule("底板", (0.62, 0.66, 0.72), ymax_lt=20),
    ])
    assert r["ok"] is True
    assert r["written"] > 0
    assert r["failed"] == 0
    faces = read_back(sample=8)
    assert any(f["rgb"] for f in faces), "回读全是 None，说明颜色没生效"


@_needs_sw
def test_purge_dry_run_does_not_delete():
    """dry-run 绝不能真的删体。

    这条用例在 v0.2 开发中抓出过 swAllBodies = -1（当时误写成 2）
    导致 purge_* 一直遍历 0 个实体的 bug。
    """
    from swforge import PartBuilder, get_session, survey
    from swforge.cleanup import purge_giant
    out = _tmp("清理")
    b = PartBuilder(out)
    b.box("大", 0, 8000, 0, 100, 0, 100, "gray")
    b.box("小", 0, 50, 0, 50, 0, 50, "silver")
    r0 = b.build()
    assert r0.ok, r0.error
    before = survey()["total_bodies"]
    assert before >= 2, "实体数 %d，说明 GetBodies2 参数错了" % before
    md = get_session().sw().ActiveDoc
    r = purge_giant(md, threshold_mm=5000, dry_run=True)
    assert r["dry_run"] is True
    assert len(r["candidates"]) >= 1, "没找到 8000 mm 的体，阈值或类型常量有误"
    after = survey()["total_bodies"]
    assert after == before, "dry-run 竟然删了体"
