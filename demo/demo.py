# -*- coding: utf-8 -*-
"""B 站演示脚本 —— 分步执行，每步停下等你按 Enter。

为什么要分步
------------
录屏时你需要在每一步之间切镜头、讲两句、拖一下 SolidWorks 窗口。
一口气跑完没法解说，所以这个脚本在每一步结束时**停下来**，
把「屏幕上应该看到什么」「旁白该说什么」打印出来，你按 Enter 才继续。

用法
----
    python demo/demo.py              # 交互模式（推荐，录制用）
    python demo/demo.py --auto       # 自动跑完，不暂停（自己先看效果用）
    python demo/demo.py --step 3     # 只跑第 3 步

前置
----
    SolidWorks 已手动启动，主窗口可见，没有打开其他文档。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = os.path.join(ROOT, "demo", "out")




# ---------------------------------------------------------------- 安全取值
def _val(obj, name, default=None):
    """pywin32 会把无参 COM 方法暴露成属性，这里统一处理两种情况。"""
    try:
        v = getattr(obj, name, default)
        if v is default:
            return default
        return v() if callable(v) else v
    except Exception:
        return default


# ---------------------------------------------------------------- 演示工具
class Step:
    def __init__(self, idx, title, narration, expect):
        self.idx = idx
        self.title = title
        self.narration = narration
        self.expect = expect


def _hr(ch="=", n=72):
    print(ch * n)


def _banner(idx, total, title):
    print()
    _hr()
    print(f"  第 {idx}/{total} 步 · {title}")
    _hr()


def _pause(step: Step, auto: bool):
    """停下，把该念的旁白和该看到的画面打出来。"""
    print()
    print("  " + "-" * 68)
    print("  【屏幕上应该看到】")
    for line in step.expect:
        print(f"      {line}")
    if step.narration:
        print()
        print("  【旁白可以这么说】")
        for line in step.narration:
            print(f"      “{line}”")
    print("  " + "-" * 68)
    if auto:
        print("  （--auto 模式，继续）")
        time.sleep(1.0)
        return
    print()
    try:
        input("  ▶ 准备好后按 Enter 继续 ... ")
    except (EOFError, KeyboardInterrupt):
        print("\n  已中止")
        sys.exit(0)




def _reset_docs(verbose=True):
    """关掉所有已打开文档。

    为什么要清场：SolidWorks 默认只允许 8 个文档同时打开（swforge 的资源守卫
    也按这个数拦）。演示要连跑 6 步，不清场第 3 步就会撞上限，
    表现是 build() 返回 ok=False 但完全不报错 —— 录屏时最怕这个。
    """
    from swforge import resource_status
    from swforge.session import _value

    try:
        sw = get_session_sw()
        docs = _value(sw, "GetDocuments") or []
        for d in docs:
            try:
                path = str(_value(d, "GetPathName") or "")
                if path:
                    sw.CloseDoc(path)
            except Exception:
                continue
        left = resource_status()["document_count"]
        if verbose:
            print(f"  （清场：关闭 {len(docs)} 个文档，剩 {left} 个）")
    except Exception as exc:
        if verbose:
            print(f"  （清场失败：{type(exc).__name__}，继续）")


def get_session_sw():
    from swforge import get_session
    return get_session().sw()


# ---------------------------------------------------------------- 步骤实现
def step_1_env(auto):
    """环境自检：连接 SolidWorks、读版本、读资源状态"""
    from swforge import get_session, resource_status

    _banner(1, 6, "环境自检 —— 证明这不是录屏造假")
    sw = get_session().sw()
    rev = _val(sw, "RevisionNumber", "未知")
    st = resource_status()
    print(f"  SolidWorks 版本 : {rev}")
    print(f"  已打开文档      : {st['document_count']} / {st['limit']}")
    print(f"  资源等级        : {st['level']}")
    return Step(1, "环境自检", [
        "这不是演示视频专用的假数据，是真实连着本机 SolidWorks。",
        "版本号、文档数都是现场读的。",
    ], [
        "命令行里打印出 SolidWorks 版本号和资源状态",
        "旁边开着 SolidWorks 主窗口（空的）",
    ])


def step_2_model(auto):
    """建模：底板 + 方管立柱 + 通孔，并自动分色"""
    from swforge import PartBuilder

    _banner(2, 6, "建模 —— 底板 + 立柱 + 通孔，自动分色")
    path = os.path.join(OUT, "01_支架.SLDPRT")
    t0 = time.monotonic()

    b = PartBuilder(path, material="Q235")
    b.box("底板", 0, 160, 0, 20, 0, 100, "steel")
    b.tube_y("立柱", 20, 140, 60, 0, 40, 40, wall=6, color="yellow")
    b.cylinder("通孔", axis="y", x=80, y=20, z=50, r=8, h=20, color="gray")

    r = b.build()
    dt = time.monotonic() - t0

    print(f"  文件      : {path}")
    print(f"  成功      : {r.ok}")
    print(f"  实体数    : {r.bodies}")
    print(f"  体积      : {r.volume_mm3:,.0f} mm³")
    print(f"  质量      : {r.mass_kg:.3f} kg")
    print(f"  材质已赋  : {r.material_applied}")
    print(f"  耗时      : {dt:.2f} 秒")
    return Step(2, "建模 + 分色", [
        "三行代码，出来一个带分色的零件，6 个实体。",
        "注意质量 3.3 公斤左右 —— 这是真实钢的密度算出来的，不是水。",
        "配色是写到每一个面上的，不是整体刷一个颜色。",
    ], [
        "SolidWorks 里出现一个零件：灰色底板 + 黄色方管 + 灰色孔",
        "命令行打印：实体数 6、体积、质量约 3.3 kg",
        "模型树里有 10 个以上特征",
    ])


def step_3_material(auto):
    """材质：证明 GB 牌号真的赋进去了"""
    from swforge import GB_MATERIALS

    _banner(3, 6, "GB 材质 —— 20 个国标牌号，密度是真的")
    print("  内置牌号（部分）:")
    for name in list(GB_MATERIALS)[:8]:
        dens = GB_MATERIALS[name][0]
        print(f"      {name:<14} 密度 {dens:,.0f} kg/m³")
    print()
    print("  对照: 如果材质没赋上，SolidWorks 默认密度是 1,000 kg/m³（水）")
    print("        底板 160×20×100 = 320,000 mm³")
    print(f"        按钢算 : 320,000 × 7.85e-6 = {320000*7.85e-6:.3f} kg")
    print(f"        按水算 : 320,000 × 1.00e-6 = {320000*1.00e-6:.3f} kg")
    print("        —— 差 7.85 倍")
    return Step(3, "GB 材质", [
        "这是这个项目最早发现的一个坑：material='Q235' 传进去了，",
        "但 SolidWorks 根本没赋值，质量是按水的密度算的，错了 7.85 倍。",
        "现在有 20 个国标牌号，会自动部署到 SolidWorks 的材质扫描目录。",
    ], [
        "命令行列出 GB 牌号和密度",
        "SolidWorks 左侧材质栏显示 Q235",
        "质量属性和命令行打印的数值一致",
    ])


def step_4_drawing(auto):
    """出图：GB 图框 + 标题栏 + 自动尺寸 + 总尺寸"""
    from swforge import produce, add_dimensions, normalize_layout, export_pdf

    _banner(4, 6, "出工程图 —— GB 图框 + 标题栏 + 自动尺寸 + 总尺寸")
    model = os.path.join(OUT, "01_支架.SLDPRT")
    dwg = os.path.join(OUT, "01_支架.SLDDRW")
    pdf = os.path.join(OUT, "01_支架.pdf")
    t0 = time.monotonic()

    r1 = produce(model, dwg, paper="A3")
    print(f"  出图      : {r1.get('ok')}   模板: {os.path.basename(str(r1.get('template', '?')))}")

    r2 = add_dimensions(dwg, overall=True)
    print(f"  自动尺寸  : {r2.get('after')} 个")
    ov = r2.get("overall") or {}
    if ov.get("dims"):
        print("  总尺寸    :")
        for d in ov["dims"][:4]:
            k = "horizontal" if d.get("horizontal") else "vertical"
            if d.get(k) == "ok":
                print(f"      {d['view']:<14} {k:<10} {d['value']} mm")

    lay = normalize_layout(dwg)
    print(f"  排版      : ok={lay.get('ok')}  比例={lay.get('scale')}")

    pdf_ok = export_pdf(dwg, pdf).get("ok")
    print(f"  PDF       : {pdf_ok}  -> {pdf}")
    print(f"  耗时      : {time.monotonic()-t0:.1f} 秒")
    return Step(4, "出工程图", [
        "出了张 A3 图，带 GB 图框、标题栏、材料、重量、比例。",
        "尺寸是自动标的，包括总长 160 和总高 140。",
        "三视图按长对正、高平齐摆的，不是随手拖的。",
    ], [
        "SolidWorks 里出现 A3 图纸，有 A~F / 1~8 图框",
        "右下角标题栏：材料 Q235、重量 3.281 kg、比例 1:2",
        "三个视图上有尺寸，主视能看到 160 和 140",
        "命令行打印 PDF 导出成功",
    ])


def step_5_assembly(auto):
    """装配 + 配合：销被同心配合拉进孔里"""
    from swforge import PartBuilder, AssemblyBuilder, MateBuilder

    _banner(5, 6, "装配 + 配合 —— 同心配合把销自动拉进孔")
    tube = os.path.join(OUT, "02_管.SLDPRT")
    pin = os.path.join(OUT, "03_销.SLDPRT")
    asm = os.path.join(OUT, "04_总装.SLDASM")

    b = PartBuilder(tube, material="Q235")
    b.revolve("管", [(8, 0), (20, 0), (20, 30), (8, 30)], axis="y", color="steel")
    print(f"  管       : {b.build(keep_open=False).ok}")

    b2 = PartBuilder(pin, material="Q235")
    b2.cylinder("销", axis="y", x=0, y=0, z=0, r=8, h=40, color="yellow")
    print(f"  销       : {b2.build(keep_open=False).ok}")

    a = AssemblyBuilder(asm)
    a.add(tube, 0, 0, 0, fixed=True)
    a.add(pin, 60, 0, 0)          # 故意放到 60 mm 外
    print(f"  装配     : {a.build().get('ok')}   （销故意放在 X=60 mm）")

    before = MateBuilder(asm).apply()
    x_before = [float(c["x"]) for c in before.get("component_boxes_center_mm", [])]
    print(f"  配合前 X : {x_before}")

    res = MateBuilder(asm).concentric(0, 1).apply()
    x_after = [float(c["x"]) for c in res.get("component_boxes_center_mm", [])]
    print(f"  配合结果 : ok={res.get('ok')}")
    for m in res.get("mates", []):
        print(f"      {m.get('op'):<12} result={m.get('result')}  {m.get('how', '')}")
    print(f"  配合后 X : {x_after}   ← 销被拉到 0")
    return Step(5, "装配 + 配合", [
        "销本来放在 60 毫米外，和孔不同轴。",
        "加一个同心配合，工具自动找到两个等径圆柱面，",
        "销直接被拉到 0 —— 同轴了。",
    ], [
        "SolidWorks 里出现装配体：管 + 销",
        "命令行打印 配合前 X = [..., 60.0]",
        "命令行打印 配合后 X = [..., 0.0]",
        "SolidWorks 模型树里出现「配合」文件夹",
    ])


def step_6_interference(auto):
    """干涉：精确算出重叠体积"""
    from swforge import PartBuilder
    from swforge.interference import body_interference

    _banner(6, 6, "干涉检测 —— 精确到立方毫米")
    print("  造两个 10×10×10 的方块，重叠 5 mm：")
    print("      理论重叠体积 = 10 × 10 × 5 = 500 mm³")
    print()
    cases = [("重叠 5 mm", 5, 15, 500.0), ("分开 20 mm", 20, 30, 0.0), ("刚好接触", 10, 20, 0.0)]
    for tag, bx0, bx1, expect in cases:
        p = os.path.join(OUT, f"05_干涉_{tag.replace(' ', '')}.SLDPRT")
        b = PartBuilder(p, material="Q235")
        b.box("A", 0, 10, 0, 10, 0, 10, "steel")
        b.box("B", bx0, bx1, 0, 10, 0, 10, "yellow")
        b.build(paint=False, keep_open=False)
        r = body_interference(p)
        got = r.get("interference_volume_mm3", 0)
        mark = "OK" if abs(got - expect) < 1.0 else "差异!"
        print(f"      {tag:<12} 实测 {got:>8.3f} mm³   期望 {expect:>6.1f}   {mark}")
    print()
    print("  注意: 装配级干涉 API 在这台机器上对 500 mm³ 重叠返回 0，不可用。")
    print("        所以走的是零件级布尔求交。")
    return Step(6, "干涉检测", [
        "干涉检测最怕报个「有干涉」但说不清多少。",
        "这里直接算重叠体积，500 立方毫米，精确到小数点后三位。",
        "分开和刚好接触都判 0，不会误报。",
    ], [
        "命令行三行结果：500.000 / 0.000 / 0.000",
        "SolidWorks 里开着对应的零件",
    ])


STEPS = [step_1_env, step_2_model, step_3_material, step_4_drawing,
         step_5_assembly, step_6_interference]


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="B 站演示脚本")
    ap.add_argument("--auto", action="store_true", help="自动跑完，不暂停")
    ap.add_argument("--step", type=int, default=0, help="只跑第 N 步")
    ap.add_argument("--keep", action="store_true", help="保留上次输出（默认清空）")
    args = ap.parse_args()

    if not args.keep and os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)

    print()
    _hr()
    print("  swforge 功能演示")
    print("  https://github.com/mwdandoms/swforge")
    _hr()
    print("  前置：SolidWorks 已启动，主窗口可见，没有其他文档")
    print(f"  输出：{OUT}")
    if not args.auto:
        print()
        input("  按 Enter 开始 ... ")

    total = len(STEPS)
    for i, fn in enumerate(STEPS, 1):
        if args.step and i != args.step:
            continue
        if i > 1:                       # 第 1 步是自检，不动文档
            _reset_docs(verbose=True)
        t0 = time.monotonic()
        step = fn(args.auto)
        print(f"\n  本步耗时: {time.monotonic()-t0:.1f} 秒")
        _pause(step, args.auto)

    print()
    _hr()
    print("  演示结束")
    _hr()
    print(f"  产物都在: {OUT}")
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f"      {f:<32} {os.path.getsize(p)/1024:>8.1f} KB")
    print()


if __name__ == "__main__":
    main()
