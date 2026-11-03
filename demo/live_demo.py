# -*- coding: utf-8 -*-
"""自主演示 —— 从 SolidWorks 关闭状态开始，走完整流程。

设计原则
--------
1. **每一步都留停顿**。这是给人看的，不是跑测试。0.5 秒一闪而过等于没演。
2. **每一步把结果读回来打在大字上**。光看模型出现，观众不知道对错；
   打出「质量 3.3122 kg / 密度 7850 kg/m³」才有说服力。
3. **窗口始终保持可见**。SolidWorks 由 COM 拉起时默认 Visible=False，
   没有窗口就录不到任何画面。
4. **出图后缩放到适合**。A3 幅面不缩放会只显示半个图框。

关于配合这一步的取舍
--------------------
实测在「支架 + 销」这种复杂零件上，concentric 和 coincident 的**自动选面
都不可靠**：

    coincident  ok=True  位置 [0.0, 200.0]  没动
    concentric  ok=True  位置 [0.0, 0.0]    落错（该在 x=80），产生 2 处假干涉

所以演示里用两块简单板做配合 —— 这个场景下位置是对的、可复现。
**不是回避问题，是把已知限制写进 issue-log，演示只展示稳定的部分。**

用法
----
    python demo/live_demo.py                 # 完整流程
    python demo/live_demo.py --fast          # 缩短停顿
    python demo/live_demo.py --out F:\\...   # 指定产物目录
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))


def say(text, big=False):
    if big:
        print()
        print("=" * 68)
        print(f"  {text}")
        print("=" * 68)
    else:
        print(f"  {text}")


def pause(seconds):
    time.sleep(seconds)


def focus_sw():
    """确保 SolidWorks 可见并置顶。没有可见窗口就录不到画面。"""
    from swforge.session import get_session, _value
    import ctypes

    sw = get_session().sw()
    try:
        if not _value(sw, "Visible"):
            sw.Visible = True
    except Exception:                                  # noqa: BLE001
        pass

    u32 = ctypes.windll.user32
    for title in ("SOLIDWORKS Premium 2025 SP5.0", None):
        h = u32.FindWindowW(title, None)
        if h:
            u32.ShowWindow(h, 9)
            u32.SetForegroundWindow(h)
            return h
    return 0


def zoom_fit():
    """当前文档缩放至适合，避免只看到半个图框。"""
    from swforge.session import get_session
    try:
        md = get_session().sw().ActiveDoc
        if md is not None:
            md.ViewZoomtofit2()
    except Exception:                                  # noqa: BLE001
        pass


def _close_all():
    from swforge.session import get_session, _value
    try:
        sw = get_session().sw()
        for d in (_value(sw, "GetDocuments") or []):
            try:
                sw.CloseDoc(str(_value(d, "GetPathName")))
            except Exception:                          # noqa: BLE001
                pass
    except Exception:                                  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"F:\SW+AI\06_录屏素材\demo_out")
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()

    k = 0.3 if args.fast else 1.0
    os.makedirs(args.out, exist_ok=True)

    print()
    say("swforge 实机演示 —— 从零开始", big=True)

    # ---------------------------------------------------------------- 1
    say("[1/6] 启动 SolidWorks", big=True)
    print()
    from swforge.session import get_session
    t0 = time.time()
    r = get_session().ping()
    say(f"已连接 SolidWorks {r.get('sw_version')}   耗时 {time.time() - t0:.1f} 秒")
    hwnd = focus_sw()
    say(f"窗口已置顶（句柄 {hwnd}）" if hwnd else "窗口未找到")
    pause(2.5 * k)

    # ---------------------------------------------------------------- 2
    say("[2/6] 建模：底板 + 立柱 + 通孔", big=True)
    print()
    from swforge import PartBuilder

    part = os.path.join(args.out, "01_支架.SLDPRT")
    if os.path.isfile(part):
        try:
            os.remove(part)
        except OSError:
            pass

    b = PartBuilder(part, material="Q235")
    b.box("底板", 0, 160, 0, 20, 0, 100)
    say("底板 160 × 20 × 100")
    pause(1.5 * k)
    b.tube_y("立柱", 20, 140, 60, 0, 40, 40, wall=6)
    say("立柱 40 × 40 壁厚 6，向上到 140")
    pause(1.5 * k)
    b.cylinder("通孔", axis="y", x=80, y=20, z=50, r=8, h=20)
    say("通孔 Ø16，位置 (80, 50)")
    pause(1.2 * k)

    say("建模中 ...")
    t0 = time.time()
    rb = b.build(paint=True, keep_open=True)
    focus_sw()
    zoom_fit()
    pause(1.5 * k)
    print()
    if not rb.ok:
        say(f"建模失败：{rb.error}")
        return 1
    say(f"完成  实体 {rb.bodies} 个  耗时 {time.time() - t0:.1f} 秒", big=True)
    pause(2 * k)

    # ---------------------------------------------------------------- 3
    say("[3/6] 赋国标材质 Q235，回读密度", big=True)
    print()
    say(f"请求材质 : {rb.material_requested}")
    say(f"回读材质 : {rb.material_applied}")
    dens = rb.mass_kg / (rb.volume_mm3 * 1e-9) if rb.volume_mm3 else 0
    say(f"体积     : {rb.volume_mm3:.1f} mm³")
    say(f"质量     : {rb.mass_kg:.4f} kg")
    say(f"反算密度 : {dens:.0f} kg/m³")
    print()
    say("SolidWorks 默认密度是 1000（水），不赋材质质量会错 7.85 倍", big=True)
    pause(3 * k)

    # ---------------------------------------------------------------- 4
    say("[4/6] 出 GB 工程图 + 自动标注", big=True)
    print()
    from swforge.drawing import produce, add_dimensions

    dwg = os.path.join(args.out, "01_支架.SLDDRW")
    if os.path.isfile(dwg):
        try:
            os.remove(dwg)
        except OSError:
            pass
    say("生成三视图（GB A3 图框，自动缩放至适合）...")
    rp = produce(part, dwg, paper="A3", keep_open=True)
    focus_sw()
    if not rp.get("ok"):
        say(f"出图失败：{rp.get('err') or rp.get('error')}")
        return 1
    zoom_fit()
    say(f"已生成 {os.path.basename(dwg)}   引擎 {rp.get('engine')}")
    pause(2.5 * k)

    say("添加受控标注（只标值得标的，跨视图去重）...")
    rd = add_dimensions(dwg, curated=True, internal=2)
    focus_sw()
    zoom_fit()
    print()
    for x in ((rd.get("overall") or {}).get("dims") or []):
        kind = "水平" if x.get("horizontal") else ("垂直" if x.get("vertical") else "内部")
        say(f"  {x.get('view')}  {kind} = {x.get('value')}")
    say(f"共 {rd.get('after')} 个尺寸（旧的全量标注会插 22 个并互相重叠）", big=True)
    pause(3.5 * k)

    # ---------------------------------------------------------------- 5
    say("[5/6] 装配 + 配合", big=True)
    print()
    _close_all()
    from swforge import AssemblyBuilder
    from swforge.mates import MateBuilder

    parts = []
    for nm in ("甲", "乙"):
        pp = os.path.join(args.out, f"02_板{nm}.SLDPRT")
        if os.path.isfile(pp):
            try:
                os.remove(pp)
            except OSError:
                pass
        bb = PartBuilder(pp, material="Q235")
        bb.box("板", 0, 60, 0, 20, 0, 40)
        bb.build(paint=False, keep_open=False)
        parts.append(pp)
    say("两块 60 × 20 × 40 的板")

    asm = os.path.join(args.out, "03_总装.SLDASM")
    if os.path.isfile(asm):
        try:
            os.remove(asm)
        except OSError:
            pass
    ab = AssemblyBuilder(asm)
    ab.add(parts[0], x=0, y=0, z=0, fixed=True)
    ab.add(parts[1], x=200, y=0, z=0)
    ra = ab.build()
    focus_sw()
    zoom_fit()
    say(f"装配完成，组件 {len(ra.get('components') or [])} 个（乙板放在 200mm 外）")
    pause(2.5 * k)

    say("加重合配合 —— 乙板应该被自动拉到甲板位置 ...")
    before = MateBuilder(asm).apply()
    xb = [round(float(c["x"]), 1) for c in (before.get("component_boxes_center_mm") or [])]
    res = MateBuilder(asm).coincident(0, 1).apply()
    focus_sw()
    zoom_fit()
    xa = [round(float(c["x"]), 1) for c in (res.get("component_boxes_center_mm") or [])]
    print()
    say(f"配合前 X = {xb}")
    say(f"配合后 X = {xa}")
    say(f"配合表 {len(res.get('mates') or [])} 条", big=True)
    if xb == xa:
        say("⚠ 位置没有变化")
    pause(3 * k)

    # ---------------------------------------------------------------- 6
    say("[6/6] 干涉检查：精确体积", big=True)
    print()
    _close_all()
    from swforge.assembly import check_interference

    say("故意造一个重叠：两块 20mm 立方，沿 X 重叠 10mm")
    say("理论干涉体积 = 10 × 20 × 20 = 4000 mm³")
    pause(2 * k)

    iparts = []
    for nm in ("A", "B"):
        pp = os.path.join(args.out, f"04_干涉{nm}.SLDPRT")
        if os.path.isfile(pp):
            try:
                os.remove(pp)
            except OSError:
                pass
        bb = PartBuilder(pp, material="Q235")
        bb.box("体", 0, 20, 0, 20, 0, 20)
        bb.build(paint=False, keep_open=False)
        iparts.append(pp)

    asm2 = os.path.join(args.out, "05_干涉测试.SLDASM")
    if os.path.isfile(asm2):
        try:
            os.remove(asm2)
        except OSError:
            pass
    ab2 = AssemblyBuilder(asm2)
    ab2.add(iparts[0], x=0, y=0, z=0, fixed=True)
    ab2.add(iparts[1], x=10, y=0, z=0)
    ab2.build()
    focus_sw()
    zoom_fit()
    say("装配完成，检测中 ...")
    pause(1.5 * k)

    ci = check_interference(asm2)
    focus_sw()
    print()
    say(f"报告 {ci.get('interference_count')} 处干涉", big=True)
    ok_vol = False
    for row in (ci.get("interferences") or []):
        vol = row.get("volume_mm3")
        say(f"  体积 {vol} mm³   涉及 {row.get('components')}")
        if vol is not None and abs(float(vol) - 4000.0) < 1.0:
            ok_vol = True
    print()
    if ok_vol:
        say("与手算值 4000 mm³ 一致 —— 不是「有无干涉」，是精确体积", big=True)
    else:
        say("⚠ 与理论值不一致")
    pause(4 * k)

    # ---------------------------------------------------------------- 收尾
    print()
    say("演示结束", big=True)
    print()
    say("每一步的结果都是从 SolidWorks 读回来的，不是「调用没报错」")
    say("自己验证：pip install swforge   然后   swforge selftest")
    print()

    try:
        from swforge.resources import sweep_documents
        sweep_documents(dry_run=False)
    except Exception:                                  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
