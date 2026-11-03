# -*- coding: utf-8 -*-
"""v0.5 诚实性回归测试 —— 防止把「检查执行成功」误报成「可制造」。

这些用例不连接 SolidWorks 也能跑大部分；涉及 produce 的用 skip 保护。
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_drawing_result_never_claims_manufacturable():
    """任何出图结果都不能声称 ready_for_manufacture=True。"""
    from dsh_sw_toolkit import drawing

    src = inspect.getsource(drawing)
    # 允许显式写 False，禁止写 True
    assert 'ready_for_manufacture=False' in src or '"ready_for_manufacture":False' in src \
        or "'ready_for_manufacture':False" in src or 'ready_for_manufacture":False' in src
    assert 'ready_for_manufacture=True' not in src
    assert "ready_for_manufacture\": True" not in src


def test_material_unknown_is_reported_not_silent():
    """材质库里没有的牌号，不能假装赋上了。"""
    from dsh_sw_toolkit.gb_materials import lookup

    assert lookup("Q235") is not None
    assert lookup("q235") is not None
    assert lookup("这不是一个牌号") is None
    assert lookup("") is None


def test_gb_material_densities_are_sane():
    """GB 牌号密度必须是工程合理值，不能是 1000（水）这种默认值。"""
    from dsh_sw_toolkit.gb_materials import GB_MATERIALS

    assert len(GB_MATERIALS) >= 15
    for name, (density, elastic, poisson, note) in GB_MATERIALS.items():
        assert 1000 < density < 20000, f"{name} 密度 {density} 不合理"
        assert 1e9 < elastic < 1e12, f"{name} 弹性模量 {elastic} 不合理"
        assert 0 < poisson < 0.5, f"{name} 泊松比 {poisson} 不合理"
        assert note, f"{name} 缺少说明"


def test_material_library_path_is_in_sw_scan_dir():
    """材质库必须落在 SW 会扫描的目录，否则赋值静默失败。"""
    from dsh_sw_toolkit.gb_materials import _sw_user_material_dirs, library_path

    dirs = _sw_user_material_dirs()
    path = library_path()
    if dirs:
        assert any(os.path.normcase(path).startswith(os.path.normcase(d))
                   for d in dirs), f"材质库 {path} 不在 SW 扫描目录 {dirs} 内"
    else:
        assert "dsh-sw-toolkit" in path.lower()