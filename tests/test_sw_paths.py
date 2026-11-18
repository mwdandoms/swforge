# -*- coding: utf-8 -*-
"""跨版本路径回归：任何写死 SolidWorks 年份的地方都要被拦住。

背景：1.7.0 起 library.py 退回成写死 ``F:\\sw基础材料库`` + ``SOLIDWORKS 2025``，
客户机器上没有这两个路径就索引到 0 个型材轮廓；session/startup 也只探到 2022/2025。
本测试锁住「按年份生成、不写死」这条规则。
"""
import io
import os
import re

import pytest

import swforge
from swforge import library, session, startup

SRC = os.path.dirname(os.path.abspath(swforge.__file__))


# ── 素材库 ────────────────────────────────────────────────────────────────
def test_library_default_roots_is_probed_not_hardcoded():
    """DEFAULT_ROOTS 必须是探测结果（list），且 1.6.1 的自动探测函数要在。"""
    assert callable(library._default_roots)
    assert isinstance(library.DEFAULT_ROOTS, (list, tuple))
    assert library.LIBRARY_DIR_NAMES, "素材库候选命名不能为空"


def test_library_roots_honour_environment_override(tmp_path, monkeypatch):
    """环境变量指定的目录必须排在探测结果里（客户素材库放哪里都要能用）。"""
    lib = tmp_path / "我的型材库"
    lib.mkdir()
    monkeypatch.setenv("SWFORGE_LIBRARY", str(lib))
    roots = library._default_roots()
    assert str(lib) in roots


def test_library_roots_only_return_existing_dirs():
    """探测结果里的每一项都必须真实存在，否则调用方会白扫。"""
    for r in library._default_roots():
        assert os.path.isdir(r), r


# ── 启动器 ────────────────────────────────────────────────────────────────
def test_sw_years_cover_2024_and_2026():
    assert 2019 in startup.SW_YEARS
    assert 2026 in startup.SW_YEARS
    assert 2024 in startup.SW_YEARS
    assert 2025 in startup.SW_YEARS
    assert list(startup.SW_YEARS) == sorted(set(startup.SW_YEARS), reverse=True)


@pytest.mark.parametrize("year", [2024, 2025, 2026])
def test_common_paths_include_each_year(year):
    """COMMON_PATHS 必须按年份生成，不能只有 2025。"""
    assert any(f"SW{year}" in p for p in startup.COMMON_PATHS), \
        f"COMMON_PATHS 缺少 SW{year}"


def test_find_exe_returns_tuple_without_crashing():
    """找不到也不能抛异常，调用方靠返回值判断。"""
    path, source = startup.find_exe("Z:\\definitely\\not\\here\\SLDWORKS.exe")
    assert isinstance(path, (str, type(None)))
    assert isinstance(source, str)


# ── 会话层 ────────────────────────────────────────────────────────────────
def test_sw_install_dirs_probes_years_beyond_2022():
    """安装目录探测必须覆盖 2020~2026（1.9.0 只列到 2022）。"""
    dirs = session._sw_install_dirs()
    assert isinstance(dirs, list) and dirs
    years = {int(m.group(1)) for d in dirs for m in [re.search(r"SW(20\d\d)", d)] if m}
    if years:                       # 取决于是否走到盘符分支
        assert years <= set(range(2019, 2027)), years
        assert max(years) >= 2024, years


# ── 源码级守卫 ────────────────────────────────────────────────────────────
@ pytest.mark.parametrize("filename", [
    "library.py", "session.py", "startup.py", "drawing.py"])
def test_no_hardcoded_sw_year_in_code(filename):
    """这 4 个文件里不能再出现写死的 SW20xx / 'SOLIDWORKS 20xx' 路径字面量。

    注释和文档串里提到版本是允许的（那是在记录实测环境）。
    """
    path = os.path.join(SRC, filename)
    offenders = []
    for i, line in enumerate(io.open(path, encoding="utf-8").read().splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        if not re.search(r"SW20\d\d|SOLIDWORKS 20\d\d", line):
            continue
        if 'r"' in line or "append" in line or 'f"' in line:
            offenders.append(f"{filename}:{i}  {s[:90]}")
    assert not offenders, "写死年份：\n" + "\n".join(offenders)


def test_explicit_version_rejects_another_server(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from swforge import sw_target

    sw2019 = tmp_path / "2019" / "SLDWORKS.exe"
    sw2025 = tmp_path / "2025" / "SLDWORKS.exe"
    sw2019.parent.mkdir()
    sw2025.parent.mkdir()
    for exe in (sw2019, sw2025):
        exe.touch()
        (exe.parent / sw_target._INTEROP).touch()
    monkeypatch.setenv("SWFORGE_SW_YEAR", "2019")
    monkeypatch.setenv("SW_INSTALL_DIR", str(sw2025.parent))
    monkeypatch.setattr(sw_target, "registered_exe", lambda year=None: {2019: sw2019, 2025: sw2025}[year])
    assert sw_target.install_dir() == str(sw2019.parent)
    assert sw_target.progid(sw_target.selected_year()) == "SldWorks.Application.27"
    with pytest.raises(RuntimeError, match="2019.*33"):
        sw_target.verify_revision(SimpleNamespace(RevisionNumber="33.5.0"), 2019)


def test_2019_selects_native_a4_templates(monkeypatch, tmp_path):
    from swforge.gb_styles import gb_template_path
    from swforge.assembly import _default_asm_template

    monkeypatch.setenv("SWFORGE_SW_YEAR", "2019")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.delenv("SW_TEMPLATE_DIR", raising=False)
    root = tmp_path / "SOLIDWORKS"
    target = root / "SOLIDWORKS 2019" / "templates"
    target.mkdir(parents=True)
    for name in ("gb_a4.drwdot", "gb_a4p.drwdot", "gb_assembly.asmdot"):
        (target / name).touch()
    with pytest.raises(ValueError):
        gb_template_path("A4L")  # Community retains 1.7 paper choices
    assert gb_template_path("A4") == str(target / "gb_a4p.drwdot")
    assert _default_asm_template() == str(target / "gb_assembly.asmdot")
    with pytest.raises(FileNotFoundError):
        gb_template_path("A3")
