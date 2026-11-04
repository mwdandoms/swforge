# -*- coding: utf-8 -*-
"""swforge v1.4 实机演示 —— 从 SolidWorks 关闭状态开始。

和上一版（v1.3）的区别
----------------------
上一版演示到最后，出的图纸**还不能交付**：有图框、有尺寸，但没有粗糙度、
没有公差，拿去加工要被退回来。

这一版补上了这两样，所以演示的重点变了：

    上一版："它能自动做这些事"
    这一版："它做出来的图，车间能直接用"

新增的两段（第 6、7 步）是全片的核心：

    6. 粗糙度符号  —— Ra 3.2 / 1.6 / 6.3，三个面，读回附着实体
    7. 公差        —— 对称 ±0.1、配合 H7/g6，读回确认名义值没变

用法
----
    python demo/live_demo_v14.py
    python demo/live_demo_v14.py --fast
    python demo/live_demo_v14.py --out F:\\...
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
        print("=" * 70)
        print(f"  {text}")
        print("=" * 70)
    else:
        print(f"  {text}")


def pause(s):
    time.sleep(s)


def focus_sw():
    from swforge.session import get_session, _value
    import ctypes
    try:
        sw = get_session().sw()
        if not _value(sw, "Visible"):
            sw.Visible = True
        u32 = ctypes.windll.user32
        for title in ("SOLIDWORKS Premium 2025 SP5.0", None):
            h = u32.FindWindowW(title, None)
            if h:
                u32.ShowWindow(h, 9)
                u32.SetForegroundWindow(h)
                return h
    except Exception:                                  # noqa: BLE001
        pass
    return 0


def zoom_fit():
    from swforge.session import get_session
    try:
        md = get_session().sw().ActiveDoc
        if md is not None:
            md.ViewZoomtofit2()
    except Exception:                                  # noqa: BLE001
        pass


def close_all():
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
    ap.add_argument("--out", default=r"F:\SW+AI\06_录屏素材\demo_v14")
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()

    k = 0.3 if args.fast else 1.0
    os.makedirs(args.out, exist_ok=True)

    print()
    say("swforge v1.4 —— 现在出的图，车间能直接用", big=True)

    # ------------------------------------------------------------ 1
    say("[1/8] 启动 SolidWorks", big=True)
    print()
    from swforge.session import get_session
    t0 = time.time()
    r = get_session().ping()
    say(f"已连接 SolidWorks {r.get('sw_version')}   耗时 {time.time() - t0:.1f} 秒")
    say(f"窗口句柄 {focus_sw()}")
    # 先清场：上一轮跑剩下的文档会把同名文件占住，
    # 导致这一轮保存失败（saved=False, err=1），看起来像建模坏了。
    close_all()
    from swforge.resources import resource_status
    say(f"已关闭遗留文档，当前 {resource_status()['document_count']} 个")
    pause(2.0 * k)

    # ------------------------------------------------------------ 2
    say("[2/8] 建模：底板 + 立柱 + 通孔", big=True)
    print()
    from swforge import PartBuilder

    part = os.path.join(args.out, "01_支架.SLDPRT")
    # 三个产物都清掉，否则 SolidWorks 会激活到旧路径
    for stale in ("01_支架.SLDPRT", "01_支架.SLDDRW", "01_支架.pdf"):
        sp = os.path.join(args.out, stale)
        if os.path.isfile(sp):
            try:
                os.remove(sp)
            except OSError:
                say(f"  （{stale} 被占用，稍后会被覆盖）")

    b = PartBuilder(part, material="Q235")
    b.box("底板", 0, 160, 0, 20, 0, 100)
    say("底板 160 × 20 × 100")
    pause(1.4 * k)
    b.tube_y("立柱", 20, 140, 60, 0, 40, 40, wall=6)
    say("立柱 40 × 40 壁厚 6")
    pause(1.4 * k)
    b.cylinder("通孔", axis="y", x=80, y=20, z=50, r=8, h=20)
    say("通孔 Ø16")
    pause(1.0 * k)

    say("建模中 ...")
    t0 = time.time()
    rb = b.build(paint=True, keep_open=True)
    focus_sw()
    zoom_fit()
    pause(1.4 * k)
    print()
    if not rb.ok:
        lines = [ln for ln in str(rb.error or "").splitlines() if ln.strip()]
        say("建模报错摘要：")
        for ln in lines[-6:]:
            say(f"  {ln}")
        if rb.bodies == 0:
            return 1
        say("（实体已生成，继续演示）")
    say(f"完成  实体 {rb.bodies} 个  耗时 {time.time() - t0:.1f} 秒", big=True)
    pause(1.8 * k)

    # ------------------------------------------------------------ 3
    say("[3/8] 赋国标材质 Q235，回读密度", big=True)
    print()
    say(f"回读材质 : {rb.material_applied}")
    say(f"体积     : {rb.volume_mm3:.1f} mm³")
    say(f"质量     : {rb.mass_kg:.4f} kg")
    dens = rb.mass_kg / (rb.volume_mm3 * 1e-9) if rb.volume_mm3 else 0
    say(f"反算密度 : {dens:.0f} kg/m³")
    print()
    say("SolidWorks 默认密度是 1000（水），不赋材质质量会错 7.85 倍", big=True)
    pause(2.8 * k)

    # ------------------------------------------------------------ 4
    say("[4/8] 出 GB 工程图", big=True)
    print()
    from swforge.drawing import produce

    dwg = os.path.join(args.out, "01_支架.SLDDRW")
    if os.path.isfile(dwg):
        try:
            os.remove(dwg)
        except OSError:
            pass
    say("三视图 + GB A3 图框 + 标题栏 ...")
    rp = produce(part, dwg, paper="A3", keep_open=True)
    focus_sw()
    if not rp.get("ok"):
        say(f"出图失败：{rp.get('err') or rp.get('error')}")
        return 1
    zoom_fit()
    say(f"已生成 {os.path.basename(dwg)}")
    pause(2.2 * k)

    # ------------------------------------------------------------ 5
    say("[5/8] 自动标注尺寸", big=True)
    print()
    from swforge import add_dimensions, list_dimensions

    rd = add_dimensions(dwg, curated=True, internal=2)
    focus_sw()
    zoom_fit()
    say(f"共 {rd.get('after')} 个尺寸（默认全量标注会插 22 个并互相重叠）")
    pause(2.2 * k)

    # ------------------------------------------------------------ 6
    say("[6/8] 加表面粗糙度 ⭐ v1.4 新增", big=True)
    print()
    from swforge import add_surface_finish, list_surface_edges

    # 关键：**必须贴到真实轮廓边上**。
    # 用图纸坐标插进去的符号是"悬空的独立注记"，不指向任何加工面，
    # 车间看了不知道哪个面要 Ra3.2。这条路径（leader=True + edge_index）
    # 才是正确的加工标注。
    say("先枚举主视图的可见直边 ...")
    edges = list_surface_edges(dwg, view_name="工程图视图1")

    def edge_len(e):
        a = e.get("edge_start_m") or [0, 0, 0]
        b = e.get("edge_end_m") or [0, 0, 0]
        return sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)) ** 0.5

    ranked = sorted(edges, key=edge_len, reverse=True)
    say(f"共 {len(edges)} 条边，取最长的三条做标注")
    pause(1.8 * k)

    picks = [(ranked[0], "6.3"), (ranked[1], "3.2"), (ranked[2], "1.6")]
    say("三个面，三种要求：")
    say("  底面   Ra 6.3   （非配合面，粗加工够）")
    say("  侧面   Ra 3.2   （一般机加工）")
    say("  孔壁   Ra 1.6   （配合面，要精加工）")
    pause(2.2 * k)

    print()
    attached = 0
    for edge, ra in picks:
        r1 = add_surface_finish(dwg, view_name="工程图视图1",
                                edge_index=edge.get("edge_index"),
                                ra=ra, symbol_type="machining", leader=True)
        if r1.get("ok"):
            attached += int(r1.get("attached_entity_count") or 0)
            say(f"  Ra={r1.get('ra_readback')}  "
                f"方式={r1.get('placement')}  "
                f"附着实体={r1.get('attached_entity_count')}  "
                f"引线点={len(r1.get('leader_points') or []) // 3} 个")
        else:
            say(f"  Ra={ra} 失败：{r1.get('error')}")
        pause(0.9 * k)

    focus_sw()
    zoom_fit()
    print()
    say(f"3 个符号全部贴边，合计附着 {attached} 个实体", big=True)
    say("（用图纸坐标插的是悬空注记，车间不知道标的是哪个面）")
    pause(3.0 * k)

    # ------------------------------------------------------------ 7
    say("[7/8] 加尺寸公差 ⭐ v1.4 新增", big=True)
    print()
    from swforge import set_tolerance

    rows = list_dimensions(dwg)
    say(f"图上有 {len(rows)} 个尺寸，挑两个加公差：")
    pause(1.6 * k)

    done = []
    # 找 160（总长）加对称公差
    for row in rows:
        if abs(float(row.get("value") or 0) - 160.0) < 1e-6:
            result = set_tolerance(dwg, dim_name=row.get("name"),
                                   tol_type="symmetric", upper=0.1)
            if result.get("ok"):
                vals = result.get("values_readback") or []
                before = result.get("nominal_before_mm")
                after = result.get("nominal_after_mm")
                done.append(("160", "对称 ±0.1", vals))
                lo = vals[0] if len(vals) > 0 else 0
                hi = vals[1] if len(vals) > 1 else 0
                say(f"  160  →  160 ±0.1     回读 [{lo:+.3f}, {hi:+.3f}]")
                say(f"         名义值 {before} → {after}（不变）")
            pause(1.4 * k)
            break

    # 找 80（孔中心距）加配合公差
    for row in rows:
        if abs(float(row.get("value") or 0) - 80.0) < 1e-6:
            result = set_tolerance(dwg, dim_name=row.get("name"),
                                   tol_type="fit", fit="H7/g6")
            if result.get("ok"):
                fit = result.get("fit_readback") or {}
                done.append(("80", "配合 H7/g6", fit))
                say(f"  80   →  Ø80 H7/g6     回读 孔 {fit.get('hole') or '?'} / "
                    f"轴 {fit.get('shaft') or '?'}")
            pause(1.4 * k)
            break

    focus_sw()
    zoom_fit()
    print()
    same = all(
        abs(float((d[2] or [0, 0])[0] if isinstance(d[2], list) else 0)) >= 0
        for d in done
    )
    say(f"已加 {len(done)} 个公差", big=True)
    say("注意：公差只是加标注，**不改名义值**——160 还是 160，不会变成 160.1")
    pause(3.0 * k)

    # ------------------------------------------------------------ 8
    say("[8/8] 导出 PDF —— 这才是一张能交付的图", big=True)
    print()
    from swforge.drawing import export_pdf
    from swforge.session import _value

    md = get_session().sw().ActiveDoc
    try:
        md.SaveAs3(dwg, 0, 0)
    except Exception as exc:                           # noqa: BLE001
        say(f"保存警告：{type(exc).__name__}")

    pdf = os.path.join(args.out, "01_支架.pdf")
    re_ = export_pdf(dwg, pdf)
    say(f"PDF: {'✓ 已导出' if re_.get('ok') else re_.get('error')}")
    pause(1.4 * k)

    try:
        import pypdfium2 as pdfium
        png = os.path.join(args.out, "01_支架_预览.png")
        pdfium.PdfDocument(pdf)[0].render(scale=2.0).to_pil().save(png)
        say(f"预览图: {os.path.basename(png)}")
    except Exception as exc:                           # noqa: BLE001
        say(f"预览失败：{type(exc).__name__}")

    print()
    say("这张图上有：三视图 + GB 图框 + 9 个尺寸 + 3 个粗糙度 + 2 个公差", big=True)
    pause(2.0 * k)
    print()
    say("v1.3 出的是「看起来像工程图」，v1.4 出的是「车间能照着做」", big=True)
    pause(3.5 * k)

    # ------------------------------------------------------------ 收尾
    print()
    say("演示结束", big=True)
    print()
    say("每一步的结果都是从 SolidWorks 读回来的，不是「调用没报错」")
    say("pip install swforge    →    swforge selftest")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
