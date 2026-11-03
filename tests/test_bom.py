# -*- coding: utf-8 -*-
"""BOM 纯逻辑测试 —— 不需要 SolidWorks。

能离线测的部分（分组、导出）先测掉，实机部分留给 selftest 和实机测试。
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from swforge.bom import (  # noqa: E402
    bom_to_csv,
    bom_to_markdown,
    group_components,
)


def comp(name, path, material="", suppressed=False):
    return {"name": name, "path": path, "material": material,
            "suppressed": suppressed}


# ---------------------------------------------------------------- 合并逻辑
def test_same_part_merges_and_counts():
    """同一个零件装 3 次必须合并成一行，数量 3。

    这是 BOM 最容易写错的地方：列成 3 行同一个垫片是没用的，
    车间要的是「垫片 ×3」。
    """
    rows = group_components([
        comp("垫片-1", r"C:\p\垫片.SLDPRT", "Q235"),
        comp("垫片-2", r"C:\p\垫片.SLDPRT", "Q235"),
        comp("垫片-3", r"C:\p\垫片.SLDPRT", "Q235"),
    ])
    assert len(rows) == 1
    assert rows[0]["qty"] == 3
    assert rows[0]["material"] == "Q235"


def test_different_parts_stay_separate():
    rows = group_components([
        comp("底板", r"C:\p\底板.SLDPRT", "Q235"),
        comp("立柱", r"C:\p\立柱.SLDPRT", "Q235"),
    ])
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {"底板", "立柱"}
    assert all(r["qty"] == 1 for r in rows)


def test_path_comparison_ignores_case_and_separators():
    """Windows 路径大小写不敏感，同一个文件不能算成两个零件。"""
    rows = group_components([
        comp("A", r"C:\Parts\Plate.SLDPRT"),
        comp("B", r"c:\parts\plate.SLDPRT"),
    ])
    assert len(rows) == 1, "同一路径的不同大小写被当成两个零件了"
    assert rows[0]["qty"] == 2


def test_suppressed_components_are_excluded():
    """压缩的组件不出现在图纸上，列进 BOM 会误导。"""
    rows = group_components([
        comp("在用", r"C:\p\a.SLDPRT"),
        comp("压缩", r"C:\p\b.SLDPRT", suppressed=True),
    ])
    assert len(rows) == 1
    assert rows[0]["name"] == "在用"


def test_missing_material_marked_not_blank():
    """没材料要显式写「未指定」，不能留空。

    留空的话看图的人会以为材料就是空，而实际后果是
    SolidWorks 退回水的密度，质量错 7.85 倍。
    """
    rows = group_components([comp("x", r"C:\p\x.SLDPRT", "")])
    assert rows[0]["material"] == "未指定"


def test_empty_input_is_safe():
    assert group_components([]) == []
    assert group_components(None) == []


def test_component_without_path_is_skipped():
    """路径为空的组件没法判重，直接跳过比瞎猜好。"""
    rows = group_components([comp("幽灵", ""), comp("正常", r"C:\p\a.SLDPRT")])
    assert len(rows) == 1
    assert rows[0]["name"] == "正常"


def test_sequence_numbers_are_dense():
    """序号必须从 1 连续，中间不能跳号——跳号意味着有行被吞了。"""
    rows = group_components([
        comp("a", r"C:\p\a.SLDPRT"),
        comp("b", r"C:\p\b.SLDPRT"),
        comp("c", r"C:\p\c.SLDPRT"),
    ])
    assert [r["seq"] for r in rows] == [1, 2, 3]


def test_material_taken_from_first_non_empty():
    """同一零件的不同实例里，材料只在一个上有值时要取到那个。"""
    rows = group_components([
        comp("a-1", r"C:\p\a.SLDPRT", ""),
        comp("a-2", r"C:\p\a.SLDPRT", "45"),
    ])
    assert rows[0]["material"] == "45"


# ---------------------------------------------------------------- 导出
def test_markdown_export_shape():
    rows = group_components([
        comp("底板", r"C:\p\底板.SLDPRT", "Q235"),
        comp("垫片", r"C:\p\垫片.SLDPRT", "Q235"),
        comp("垫片", r"C:\p\垫片.SLDPRT", "Q235"),
    ])
    md = bom_to_markdown(rows)
    assert "| 序号 | 名称 | 数量 | 材料 |" in md
    assert "| 1 | 底板 | 1 | Q235 |" in md
    assert "| 2 | 垫片 | 2 | Q235 |" in md


def test_csv_has_utf8_bom_for_excel(tmp_path):
    """CSV 必须带 BOM，否则 Excel 打开中文是乱码。

    这是国内用户最先撞上的问题，不是可选项。
    """
    rows = group_components([comp("中文零件", r"C:\p\中文.SLDPRT", "Q235")])
    p = tmp_path / "bom.csv"
    bom_to_csv(rows, str(p))

    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "CSV 没有 UTF-8 BOM，Excel 会乱码"

    text = raw.decode("utf-8-sig")
    assert "中文零件" in text
    assert "序号" in text


def test_csv_roundtrip(tmp_path):
    import csv
    rows = group_components([comp("底板", r"C:\p\底板.SLDPRT", "Q235")])
    p = tmp_path / "bom.csv"
    bom_to_csv(rows, str(p))
    with open(p, encoding="utf-8-sig", newline="") as fh:
        got = list(csv.reader(fh))
    assert got[0] == ["序号", "名称", "数量", "材料", "路径"]
    assert got[1][1] == "底板"
    assert got[1][3] == "Q235"

# ---------------------------------------------------------------- 排除规则
def test_include_suppressed_optin_works():
    """include_suppressed=True 时必须把压缩件也算进来。

    这个参数之前是死的（两个分支传的参数一模一样），
    等于悄悄忽略了调用方的意图。测试守住它。
    """
    comps = [
        comp("在用", r"C:\p\a.SLDPRT"),
        comp("压缩", r"C:\p\b.SLDPRT", suppressed=True),
    ]
    only_visible = group_components(comps)
    with_all = group_components(comps, include_suppressed=True)
    assert len(only_visible) == 1
    assert len(with_all) == 2, "include_suppressed=True 没生效"
    assert {r["name"] for r in with_all} == {"在用", "压缩"}


def test_exclude_from_bom_is_respected():
    """SolidWorks 允许把组件标成「从明细表排除」，这是用户明确意图，必须尊重。"""
    rows = group_components([
        {**comp("正常", r"C:\p\a.SLDPRT"), "exclude_from_bom": False},
        {**comp("排除", r"C:\p\b.SLDPRT"), "exclude_from_bom": True},
    ])
    assert len(rows) == 1
    assert rows[0]["name"] == "正常"


def test_exclude_wins_over_include_suppressed():
    """即使要求包含压缩件，标了「从明细表排除」的也不能进来。"""
    rows = group_components([
        {**comp("排除", r"C:\p\b.SLDPRT", suppressed=True), "exclude_from_bom": True},
        comp("正常", r"C:\p\a.SLDPRT"),
    ], include_suppressed=True)
    assert len(rows) == 1
    assert rows[0]["name"] == "正常"
