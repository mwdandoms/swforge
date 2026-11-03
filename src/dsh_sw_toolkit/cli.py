# -*- coding: utf-8 -*-
"""命令行入口：`dsh-sw <子命令>`"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _p(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _result(obj) -> int:
    _p(obj)
    return 1 if isinstance(obj, dict) and obj.get("ok") is False else 0


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dsh-sw", description="SolidWorks 自动化工具箱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping", help="连接探针")
    sub.add_parser("survey", help="量当前文档的包络与实体构成")
    sub.add_parser("capabilities", help="本机能力自检")
    p = sub.add_parser("materials", help="列出内置 GB 牌号并生成/校验 SW 材质库")
    p.add_argument("--ensure", action="store_true", help="生成材质库并返回路径")
    p.add_argument("--force", action="store_true", help="强制重新生成")

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

    if args.cmd == "ping":
        from .session import get_session

        return _result(get_session().ping())

    if args.cmd == "survey":
        from .cleanup import survey

        return _result(survey())

    if args.cmd == "capabilities":
        from .drawing import have_mechdog

        info = {
            "dsh_sw_toolkit": __import__("dsh_sw_toolkit").__version__,
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


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _p({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
