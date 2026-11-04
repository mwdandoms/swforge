# -*- coding: utf-8 -*-
"""MCP 服务器 —— 把 swforge 的能力暴露成 18 个标准工具。

启动
----
    python -m swforge.server          # stdio
    # 或在 DSH / Claude Desktop 的 MCP 配置里指向：
    #   command: <python>/Scripts/solidworks-swforge.exe

设计原则
--------
* **破坏性操作默认 dry-run**：`purge_*` 不传 `apply=true` 只列不删
* **所有工具返回 dict**，含 `ok` 字段；异常也包成 `{"ok": false, "error": ...}`
* **不重复 MechDog 的 29 个工程图工具** —— 它自己就是 MCP 服务器，
  两个都注册即可；本服务只补它没有的（建模 / 清理 / 排版 / 图集）
"""

from __future__ import annotations

import json
import os
import sys
import asyncio
from functools import wraps
from typing import Any

__all__ = ["mcp", "main"]

from .session import STAWorker

_WORKER = STAWorker()


def _err(exc: BaseException) -> dict:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_mcp():
    """构造 FastMCP 实例。延迟 import，没装 mcp 也能 import 本模块。"""
    from mcp.server.fastmcp import FastMCP

    # instructions 是 MCP 客户端（Claude Desktop / Cursor / Codex …）读到的第一段话，
    # 决定这个服务器 "别的智能体能不能用对"。空着等于让 Agent 自己猜。
    mcp = FastMCP(
        "swforge",
        instructions=(
            "swforge：驱动本机 SolidWorks 的机械设计工具箱（建模用 mm，工程图标注坐标用米）。\n"
            "\n"
            "使用前提：SolidWorks 必须已在用户桌面上运行并完成启动，否则工具会返回连接错误。\n"
            "\n"
            "推荐流程：\n"
            "1. 不确定参数时先调 sw_validate_part —— 它只校验不建文件，能立刻指出哪一项非法。\n"
            "2. sw_build_part 建模（spec 用 boxes/tubes/cylinders/revolves/fillets/chamfers）。\n"
            "3. sw_apply_colors 上色后一定用 sw_read_colors 回读，确认颜色真的写进去了。\n"
            "4. sw_produce_drawing 出工程图 → sw_layout_views 排版 → sw_export_pdf 导 PDF。\n"
            "\n"
            "重要约束：\n"
            "- SolidWorks 默认只允许同时打开 8 个文档。批量操作前先调 sw_resource_status，"
            "必要时 sw_sweep_documents 清场，否则会报文档数超限。\n"
            "- 材质用国标牌号（Q235 / Q355 / 45 / 40Cr …），用 sw_list_materials 查看可用牌号。\n"
            "- 所有工具返回 JSON，成功看 ok=true，失败看 error。\n"
            "- 公差与粗糙度须显式调用标注工具，不能自动推荐工艺要求；图纸仍需工程审核。\n"
            "- 标注工具只修改内存工程图；粗糙度坐标用米，Ra 用 μm，尺寸及公差偏差用 mm。\n"
            "\n"
            "This server drives a real SolidWorks instance. Model lengths and tolerance offsets are mm; annotation positions are metres. "
            "Every tool returns JSON with an ok field."
        ),
    )

    def tool():
        def register(fn):
            @wraps(fn)
            async def run_on_sta(*args, **kwargs):
                try:
                    return await asyncio.wrap_future(_WORKER.submit(fn, *args, **kwargs))
                except Exception as exc:
                    return _err(exc)
            mcp.tool()(run_on_sta)
            return run_on_sta
        return register

    @tool()
    def sw_add_surface_finish(drawing_path: str | None = None,
                              x: float | None = None, y: float | None = None,
                              ra: str = '3.2', symbol_type: str = 'machining',
                              view_name: str | None = None, prod_method: str = '',
                              edge_index: int | None = None, edge_fraction: float = .5,
                              leader: bool = False) -> dict:
        """添加粗糙度并回读类型、Ra、位置。坐标米，Ra μm；指定 view_name/edge_index 可原生附着直边，leader=True 加引线。

        不指定边时是独立图纸符号；省略坐标从视图右上角推算。只修改内存。
        """
        from .annotations import add_surface_finish
        return add_surface_finish(drawing_path, x=x, y=y, ra=ra, symbol_type=symbol_type,
                                  view_name=view_name, prod_method=prod_method, edge_index=edge_index,
                                  edge_fraction=edge_fraction, leader=leader)

    @tool()
    def sw_list_surface_edges(drawing_path: str | None = None, view_name: str | None = None) -> dict:
        """枚举指定视图的可见直边索引与图纸端点（米），供粗糙度显式附着；只读。"""
        from .annotations import list_surface_edges
        return {'ok': True, 'edges': list_surface_edges(drawing_path, view_name)}

    @tool()
    def sw_add_surface_finishes(finishes: list[dict], drawing_path: str | None = None) -> dict:
        """批量添加明确指定的粗糙度。每项 x/y 为米、ra 为 μm，可指定 view_name；只修改内存。"""
        from .annotations import add_surface_finishes
        return add_surface_finishes(drawing_path, finishes)

    @tool()
    def sw_list_dimensions(drawing_path: str | None = None) -> dict:
        """枚举当前图纸的尺寸完整名称、视图和毫米值，用于唯一定位公差对象。只读。"""
        from .annotations import list_dimensions
        return {'ok': True, 'dimensions': list_dimensions(drawing_path)}

    @tool()
    def sw_set_tolerance(drawing_path: str | None = None, dim_name: str | None = None,
                         dim_value: float | None = None, view_name: str | None = None,
                         tol_type: str = 'symmetric', upper: float | None = None,
                         lower: float | None = None, fit: str | None = None) -> dict:
        """应用明确给定的线性尺寸公差，偏差用 mm；支持 symmetric/bilateral/limit/fit/none。

        必须唯一匹配。配合如 H7/g6，不自动推荐等级。回读并核对名义值；只修改内存。
        """
        from .annotations import set_tolerance
        return set_tolerance(drawing_path, dim_name=dim_name, dim_value=dim_value,
                             view_name=view_name, tol_type=tol_type, upper=upper,
                             lower=lower, fit=fit)

    @tool()
    def sw_list_mate_faces(assembly_path: str | None = None, component: str | None = None,
                           kind: str | None = None) -> dict:
        """只读枚举装配顶层零件的圆柱面/平面，坐标和半径用mm，含持久面引用与装配坐标。"""
        from .mate_faces import list_mate_faces
        return list_mate_faces(assembly_path,component=component,kind=kind)

    @tool()
    def sw_apply_face_mates(mates: list[dict], assembly_path: str | None = None) -> dict:
        """按明确的 face_a/face_b 持久引用建立 concentric/coincident 配合，回读面身份与轴距/平面间距。

        不要求同心孔轴半径相等，不自动替换目标面。失败尝试回退本批次新配合；只改内存，需另行保存。
        """
        from .mate_faces import apply_face_mates
        return apply_face_mates(assembly_path,mates=mates)

    @tool()
    def sw_inspect_face_mates(mates: list[dict], assembly_path: str | None = None) -> dict:
        """只读核对明确面的原生配合、实体身份及几何误差；用于保存重开验证，线性单位mm。"""
        from .mate_faces import inspect_face_mates
        return inspect_face_mates(assembly_path,mates=mates)

    # ------------------------------------------------------------------ 会话
    @tool()
    def sw_ping() -> dict:
        """连接探针：返回 SolidWorks 版本、往返延迟、重连与脏缓存统计。"""
        try:
            from .session import get_session

            return {"ok": True, **get_session().ping()}
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_capabilities() -> dict:
        """本机能力自检：SW 是否可用、MechDog 是否可用、Python 版本。"""
        try:
            from .drawing import have_mechdog
            from .session import get_session

            from . import __version__
            info = {"ok": True, "swforge": __version__,
                    "python": sys.version.split()[0], "mechdog": have_mechdog(),
                    "geometry": ["box", "tube_x", "tube_y", "tube_z",
                                 "cylinder", "revolve_y", "fillet", "chamfer"],
                    "execution": "serialized STA worker",
                    "default_max_documents":8,"default_keep_open":False,
                    "default_drawing_annotations":False,"pdf_validation":"pdfium"}
            try:
                info["sw"] = get_session().ping()
            except Exception as exc:                     # noqa: BLE001
                info["sw"] = {"ok": False, "error": str(exc)}
            return info
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_close_all(discard_unsaved: bool = False) -> dict:
        """关闭已保存且未修改的文档。discard_unsaved=True 才会丢弃未保存更改。"""
        try:
            from .session import get_session

            return {"ok": True, "closed": get_session().close_all(discard_unsaved=discard_unsaved),
                    "discard_unsaved": discard_unsaved}
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    # ------------------------------------------------------------------ 建模
    @mcp.tool()
    def sw_validate_part(out_path: str, spec: dict) -> dict:
        """只校验建模描述，不连接 SW、不创建文件。支持圆柱/绕 Y 旋转/按 tag 圆角倒角。"""
        try:
            from .spec import builder_from_spec
            builder = builder_from_spec(out_path, spec)
            return {"ok": True, "validated": True, "path": builder.path,
                    "source_bytes": len(builder.render_cs().encode("utf-8"))}
        except Exception as exc:
            return _err(exc)

    @tool()
    def sw_build_part(out_path: str, spec: dict, paint: bool = True,
                      keep_open: bool = False, max_documents: int = 8) -> dict:
        """按 spec 建零件。

        spec 格式::

            {"material": "Q235",
             "boxes": [{"tag":"底板","x0":-150,"x1":150,"y0":0,"y1":12,
                        "z0":-100,"z1":100,"color":"steel"}],
             "tubes": [{"tag":"立柱","axis":"y","y0":12,"y1":812,
                        "cx":0,"cz":0,"sx":40,"sz":40,"wall":4,"color":"yellow"}]}

        v0.3 另支持 cylinders [{tag,axis,x,y,z,r,h,color}]、
        revolves [{tag,profile_pts:[[radius,axial],...],axis:"y",angle:360,x,y,z,color}]、
        fillets [{tag,r}]、chamfers [{tag,d}]。所有长度为 mm。
        """
        try:
            from .spec import builder_from_spec

            b = builder_from_spec(out_path, spec)
            r = b.build(paint=paint,keep_open=keep_open,max_documents=max_documents)
            d = dict(r.__dict__)
            d["ok"] = r.ok
            return d
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_list_colors() -> dict:
        """可用的预置配色名称。"""
        from .modeling import COLORS

        return {"ok": True, "colors": {k: list(v) for k, v in COLORS.items()}}

    # ------------------------------------------------------------------ 分色
    @tool()
    def sw_apply_colors(part_path: str, rules: list, dry_run: bool = False) -> dict:
        """按规则给零件上色（面级写入 + 回读验证）。

        rules 每项::

            {"name": "轮子", "color": [0.10,0.10,0.11], "cond": {"ymax_lt": -560}}
        """
        try:
            from .colors import FaceRule, apply_rules

            rs = [FaceRule(r["name"], tuple(r["color"]), **r.get("cond", {}))
                  for r in rules]
            return apply_rules(part_path, rs, dry_run=dry_run)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_read_colors(sample: int = 12) -> dict:
        """回读当前文档若干面的颜色，用于验证上色是否真的生效。"""
        try:
            from .colors import read_back

            return {"ok": True, "faces": read_back(sample=sample)}
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    # ------------------------------------------------------------------ 体检
    @tool()
    def sw_survey(include_boxes: bool = False, top_n: int = 20) -> dict:
        """当前文档的包络与实体构成（实体数 / 曲面数 / 最大体清单）。"""
        try:
            from .cleanup import survey

            return survey(include_boxes=include_boxes, top_n=top_n)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_purge_giant(threshold_mm: float = 5000.0, apply: bool = False) -> dict:
        """删掉最大边长超阈值的垃圾体（默认只列不删）。

        典型场景：STEP 里混进 6 km 级方块，导致「缩放到适合」后模型变成一点。
        """
        try:
            from .cleanup import purge_giant
            from .session import get_session

            md = get_session().sw().ActiveDoc
            if md is None:
                return {"ok": False, "error": "没有打开的文档"}
            return purge_giant(md, threshold_mm, dry_run=not apply)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_purge_small(max_dim_mm: float = 120.0, min_y_mm: float | None = None,
                       apply: bool = False) -> dict:
        """删掉零碎小体（导入碎片）。默认只列不删。"""
        try:
            from .cleanup import purge_small
            from .session import get_session

            md = get_session().sw().ActiveDoc
            if md is None:
                return {"ok": False, "error": "没有打开的文档"}
            return purge_small(md, max_dim_mm, min_y_mm, dry_run=not apply)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    # ------------------------------------------------------------------ 出图
    @tool()
    def sw_produce_drawing(model_path: str, out_path: str | None = None,
                           paper: str = "A3", annotations: bool = False,
                           keep_open: bool = False, max_documents: int = 8,
                           template: str | None = None) -> dict:
        """一条命令出工程图（委托 MechDog；未安装时降级为三视图）。"""
        try:
            from .drawing import produce

            return produce(model_path, out_path, paper,annotations=annotations,
                           keep_open=keep_open,max_documents=max_documents,template=template)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_layout_views(drawing_path: str | None = None, gap_mm: float = 35.0,
                        auto_scale: bool = True, dry_run: bool = False) -> dict:
        """按 GB 惯例重排视图：长对正 / 高平齐 / 间距 ≥ 35 mm。"""
        try:
            from .drawing import normalize_layout

            return normalize_layout(drawing_path, gap_mm=gap_mm,
                                    auto_scale=auto_scale, dry_run=dry_run)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_export_pdf(drawing_path: str, pdf_path: str | None = None) -> dict:
        """把工程图导出为 PDF。"""
        try:
            from .drawing import export_pdf

            return export_pdf(drawing_path, pdf_path, "pdf")
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_make_atlas(pages: list, out_pdf: str, title: str = "技术图集",
                      subtitle: str = "", paper: str = "A3") -> dict:
        """把「文字页 + 图片页」拼成多页 PDF 图集。

        pages 每项::

            {"type": "cover/text/image",
             "title": "一、说明", "lines": ["■ 标题", "正文"],
             "image": "D:/xxx.png"}
        """
        try:
            from .drawing import make_atlas

            return make_atlas(pages, out_pdf, title=title,
                              subtitle=subtitle, paper=paper)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_delivery_check(drawing_path: str, model_path: str | None = None,
                          strict_attachments: bool = True) -> dict:
        """这张图能不能交（需 MechDog）。"""
        try:
            from .drawing import delivery_check

            return delivery_check(drawing_path,model_path,strict_attachments)
        except Exception as exc:                         # noqa: BLE001
            return _err(exc)

    @tool()
    def sw_resources() -> dict:
        """只读列出 SW 文档、保存状态、进程与工作集内存。"""
        from .resources import document_inventory
        return document_inventory()

    @tool()
    def sw_list_materials() -> dict:
        """列出内置 GB 牌号（密度/弹性模量/泊松比）与材质库路径。"""
        from .gb_materials import GB_MATERIALS, library_path
        return {"ok": True,
                "count": len(GB_MATERIALS),
                "grades": [{"grade": n, "density_kg_m3": v[0], "elastic_pa": v[1],
                            "poisson": v[2], "note": v[3]}
                           for n, v in sorted(GB_MATERIALS.items())],
                "library": library_path()}

    @tool()
    def sw_ensure_material_library(force: bool = False) -> dict:
        """生成 GB 材质库到 SW 扫描目录，返回路径。

        SW 自带中文库没有 GB 钢牌号；不生成时 material='Q235' 会静默失败，
        零件退回默认密度 1000 kg/m3（水），质量算错约 7.85 倍。
        """
        from .gb_materials import ensure_library, library_path, material_names
        path = ensure_library(force=force)
        import os
        return {"ok": True, "library": path, "bytes": os.path.getsize(path),
                "grades": material_names(), "default_path": library_path()}

    @tool()
    def sw_resource_status(limit: int = 8, warn_ratio: float = 0.75,
                           mem_warn_mb: float = 2500.0) -> dict:
        """SW 文档数量/内存健康检查。

        返回 level = ok / warn / critical：
        ok 正常；warn 已到告警线（默认 6/8）或内存超阈值；
        critical 已达上限，再建文档会被拒绝。只读，不关闭任何文档。
        """
        from .resources import resource_status
        return resource_status(limit=limit, warn_ratio=warn_ratio,
                               mem_warn_mb=mem_warn_mb)

    @tool()
    def sw_sweep_documents(apply: bool = False, keep: list | None = None) -> dict:
        """关闭遗留的临时/测试文档（默认只列不关）。

        只匹配 pytest 目录、swforge_it 目录和系统临时目录下的文档；
        用户打开的工作文档和有未保存修改的文档不会被关闭。
        """
        from .resources import sweep_documents
        return sweep_documents(dry_run=not apply, keep=keep or ())

    @tool()
    def sw_preview_edges(part_path: str, tag: str, edges_rule: dict | None = None) -> dict:
        """只读预览实体选边规则；长度单位 mm，带规则时仅匹配直边。"""
        from .modeling import preview_edges
        return preview_edges(part_path,tag,edges_rule)

    # 让 serverInfo.version 报 swforge 自己的版本。
    # FastMCP 构造参数里没有 version，底层 Server 的 version 默认是 None，
    # 于是 MCP 客户端看到的是 SDK 版本（1.30.0）—— 排查问题时会被误导。
    try:
        from . import __version__ as _ver
        inner = getattr(mcp, "_mcp_server", None)
        if inner is not None:
            inner.version = _ver
    except Exception:                                     # noqa: BLE001
        pass

    return mcp


try:                                          # 供 `from swforge.server import mcp`
    mcp = build_mcp()
except ModuleNotFoundError as exc:
    if exc.name != "mcp":
        raise
    mcp = None


def main() -> int:
    if mcp is None:
        print("未安装 mcp 包，请先 pip install \"swforge[mcp]\"", file=sys.stderr)
        return 1
    try:
        mcp.run()
    finally:
        _WORKER.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

