# -*- coding: utf-8 -*-
"""跨版本验收脚本 —— 在一台陌生机器上跑，把结论结构化带回来。

设计目标
========
1. **绝不崩**：每一阶段都包 try/except，失败记档继续往下跑。
   异机测试最怕「跑到第三步抛异常停了」，回来后什么信息都没有。
2. **分阶段定位**：环境 → 连接 → API → 建模 → 出图 → 模板。
   哪一阶段挂了，报告里一眼看得出是「版本不兼容」还是「装错了」。
3. **不依赖模板也能出结论**：旧版 SW 打不开 2025 的 .DRWDOT，
   所以建模阶段必须与出图阶段解耦 —— 建模过了就说明核心可用。
4. **回传一份就够**：同时写 ``report.json``（机器读）和 ``report.md``（人读）。

用法
====
    python version_acceptance.py --year 2019
    python version_acceptance.py --year 2019 --out D:\acc    # 指定输出目录
    python version_acceptance.py --year 2019 --no-drawing    # 跳过出图阶段（更快）

前提：SolidWorks 已手动启动好；``pip install swforge`` 已装。
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
import os
import platform
import sys
import time
import traceback

STAGES: list[dict] = []


def stage(name: str, fn):
    """跑一个阶段，任何异常都记档不中断。"""
    t0 = time.time()
    rec = {"stage": name, "status": "unknown", "seconds": 0, "detail": {}, "error": None}
    try:
        out = fn() or {}
        rec["status"] = out.pop("status", "pass")
        rec["detail"] = out
    except Exception as exc:                                  # noqa: BLE001
        rec["status"] = "fail"
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["seconds"] = round(time.time() - t0, 2)
    STAGES.append(rec)
    flag = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP", "blocked": "BLOCK"}.get(
        rec["status"], rec["status"].upper())
    print(f"  [{flag}] {name:<28} {rec['seconds']:6.2f}s"
          + (f"   {rec['error'][:70]}" if rec["error"] else ""))
    return rec


# ─────────────────────────────────────────────────────────── 阶段 0：环境
def s_env():
    import swforge
    d = {
        "swforge": swforge.__version__,
        "swforge_path": swforge.__file__,
        "python": sys.version.split()[0],
        "python_exe": sys.executable,
        "platform": platform.platform(),
        "arch": platform.machine(),
    }
    if sys.version_info < (3, 10):
        d["status"] = "fail"
        d["note"] = "swforge 需要 Python 3.10+"
    return d


# ─────────────────────────────────────────────────────────── 阶段 1：连接
def s_connect():
    from swforge import document_inventory, get_session
    from swforge.session import _value

    sw = get_session().sw()
    rev = str(_value(sw, "RevisionNumber"))
    major = int(rev.split(".")[0])
    year = major + 1992                      # SW 版本编码：2025 → 33
    return {
        "revision": rev,
        "year": year,
        "process_id": int(_value(sw, "GetProcessID")),
        "open_documents": document_inventory(sw)["document_count"],
        "status": "pass",
    }


# ─────────────────────────────────────────────────────────── 阶段 2：API 反射
def s_api():
    from swforge import probe

    r = probe.probe_api()
    apis = r.get("apis") or {}
    missing = list(r.get("missing") or [])
    return {
        "ok": r.get("ok"),
        "interop_version": r.get("assembly_version"),
        "interop_dll": r.get("dll_path"),
        "total": r.get("total_count", len(apis)),
        "present": r.get("available_count", len(apis) - len(missing)),
        "missing_count": len(missing),
        "missing_names": missing[:20],
        "notes": r.get("summary"),
        # 缺 API 不算阶段失败 —— 这正是要测出来的东西
        "error": r.get("error"),
        "status": "pass" if r.get("ok") else "fail",
    }


# ─────────────────────────────────────────────────────────── 阶段 3：建模
def s_model(outdir):
    from swforge import PartBuilder

    model = os.path.join(outdir, "acc_box.SLDPRT")
    b = PartBuilder(model, material="Q235")
    b.box("base", 0, 100, 0, 20, 0, 50)
    b.hole_grid("holes", "base", x=20, z=15, rows=2, columns=3,
                pitch_u=30, pitch_v=20, diameter=8, through_all=True)
    r = b.build(keep_open=False, max_documents=5, timeout_s=120)
    d = {
        "ok": bool(getattr(r, "ok", False)),
        "bodies": getattr(r, "bodies", None),
        "volume_mm3": round(getattr(r, "volume_mm3", 0) or 0, 3),
        "mass_kg": getattr(r, "mass_kg", 0) or 0,
        "part": model if os.path.isfile(model) else None,
        "material_applied": r.material_applied,
        "error": r.error,
    }
    # 理论体积：100*20*50 - 6*(π*4²*20)
    expect = 100 * 20 * 50 - 6 * (3.141592653589793 * 16 * 20)
    d["volume_expected_mm3"] = round(expect, 3)
    d["volume_deviation_pct"] = round(abs(d["volume_mm3"] - expect) / expect * 100, 3)
    d["density_check"] = "7850 附近=材质已赋; 1000=按水算(材质没赋上)"
    if not d["ok"] or r.bodies != 1 or not math.isclose(r.volume_mm3, expect, abs_tol=.01):
        d["status"] = "fail"
    return d


# ─────────────────────────────────────────────────────────── 阶段 4：材质密度
def s_material(outdir):
    """用建模阶段的 质量/体积 反算密度。

    刻意不调 ``Extension.CreateMassProperty`` —— 它在 pywin32 后期绑定下
    会抛「类型不匹配」（swforge 源码 assembly.py 已注明这一点，正确做法是走
    ``IBody2.GetMassProperties``）。反算只用已有数据，任何 SW 版本都成立：
    密度≈7850 说明材质真赋上了；≈1000 说明按水算，质量会错 7.85 倍。
    """
    model_rec = next((s for s in STAGES if s["stage"] == "model"), None)
    d = (model_rec or {}).get("detail") or {}
    vol_mm3, mass_kg = d.get("volume_mm3"), d.get("mass_kg")
    if not vol_mm3 or not mass_kg:
        return {"status": "skip", "note": "建模阶段没有质量/体积数据，无法反算"}
    density = mass_kg / (vol_mm3 * 1e-9)            # kg/m³
    if abs(density - 7850) <= 2 and d.get("material_applied") == "Q235":
        verdict, st = "正确：材质已赋（Q235≈7850）", "pass"
    elif abs(density - 1000) < 300:
        verdict, st = "异常：按水密度 1000 计算，质量错 7.85 倍 —— 材质没赋上", "fail"
    elif abs(density - 2700) < 300:
        verdict, st = "可疑：接近铝 2700，材质可能赋错", "fail"
    else:
        verdict, st = f"反算 {density:.0f} kg/m³ 或材料名称不符，请核对材质", "fail"
    return {
        "density_kg_m3": round(density, 1),
        "mass_kg": mass_kg,
        "volume_mm3": vol_mm3,
        "density_verdict": verdict,
        "status": st,
    }


# ─────────────────────────────────────────────────────────── 阶段 5：出图
def s_drawing(outdir):
    from swforge.drawing import produce

    model = os.path.join(outdir, "acc_box.SLDPRT")
    if not os.path.isfile(model):
        return {"status": "skip", "note": "建模阶段没产出文件"}
    drawing = os.path.join(outdir, "acc_box.SLDDRW")
    r = produce(model, drawing, paper="A3", keep_open=False, max_documents=5)
    lay = r.get("layout") or {}
    d = {
        "ok": bool(r.get("ok")),
        "paper": r.get("paper"),
        "template": r.get("template"),
        "scale": lay.get("scale"),
        "span_fraction": lay.get("span_fraction"),
        "scales_tried": lay.get("scales_tried"),
        "error": (str(r.get("error"))[:400] if r.get("error") else None),
        "code": r.get("code"),
        "drawing": drawing if os.path.isfile(drawing) else None,
    }
    if not d["ok"]:
        d["status"] = "fail"
        d["hint"] = ("若 error 含 template / 模板 / drwdot，说明随包模板（2025 格式）"
                     "在本版本打不开 —— 这是旧版 SW 的已知限制，需在该版本内重建模板。")
    return d


# ─────────────────────────────────────────────────────────── 阶段 6：模板
def s_template():
    import swforge
    from swforge.drawing import _template_dirs
    from swforge.gb_styles import gb_template_path

    bundled = os.path.join(os.path.dirname(swforge.__file__), "assets", "templates")
    files = sorted(os.listdir(bundled)) if os.path.isdir(bundled) else []
    local = _template_dirs()
    return {
        "bundled_dir": bundled,
        "bundled_count": len([f for f in files if f.lower().endswith((".drwdot", ".slddrt"))]),
        "local_template_dirs": local[:6],
        "local_template_count": len(local),
        "a4_landscape_template": gb_template_path("A4L"),
        "status": "pass",
    }


# ─────────────────────────────────────────────────────────── 阶段 7：自检
def s_selftest():
    from swforge.selftest import run_selftest

    r = run_selftest()
    results = r.get("results") or r.get("checks") or []
    passed = sum(1 for x in results if str(x.get("status", x.get("ok", ""))).lower()
                 in ("pass", "true", "ok", "1"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "failed_names": [x.get("name") for x in results
                         if str(x.get("status", x.get("ok", ""))).lower()
                         not in ("pass", "true", "ok", "1")][:15],
        "status": "pass" if r.get("ok") else "fail",
    }


# ─────────────────────────────────────────────────────────── 汇总
def write_reports(outdir, env):
    summary_path = os.path.join(outdir, "report.json")
    doc = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": env,
        "stages": STAGES,
        "version_verdict": None,
        "guidance": [],
    }

    by = {s["stage"]: s for s in STAGES}
    conn = (by.get("connect") or {}).get("detail") or {}
    year = conn.get("year")
    doc["detected_year"] = year
    def blk(name):
        return (by.get(name) or {}).get("status")

    required = ("connect", "model", "material", "template", "documents")
    if "drawing" in by:
        required += ("drawing",)
    doc["version_verdict"] = "smoke_pass" if all(blk(name) == "pass" for name in required) else "smoke_fail"

    if blk("connect") != "pass":
        doc["guidance"].append("连接失败：先手动启动 SolidWorks，再重跑本脚本。")
    if blk("api_probe") == "pass":
        miss = ((by.get("api_probe") or {}).get("detail") or {}).get("missing_names") or []
        if miss:
            doc["guidance"].append(f"本机 Interop 缺 {len(miss)} 个 API：{miss}。"
                                   "依赖这些 API 的能力会降级或不可用。")
    if blk("model") == "pass":
        doc["guidance"].append("建模核心可用（盒体+孔阵列通过体积回读校验）。")
    elif blk("model") == "fail":
        doc["guidance"].append("建模失败：这是核心能力，必须排查。看 report.json 里的 traceback。")
    if blk("drawing") == "fail":
        err = ((by.get("drawing") or {}).get("detail") or {}).get("error") or ""
        if any(k in err.lower() for k in ("template", "模板", "drwdot", "slddrt")):
            doc["guidance"].append(
                "出图失败原因是模板：随包 .DRWDOT 是 2025 格式，本版本打不开。"
                "检查目标版本的本机模板及 SW_TEMPLATE_DIR。")
        else:
            doc["guidance"].append(f"出图失败：{err[:200]}")

    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)

    # 人读版
    md = [f"# swforge 跨版本验收报告",
          "",
          f"- 生成时间：{doc['generated_at']}",
          f"- swforge：{env.get('swforge')}",
          f"- Python：{env.get('python')}（{env.get('arch')}）",
          f"- 平台：{env.get('platform')}",
          f"- **检测到 SolidWorks 年份：{year}**",
          f"- 结论：{doc['version_verdict']}",
          "",
          "| 阶段 | 结果 | 耗时 | 说明 |",
          "|---|---|---|---|"]
    for s in STAGES:
        note = s["error"] or json.dumps(s.get("detail") or {}, ensure_ascii=False)[:90]
        md.append(f"| {s['stage']} | {s['status']} | {s['seconds']}s | {note[:90]} |")
    md += ["", "## 建议", ""]
    md += [f"- {g}" for g in doc["guidance"]] or ["- 无明显问题"]
    md += ["", "## 详细数据", "", "见同目录 `report.json`。"]
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    return summary_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="swforge 跨版本验收（容错，绝不中断）")
    ap.add_argument("--out", default=os.getcwd(), help="报告输出目录")
    ap.add_argument("--no-drawing", action="store_true", help="跳过出图阶段")
    from swforge.sw_target import SW_YEARS

    ap.add_argument("--year", type=int, choices=SW_YEARS, default=os.environ.get("SWFORGE_SW_YEAR"),
                    help="目标 SolidWorks 年份，或设置 SWFORGE_SW_YEAR")
    selftest = ap.add_mutually_exclusive_group()
    selftest.add_argument("--selftest", action="store_true", help="额外运行完整实机自检")
    selftest.add_argument("--no-selftest", action="store_false", dest="selftest")
    ap.set_defaults(selftest=False)
    args = ap.parse_args(argv)

    if args.year not in SW_YEARS:
        ap.error("请使用 --year 指定已启动的 SolidWorks 年份")
    os.environ["SWFORGE_SW_YEAR"] = str(args.year)
    STAGES.clear()
    os.makedirs(args.out, exist_ok=True)
    outdir = tempfile.mkdtemp(prefix=f"swforge_{args.year}_", dir=os.path.abspath(args.out))

    print("=" * 66)
    print("  swforge 跨版本验收")
    print(f"  输出目录：{outdir}")
    print("=" * 66)
    print()

    env = stage("environment", s_env)["detail"]
    connected = stage("connect", s_connect)["status"] == "pass"
    if connected:
        from swforge import document_inventory

        before = document_inventory()
        stage("api_probe", s_api)
        stage("model", lambda: s_model(outdir))
        stage("material", lambda: s_material(outdir))
        if not args.no_drawing:
            stage("drawing", lambda: s_drawing(outdir))
        stage("template", s_template)
        if args.selftest:
            stage("selftest", s_selftest)

        def verify_documents():
            after = document_inventory()
            same = before["documents"] == after["documents"]
            same = same and before.get("process_id") == after.get("process_id")
            return {"status": "pass" if same else "fail", "before": before, "after": after}

        stage("documents", verify_documents)

    path = write_reports(outdir, env)

    print()
    print("=" * 66)
    ok = sum(1 for s in STAGES if s["status"] == "pass")
    bad = [s["stage"] for s in STAGES if s["status"] == "fail"]
    print(f"  {ok}/{len(STAGES)} 阶段通过")
    if bad:
        print(f"  失败阶段：{', '.join(bad)}")
    print(f"  报告：{path}")
    print(f"        {os.path.join(outdir, 'report.md')}")
    print("=" * 66)
    print()
    print("  请把 report.json 和 report.md 一起发回。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
