# -*- coding: utf-8 -*-
"""命令行入口：`swforge <子命令>`"""

from __future__ import annotations

import argparse
import json
import os
import sys


# ---------------------------------------------------------------- 编码兜底
# Windows 上 Python 有时把 stdout 编码设成 cp1252 之类的单字节编码。
# 这时打印中文会抛 UnicodeEncodeError —— 而 `swforge --help` 里的描述就是中文，
# 所以陌生人第一次运行就可能直接崩在帮助信息上。（这条是 CI 抓到后修的。）
_CJK_SAFE = ("utf-8", "utf8", "cp65001", "cp936", "gbk", "gb2312", "big5", "cp950")


def _stream_encoding(stream) -> str:
    try:
        return (getattr(stream, "encoding", "") or "").lower()
    except Exception:                                     # noqa: BLE001
        return ""


def _make_output_safe() -> None:
    """让 CLI 输出永远不会因为编码崩掉。

    两步：
    1. 把 stdout/stderr 的 errors 设成 replace —— 编不出来的字符变 ? 而不是抛异常
    2. JSON 输出时按流的真实编码决定 ensure_ascii
       （单字节编码下必须转义，否则 JSON 会变成非法字符序列，机器读不了）
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:                                 # noqa: BLE001
            pass


def _json_ascii() -> bool:
    """当前 stdout 编码能否安全表示中文；不能就转义成 \\uXXXX。"""
    enc = _stream_encoding(sys.stdout)
    if not enc:
        return False                                      # 未知编码，保守转义
    if any(k in enc for k in _CJK_SAFE):
        return False
    return True


def _p(obj) -> None:
    print(json.dumps(obj, ensure_ascii=_json_ascii(), indent=2, default=str))


def _result(obj) -> int:
    _p(obj)
    return 1 if isinstance(obj, dict) and obj.get("ok") is False else 0


def _main(argv: list[str] | None = None) -> int:
    _make_output_safe()
    ap = argparse.ArgumentParser(prog="swforge", description="SolidWorks 自动化工具箱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("selftest",
                       help="实机自检：逐项验证回读、资源、干涉、尺寸等承诺是否真的成立")
    p.add_argument("--only", default=None, help="只跑名称或标题含该词的检查")
    p.add_argument("--keep", action="store_true", help="保留产物目录")
    p.add_argument("--work-dir", default=None, help="指定产物目录")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    p = sub.add_parser("bom", help="从装配体读 BOM 明细（材料/数量），可导出 CSV")
    p.add_argument("assembly", nargs="?", default=None, help="装配体路径，省略则用当前文档")
    p.add_argument("--csv", default=None, help="导出 CSV 的路径")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    sub.add_parser("ping", help="连接探针")
    sub.add_parser("survey", help="量当前文档的包络与实体构成")
    p = sub.add_parser("capabilities", help="本机能力自检")
    p.add_argument("--api", action="store_true",
                   help="额外用反射探测本机 Interop 支持哪些 API（判断版本兼容用）")
    p.add_argument("--sw-dir", default=None, help="手动指定 SolidWorks 安装目录")
    p = sub.add_parser("materials", help="列出内置 GB 牌号并生成/校验 SW 材质库")
    p.add_argument("--ensure", action="store_true", help="生成材质库并返回路径")
    p.add_argument("--force", action="store_true", help="强制重新生成")

    p = sub.add_parser("batch", help="批量出图：一个文件夹的零件 -> 一批工程图")
    p.add_argument("folder", help="模型所在文件夹")
    p.add_argument("--out", default=None, help="输出文件夹（默认与模型同目录）")
    p.add_argument("--pattern", default="*.SLDPRT", help="文件名通配，默认 *.SLDPRT")
    p.add_argument("--recursive", action="store_true", help="递归子目录")
    p.add_argument("--paper", default="A3", choices=["A0", "A1", "A2", "A3", "A4"])
    p.add_argument("--no-overall", action="store_true", help="不补总尺寸")
    p.add_argument("--pdf", action="store_true", help="同时导出 PDF")
    p.add_argument("--no-skip-existing", action="store_true", help="已存在也重出（默认跳过）")
    p.add_argument("--limit", type=int, default=0, help="最多处理 N 个（0=不限）")
    p.add_argument("--max-documents", type=int, default=8)
    p.add_argument("--report", default=None, help="把结果写成 JSON 报告")
    p.add_argument("--json", action="store_true", help="输出 JSON 而不是人读格式")

    p = sub.add_parser("resources", help="SW 文档数量与内存健康检查；可清扫遗留临时文档")
    p.add_argument("--limit", type=int, default=8, help="文档数上限，默认 8")
    p.add_argument("--warn-ratio", type=float, default=0.75, help="告警线比例，默认 0.75")
    p.add_argument("--mem-warn-mb", type=float, default=2500.0, help="内存告警阈值 MB")
    p.add_argument("--sweep", action="store_true", help="列出可关闭的遗留临时/测试文档")
    p.add_argument("--apply", action="store_true", help="真正关闭（配合 --sweep）")
    p.add_argument("--keep", action="append", default=[], help="永不关闭的路径（可重复）")

    p = sub.add_parser("build", help="按 JSON 描述建零件")
    p.add_argument("spec", help="形位描述 JSON 路径")
    p.add_argument("--out", required=True, help="输出 .SLDPRT 路径")
    p.add_argument("--validate-only", action="store_true", help="只验证描述，不连接 SolidWorks")
    p.add_argument("--no-paint", action="store_true", help="不执行面级配色后处理")
    p.add_argument("--keep-open", action="store_true", help="完成后保留生成的模型文档")
    p.add_argument("--max-documents",type=int,default=8)

    p = sub.add_parser("color", help="按规则给当前零件分色")
    p.add_argument("rules", help="规则 JSON 路径")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("purge", help="清理导入模型的垃圾体/碎片")
    p.add_argument("--giant", type=float, default=5000.0, help="最大边长阈值 mm")
    p.add_argument("--small", type=float, default=None, help="碎片阈值 mm")
    p.add_argument("--min-y", type=float, default=None, help="碎片最低高度")
    p.add_argument("--apply", action="store_true", help="真的删（默认只列）")

    p = sub.add_parser("draw", help="出工程图")
    p.add_argument("model")
    p.add_argument("--out", default=None)
    p.add_argument("--paper", default="A3")
    p.add_argument("--annotations",action="store_true",help="明确请求 MechDog 自动标注，结果需审核")
    p.add_argument("--keep-open",action="store_true")
    p.add_argument("--max-documents",type=int,default=8)
    p.add_argument("--template",default=None)

    p=sub.add_parser("export",help="导出指定工程图并验证 PDF")
    p.add_argument("drawing")
    p.add_argument("--out",default=None)

    p = sub.add_parser("atlas", help="按 JSON 页面描述拼 PDF 图集")
    p.add_argument("spec")
    p.add_argument("--out", required=True)

    args = ap.parse_args(argv)
    if args.cmd == "materials":
        from .gb_materials import GB_MATERIALS, ensure_library, library_path
        rows = [{"grade": n, "density_kg_m3": v[0], "elastic_pa": v[1],
                 "poisson": v[2], "note": v[3]}
                for n, v in sorted(GB_MATERIALS.items())]
        out = {"ok": True, "count": len(rows), "grades": rows, "library": library_path()}
        if args.ensure:
            out["library"] = ensure_library(force=args.force)
        return _result(out)

    if args.cmd == "capabilities":
        return _cmd_capabilities(args)

    if args.cmd == "batch":
        return _cmd_batch(args)

    if args.cmd == "resources":
        from .resources import resource_status, sweep_documents
        out = resource_status(limit=args.limit, warn_ratio=args.warn_ratio,
                              mem_warn_mb=args.mem_warn_mb)
        if args.sweep:
            out["sweep"] = sweep_documents(dry_run=not args.apply, keep=args.keep)
            if args.apply:
                out.update({k: out["sweep"][k] for k in ("document_count", "headroom")}
                           if False else {})
                out = resource_status(limit=args.limit, warn_ratio=args.warn_ratio,
                                      mem_warn_mb=args.mem_warn_mb)
                out["sweep"] = sweep_documents(dry_run=True, keep=args.keep)
        return _result(out)

    if args.cmd == "selftest":
        return _cmd_selftest(args)
    if args.cmd == "bom":
        return _cmd_bom(args)
    if args.cmd == "ping":
        from .session import get_session

        return _result(get_session().ping())

    if args.cmd == "survey":
        from .cleanup import survey

        return _result(survey())

    if args.cmd == "capabilities":
        from .drawing import have_mechdog

        info = {
            "swforge": __import__("swforge").__version__,
            "mechdog": have_mechdog(),
            "python": sys.version.split()[0],
            "platform": sys.platform,
        }
        try:
            from .session import get_session

            info["sw"] = get_session().ping()
        except Exception as exc:                         # noqa: BLE001
            info["sw"] = {"ok": False, "error": str(exc)}
        info["ok"] = bool(info["sw"].get("ok"))
        return _result(info)

    if args.cmd == "build":
        from .spec import builder_from_spec

        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        b = builder_from_spec(args.out, spec)
        if args.validate_only:
            return _result({"ok": True, "path": b.path, "validated": True,
                            "source_bytes": len(b.render_cs().encode("utf-8"))})
        return _result(b.build(paint=not args.no_paint,keep_open=args.keep_open,
                               max_documents=args.max_documents).__dict__)

    if args.cmd == "color":
        from .colors import FaceRule, apply_rules

        with open(args.rules, encoding="utf-8") as fh:
            spec = json.load(fh)
        rules = [FaceRule(r["name"], tuple(r["color"]), **r.get("cond", {}))
                 for r in spec["rules"]]
        return _result(apply_rules(spec.get("part", ""), rules, dry_run=args.dry_run))

    if args.cmd == "purge":
        from .cleanup import purge_giant, purge_small
        from .session import get_session

        md = get_session().sw().ActiveDoc
        if md is None:
            print("没有打开的文档", file=sys.stderr)
            return 1
        if args.small is not None:
            return _result(purge_small(md, args.small, args.min_y, dry_run=not args.apply))
        else:
            return _result(purge_giant(md, args.giant, dry_run=not args.apply))

    if args.cmd == "draw":
        from .drawing import produce

        return _result(produce(args.model, args.out, args.paper,annotations=args.annotations,
                               keep_open=args.keep_open,max_documents=args.max_documents,template=args.template))

    if args.cmd == 'export':
        from .drawing import export_pdf
        return _result(export_pdf(args.drawing,args.out))

    if args.cmd == "atlas":
        from .drawing import make_atlas

        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        return _result(make_atlas(spec["pages"], args.out,
                      title=spec.get("title", "技术图集"),
                      subtitle=spec.get("subtitle", ""),
                      cover_items=[tuple(x) for x in spec.get("cover_items", [])],
                      paper=spec.get("paper", "A3")))

    return 1




def _cmd_bom(args):
    """读装配体的 BOM 明细。"""
    from .bom import collect_bom, bom_to_csv, bom_to_markdown

    r = collect_bom(args.assembly)
    if args.json:
        print(_json_ascii(r))
        return 0 if r.get("ok") else 1
    if not r.get("ok"):
        print(f"  失败：{r.get('error')}")
        return 1

    print()
    print(f"  装配：{r['assembly']}")
    print(f"  种类 {r['distinct_parts']} 项，共计 {r['total_items']} 件")
    print()
    print(bom_to_markdown(r["rows"]))
    print()
    if r.get("missing_material"):
        print(f"  ⚠ 这些零件没有材料：{', '.join(r['missing_material'])}")
        print(f"    {r.get('note', '')}")
    if args.csv:
        bom_to_csv(r["rows"], args.csv)
        print(f"  已导出 CSV：{args.csv}")
    return 0

def _cmd_selftest(args):
    """实机自检。逐项跑，任何一项失败就以非 0 退出。"""
    from .selftest import run_selftest

    def show(one):
        mark = "PASS" if one["ok"] else "FAIL"
        print(f"  [{mark}] {one['title']:<26} {one['elapsed_s']:>5.2f}s  {one['detail']}")

    if not args.json:
        print()
        print("  swforge 实机自检")
        print("  每一项都在真实 SolidWorks 上跑，读出结果再判定")
        print()

    r = run_selftest(work_dir=args.work_dir, only=args.only,
                     keep=args.keep,
                     progress=None if args.json else show)

    if args.json:
        print(_json_ascii(r))
        return 0 if r.get("ok") else 1

    print()
    if r.get("error"):
        print(f"  错误：{r['error']}")
        return 1
    print(f"  结果：{r['passed']} 通过 / {r['failed']} 失败"
          f"   耗时 {r['elapsed_s']:.1f}s")
    print(f"  环境：swforge {r['swforge']}  SolidWorks {r['sw_version']}")
    if r.get("work_dir"):
        print(f"  产物：{r['work_dir']}")
    if r.get("ok"):
        print("  全部通过 —— 本机这些能力都是实测可用的")
    else:
        failed = [x for x in r["results"] if not x["ok"]]
        print()
        print("  失败项说明：")
        for x in failed:
            print(f"    - {x['title']}：{x['detail']}")
            if x.get("why"):
                print(f"      这一项对应的问题：{x['why']}")
    return 0 if r.get("ok") else 1

def _cmd_capabilities(args):
    """本机能力自检。--api 时额外探测 Interop 支持的 API 清单。"""
    from .session import get_session

    out = {"swforge": ""}
    try:
        from . import __version__ as _v
        out["swforge"] = _v
    except Exception:                                     # noqa: BLE001
        pass
    out["python"] = sys.version.split()[0]
    out["platform"] = sys.platform

    # 连接信息（连不上也给结论，不要整条命令失败）
    try:
        ping = get_session().ping()
        out["sw"] = ping
        out["connected"] = bool(ping.get("ok"))
    except Exception as exc:                              # noqa: BLE001
        out["sw"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        out["connected"] = False

    if args.api:
        try:
            from .probe import probe_api
            probe = probe_api(sw_dir=args.sw_dir)
            out["api"] = probe
            # 顶层给个结论，方便一眼看出能不能用
            if probe.get("ok"):
                out["verdict"] = (
                    "本机支持完整功能" if not probe.get("missing")
                    else f"缺失 {len(probe['missing'])} 个 API，见 api.missing"
                )
            else:
                out["verdict"] = f"探测失败：{probe.get('error')}"
        except Exception as exc:                          # noqa: BLE001
            out["api"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            out["verdict"] = "探测异常"

    out["ok"] = out.get("connected", False)
    return _result(out)


def _cmd_batch(args):
    """批量出图：一个文件夹的零件 -> 一批带 GB 图框的工程图。"""
    import os as _os
    from .batch import batch_drawings, write_report

    def show(idx, total, item):
        bar = f"[{idx}/{total}]"
        name = _os.path.basename(item.model)
        if item.skipped:
            print(f"{bar} 跳过  {name}（图已存在）", flush=True)
        elif item.ok:
            extra = f"  尺寸 {item.dims}"
            if item.overall_done:
                extra += f"（总尺寸 {item.overall_done}）"
            if item.pdf_ok:
                extra += "  +PDF"
            print(f"{bar} ✓     {name}{extra}  {item.seconds:.1f}s", flush=True)
        else:
            print(f"{bar} ✗     {name}  {item.error[:80]}", flush=True)

    res = batch_drawings(
        args.folder,
        out_dir=args.out,
        pattern=args.pattern,
        recursive=args.recursive,
        paper=args.paper,
        overall=not args.no_overall,
        pdf=args.pdf,
        skip_existing=not args.no_skip_existing,
        limit=args.limit,
        max_documents=args.max_documents,
        progress=None if args.json else show,
    )

    if args.report:
        write_report(res, args.report)
        if not args.json:
            print(f"\n报告: {args.report}")

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    print()
    print(f"  合计 {res['total']} 个模型")
    print(f"  成功 {res['succeeded']}   失败 {res['failed']}   跳过 {res['skipped']}   PDF {res['pdf_ok']}")
    print(f"  耗时 {res['seconds']:.1f} 秒")
    if res["failed"]:
        print()
        print("  失败的：")
        for it in res["items"]:
            if not it["ok"]:
                print(f"    {_os.path.basename(it['model'])}: {it['error']}")
    return 0 if res["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    _make_output_safe()
    try:
        return _main(argv)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _p({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
