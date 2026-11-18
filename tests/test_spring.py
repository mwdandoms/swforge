# -*- coding: utf-8 -*-
"""弹簧（受限几何）回归测试。

分两类：
- 纯算术与校验（不需要 SolidWorks）
- 实机建模（标记 ``sw``，用 ``-m "not sw"`` 排除）

弹簧是 swforge 第一个「复合特征」（螺旋线 + 扫掠），校验纪律比单步特征更严：
解析体积 0.5% + B-Rep 极值外廓 0.2%，两道都过才算成功。
"""
import math
import os

import pytest

from swforge.spring import (
    SpringSpec,
    create_spring,
    describe,
    expected_bounds_mm,
    validate,
    verify,
    verify_bounds,
)

# 基准件：线径 2 / 中径 20 / 中心线高 60 / 8 圈
BASE = SpringSpec(wire_diameter_mm=2, mean_diameter_mm=20, height_mm=60, turns=8)


# ── 校验：合法输入 ──────────────────────────────────────────────────────
def test_valid_spec_returns_analytic_values():
    c = validate(BASE)
    assert c["pitch_mm"] == pytest.approx(7.5)                 # 60 / 8
    assert c["circumference_mm"] == pytest.approx(math.pi * 20)
    assert c["centerline_length_mm"] == pytest.approx(math.hypot(math.pi * 20 * 8, 60))
    assert c["ideal_volume_mm3"] == pytest.approx(
        math.pi * 1.0 ** 2 * math.hypot(math.pi * 20 * 8, 60))


def test_analytic_values_match_closed_form():
    """体积 = 线截面 × 中心线长度，必须严格等于闭式解。"""
    c = validate(SpringSpec(3, 25, 80, 10))
    wire, mean, height, turns = 3, 25, 80, 10
    length = math.hypot(math.pi * mean * turns, height)
    assert c["centerline_length_mm"] == pytest.approx(length, rel=1e-12)
    assert c["ideal_volume_mm3"] == pytest.approx(
        math.pi * (wire / 2) ** 2 * length, rel=1e-12)


def test_clockwise_defaults_to_left_hand():
    assert SpringSpec(2, 20, 60, 8).clockwise is False
    assert validate(BASE)["clockwise"] is False


# ── 校验：拒绝非法输入 ──────────────────────────────────────────────────
@pytest.mark.parametrize("spec,fragment", [
    (SpringSpec(2, 20, 60, 0), "圈数"),
    (SpringSpec(2, 20, 60, 25), "圈数"),
    (SpringSpec(0.05, 20, 60, 8), "线径"),
    (SpringSpec(60, 200, 60, 8), "线径"),
    (SpringSpec(5, 10, 60, 8), "中径"),                       # 中径 < 4×线径
    (SpringSpec(2, 600, 60, 8), "中径"),
    (SpringSpec(2, 20, 3000, 8), "高度"),
    (SpringSpec(2, 20, 10, 8), "螺距"),                        # 螺距 < 1.25d
    (SpringSpec(2, 20, 200, 2), "螺距"),                       # 螺距 > 0.5D
])
def test_invalid_specs_are_rejected_with_reason(spec, fragment):
    with pytest.raises(ValueError) as exc:
        validate(spec)
    assert fragment in str(exc.value), f"报错应点名「{fragment}」，实际：{exc.value}"


@pytest.mark.parametrize("field", ["wire_diameter_mm", "mean_diameter_mm",
                                   "height_mm", "turns"])
def test_bool_is_not_accepted_as_number(field):
    """bool 是 int 的子类；不挡住的话 True 会被当成 1 用。"""
    kw = dict(wire_diameter_mm=2, mean_diameter_mm=20, height_mm=60, turns=8)
    kw[field] = True
    with pytest.raises(ValueError) as exc:
        validate(SpringSpec(**kw))
    assert "布尔" in str(exc.value)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0, None, "abc"])
def test_non_finite_and_non_positive_rejected(bad):
    with pytest.raises(ValueError):
        validate(SpringSpec(bad, 20, 60, 8))


def test_numeric_string_is_coerced():
    """数字字符串按 Python 惯例强制转换（"2" → 2.0）；非数字字符串才报错。"""
    assert validate(SpringSpec("2", 20, 60, 8))["wire_diameter_mm"] == 2.0
    with pytest.raises(ValueError) as exc:
        validate(SpringSpec("abc", 20, 60, 8))
    assert "有限正数" in str(exc.value)


# ── 外廓 ────────────────────────────────────────────────────────────────
def test_expected_bounds_shape_and_order():
    c = validate(BASE)
    b = expected_bounds_mm(c)
    assert len(b) == 3
    assert b == sorted(b), "外廓应为升序，便于与实测逐项比较"
    # 两轴径向 = 中径 + 线径
    assert b[0] == pytest.approx(22.0) and b[1] == pytest.approx(22.0)
    # 轴向 = 中心线高 + 端部圆截面倾斜超出量，必然大于中心线高度
    assert b[2] > 60.0


def test_axial_bound_grows_with_pitch():
    """螺距越大，端部圆截面越倾斜，轴向外廓超出越多。"""
    tight = validate(SpringSpec(2, 20, 40, 8))     # 螺距 5
    loose = validate(SpringSpec(2, 20, 70, 8))     # 螺距 8.75
    assert expected_bounds_mm(loose)[2] > expected_bounds_mm(tight)[2]


# ── 校验函数本身 ────────────────────────────────────────────────────────
def test_volume_verify_passes_on_close_value():
    c = validate(BASE)
    v = verify(c["ideal_volume_mm3"] * 1.001, c)
    assert v["ok"] and v["deviation_pct"] < 0.2


def test_volume_verify_fails_on_wrong_value():
    c = validate(BASE)
    v = verify(c["ideal_volume_mm3"] * 1.05, c)      # 偏 5%，超 0.5% 容差
    assert not v["ok"]
    assert "偏差" in v["reason"]


def test_bounds_verify_passes_on_exact():
    c = validate(BASE)
    v = verify_bounds(expected_bounds_mm(c), expected_bounds_mm(c))
    assert v["ok"] and v["reason"] is None


def test_bounds_verify_fails_on_swapped_or_wrong():
    c = validate(BASE)
    want = expected_bounds_mm(c)
    bad = [want[0], want[1], want[2] + 5.0]
    v = verify_bounds(bad, want)
    assert not v["ok"]
    assert "外廓不符" in v["reason"]


def test_bounds_verify_handles_missing_measurement():
    c = validate(BASE)
    v = verify_bounds(None, expected_bounds_mm(c))
    assert not v["ok"] and "没有实测外廓" in v["reason"]


def test_bounds_verify_handles_wrong_arity():
    v = verify_bounds([1.0, 2.0], [1.0, 2.0, 3.0])
    assert not v["ok"] and "3 个分量" in v["reason"]


# ── 入口函数的前置拒绝（不连 SolidWorks）─────────────────────────────────
def test_create_spring_rejects_wrong_extension(tmp_path):
    r = create_spring(str(tmp_path / "x.step"), wire_diameter=2,
                      mean_diameter=20, height=60, turns=8)
    assert not r["ok"] and ".SLDPRT" in r["error"]


def test_create_spring_refuses_to_overwrite(tmp_path):
    target = tmp_path / "exists.SLDPRT"
    target.write_bytes(b"x")
    r = create_spring(str(target), wire_diameter=2, mean_diameter=20,
                      height=60, turns=8)
    assert not r["ok"] and "已存在" in r["error"]


def test_create_spring_rejects_out_of_range_before_touching_sw(tmp_path):
    r = create_spring(str(tmp_path / "bad.SLDPRT"), wire_diameter=5,
                      mean_diameter=10, height=60, turns=8)
    assert not r["ok"]
    assert "受限几何" in r["error"]
    assert not (tmp_path / "bad.SLDPRT").exists(), "参数被拒时不应产生文件"


def test_describe_mentions_handedness():
    assert "右旋" in describe(SpringSpec(2, 20, 60, 8, clockwise=True))
    assert "左旋" in describe(SpringSpec(2, 20, 60, 8, clockwise=False))


# ── 实机 ────────────────────────────────────────────────────────────────
@pytest.mark.sw
def test_live_spring_double_verification(tmp_path):
    """实机：体积与外廓两道校验都要过。"""
    out = tmp_path / "live_spring.SLDPRT"
    r = create_spring(str(out), wire_diameter=2, mean_diameter=20,
                      height=60, turns=8, clockwise=True, material="65Mn")
    assert r["ok"], r.get("error")
    assert r["bodies"] == 1
    chk = r["volume_check"]
    assert chk["deviation_pct"] < 0.5
    assert chk["bounds"]["ok"], chk["bounds"].get("reason")
    assert r["material_applied"] == "65Mn"
    assert out.is_file()
