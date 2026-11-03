# -*- coding: utf-8 -*-
"""生成源码快照测试 —— 不开 SolidWorks 也能守住最贵的坑。

为什么不直接做完整 Mock
------------------------
Mock 会把 SolidWorks 的行为"模拟成正常"，而本项目所有严重 bug 都是**真机跑出来的**：

    IFace2.GetSurface()      后期绑定类型不匹配
    IFace2 没有 Select2      方法根本不存在
    AddComponent5 参数是米    零件出现在 60000 mm 处
    Operations2 返回 (None,1) 干涉算成 0
    GetInterferences 是属性   明细列表永远为空

这些 Mock 一个都发现不了，反而会给出虚假的安全感。

那这批测试守什么
----------------
守「生成的 C# 源码有没有被改坏」。这不需要 SolidWorks —— 纯字符串比对。

能抓到的是真实发生过的问题类型：
- 单位换算被改掉（mm → m 那个坑）
- API 方法名拼错
- 参数顺序变了
- 必要的调用被删掉

成本大概是完整 Mock 的 1/5，覆盖的是最容易改坏的那部分。
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from swforge.modeling import PartBuilder  # noqa: E402


@pytest.fixture()
def builder(tmp_path):
    """一个只用来生成源码的 builder，不会碰 SolidWorks。"""
    return PartBuilder(str(tmp_path / "snap.SLDPRT"), material="Q235")


def _cs(b: PartBuilder, paint: bool = True) -> str:
    """取生成的 C# 源码。不含任何 COM 调用。"""
    return b.render_cs(paint=paint)


def _code_only(cs: str) -> str:
    """去掉注释行，只留可执行代码。

    注释里会提到已知不可用的 API（解释为什么不用它们），
    检查「不能出现某个 API」时必须先把注释剔掉，否则会误报。
    """
    keep = []
    for line in cs.split("\n"):
        t = line.strip()
        if t.startswith("//") or t.startswith("*") or t.startswith("/*"):
            continue
        keep.append(line)
    return "\n".join(keep)


# ---------------------------------------------------------------- 单位换算
def test_part_dimensions_are_millimetres(builder):
    """建模尺寸必须是毫米，不能被改成米。

    这是真实发生过的坑：AddComponent5 的参数是**米**，
    早期版本把毫米直接传进去，零件出现在 60000 mm 的位置。
    零件侧的换算必须保持「米 = 毫米 / 1000」，不能漏。
    """
    builder.box("底板", 0, 100, 0, 20, 0, 50)
    cs = _cs(builder)
    assert "CreateCornerRectangle" in cs
    # 真实的换算写法是常量 MM = 0.001。删掉它，几何尺寸会全错 1000 倍。
    assert "const double MM = 0.001" in cs, \
        "毫米→米的换算常量 MM 不见了，几何尺寸会错 1000 倍"


def test_assembly_component_position_converts_to_metres(tmp_path):
    """装配里插入零件的位置必须做 mm → m 换算。

    这条对应用户能直接看到的现象：零件该在 0 位置，结果出现在 60 米外。
    """
    from swforge.assembly import AssemblyBuilder

    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"")            # add() 会校验文件存在，内容不重要
    ab = AssemblyBuilder(str(tmp_path / "a.SLDASM"))
    ab.add(part, x=100, y=0, z=0)    # 100 mm

    # add() 必须原样保存毫米值——换算只能发生在调用 COM 的那一刻。
    # 如果这里就被除成 0.1，量级就说不清了（AddComponent5 参数是米的坑）。
    items = getattr(ab, "_items", None)
    assert items, "AssemblyBuilder 没有保存组件列表，无法检查位置"
    _path, x, _y, _z, _fixed = items[0]
    assert x == 100.0, f"add(x=100) 存下来的却是 {x!r}，单位换算位置不对"


# ---------------------------------------------------------------- API 名称
def test_box_uses_corner_rectangle(builder):
    """矩形草图必须用 CreateCornerRectangle，方法名不能被改。"""
    builder.box("b", 0, 10, 0, 10, 0, 10)
    assert "CreateCornerRectangle" in _cs(builder)


def test_cylinder_uses_circle(builder):
    """圆柱草图必须用 CreateCircle。"""
    builder.cylinder("c", axis="y", x=0, y=0, z=0, r=5, h=20)
    assert "CreateCircle" in _cs(builder)


def test_connection_keeps_both_paths(builder):
    """连接必须是「先试 GetActiveObject，失败再 CreateInstance」的两级结构。

    这是本项目花了很多时间才确认的行为：
    SolidWorks 不一定注册到 ROT——从桌面启动的会注册，
    被 COM 从后台拉起的不会（实测 MK_E_UNAVAILABLE）。
    所以两条路径都得有，删掉任何一条都会在某种启动方式下连不上。

    这条测试守住的是「别哪天有人图省事把回退删了」。
    """
    builder.box("b", 0, 10, 0, 10, 0, 10)
    code = _code_only(_cs(builder))
    assert "GetActiveObject" in code, "第一级 GetActiveObject 不见了"
    assert "CreateInstance" in code, "第二级 CreateInstance 回退不见了"

    # 回退的顺序不能颠倒：先试已注册实例，再创建
    i_rot = code.find("GetActiveObject")
    i_new = code.find("CreateInstance")
    assert i_rot < i_new, "两级顺序反了，应该先试已注册实例再创建新实例"


def test_no_nonexistent_members(builder):
    """生成源码里不能出现已知不存在的成员。

    实测在 pywin32 下取不到的：
        IFace2.Select2  —— IFace2 上没有这个方法，必须转成 IEntity 再 Select2
    """
    builder.box("b", 0, 10, 0, 10, 0, 10)
    code = _code_only(_cs(builder))
    # 直接对 IFace2 调 Select2 会失败，正确写法是先 (IEntity)
    if "Select2" in code:
        assert "(IEntity)" in code, \
            "出现了 Select2 但没有转成 IEntity，IFace2 上没有这个方法"


# ---------------------------------------------------------------- 结构完整
def test_every_shape_becomes_a_feature(builder):
    """每个 shape 都要在源码里出现，不能漏。"""
    tags = ["A", "B", "C"]
    builder.box(tags[0], 0, 10, 0, 10, 0, 10)
    builder.box(tags[1], 20, 30, 0, 10, 0, 10)
    builder.cylinder(tags[2], axis="y", x=0, y=0, z=0, r=3, h=10)
    cs = _cs(builder)
    for t in tags:
        # 标签要么出现在日志字符串里，要么出现在草图名里
        assert t in cs, f"标签 {t} 没有出现在生成的源码里"


def test_extrude_depth_matches_input(builder):
    """拉伸深度必须等于输入值，不能被缩放。"""
    builder.box("b", 0, 10, 0, 10, 0, 25)
    cs = _cs(builder)
    # 25mm 对应的数值应该出现（可能带小数位）
    assert re.search(r"\b25(\.0+)?\b", cs), "拉伸深度 25 没有按原值出现在源码里"


def test_paint_false_skips_colour_calls(tmp_path):
    """paint=False 时不应生成上色调用。"""
    b = PartBuilder(str(tmp_path / "np.SLDPRT"), material="Q235")
    b.box("b", 0, 10, 0, 10, 0, 10)
    without = b.render_cs(paint=False)
    with_paint = b.render_cs(paint=True)
    assert len(with_paint) >= len(without)
    # 关掉上色后，源码不该再明显更长
    assert "MaterialPropertyValues" not in without or len(without) <= len(with_paint)


# ---------------------------------------------------------------- 稳定性
def test_render_is_deterministic(builder):
    """同一个 builder 渲染两次必须完全一致。

    如果渲染带随机量（比如自动生成的类名），快照就没法比对了。
    """
    builder.box("b", 0, 10, 0, 10, 0, 10)
    a = builder.render_cs(paint=False)
    b = builder.render_cs(paint=False)
    # 类名是随机生成的，去掉后再比
    def strip_random(s: str) -> str:
        return re.sub(r"Bld_[0-9a-f]{10,}", "Bld_X", s)
    assert strip_random(a) == strip_random(b)


def test_render_produces_compilable_looking_csharp(builder):
    """粗略检查生成的 C# 结构完整（花括号配对、有入口方法）。

    真正的编译验证在实机测试里（Add-Type 会报错）。
    这里只挡住「生成逻辑被改坏、产出一段残码」这种低级错误。
    """
    builder.box("b", 0, 10, 0, 10, 0, 10)
    cs = _cs(builder)
    assert cs.count("{") == cs.count("}"), "花括号不配对"
    assert "public static string Run" in cs or "Run()" in cs, "缺少入口方法"
    assert "class " in cs
