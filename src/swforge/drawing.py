# -*- coding: utf-8 -*-
"""工程图流水线与图集输出。

分工
----
* **标注**交给 AssetMate_MechDog（29 个工程图工具，原生尺寸/公差/
  形位公差/粗糙度/孔标注/BOM 明细栏/交付自检），本包不重复造轮子。
* **排版与成册**由本包负责：MechDog 自动布局在 4 视图以上会挤在一起，
  这里提供 `normalize_layout()` 按 GB 的「长对正、高平齐」重排，
  再用 `make_atlas()` 拼成多页 PDF 图集。

没装 MechDog 时，`produce()` 会退回「只建三视图」的最小实现，
并在结果里标记 `degraded=True`，避免让人误以为标注齐全。
"""

from __future__ import annotations

import os
import json
import math
import tempfile

__all__ = ["have_mechdog", "produce", "export_pdf", "normalize_layout",
           "add_dimensions", "count_dimensions",
           "make_atlas", "delivery_check"]

_DEGRADED_NOTE = (
    "未安装 solidworks-assetmate-mechdog，只生成三视图、无尺寸/公差/粗糙度。"
    "安装：pip install swforge[mechdog]"
)


def _value(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) and not hasattr(value, "_oleobj_") else value


def _drawing_document(sw, path=None):
    md = sw.ActiveDoc
    if path:
        target = os.path.normcase(os.path.abspath(path))
        current = str(_value(md, "GetPathName")) if md else ""
        if os.path.normcase(os.path.abspath(current)) != target:
            md = sw.OpenDoc(target, 3)
            sw.ActivateDoc(target)
            md = sw.ActiveDoc
        if md is None or os.path.normcase(os.path.abspath(str(_value(md, "GetPathName")))) != target:
            raise RuntimeError(f"打不开指定工程图：{path}")
    if md is None or _value(md, "GetType") != 3:
        raise RuntimeError("当前文档不是工程图，请先打开或传入 drawing_path")
    return md


# ---------------------------------------------------------------- 自动标注（v0.6）
# swInsertAnnotation_e 位掩码
_INS_DIMS              = 8          # swInsertDimensions
_INS_DIMS_MARKED       = 32768      # swInsertDimensionsMarkedForDrawing
_INS_DIMS_NOT_MARKED   = 524288     # swInsertDimensionsNotMarkedForDrawing
_INS_HOLES             = 1048576    # swInsertholeCallout
_INS_CENTERMARKS       = 1          # swInsertCThreads（中心标记/螺纹）


def _wrap_view(obj):
    """把原生 PyIDispatch 包成可用的 CDispatch。"""
    if obj is None or hasattr(obj, "GetNextView"):
        return obj
    import win32com.client

    return win32com.client.Dispatch(obj)


def _view_list(md):
    """返回当前图纸的 [(视图对象, 名字)]，跳过图纸本身。

    用 GetFirstView 的链表而不是 GetViews：后者返回「每张图纸一组」的嵌套元组，
    组内元素是原生 PyIDispatch，属性访问会抛异常，容易静默丢视图。
    """
    sheet_view = _wrap_view(_value(md, "GetFirstView"))
    current = _wrap_view(_value(sheet_view, "GetNextView")) if sheet_view else None
    out = []
    guard = 0
    while current is not None and guard < 30:
        guard += 1
        try:
            out.append((current, str(_value(current, "Name"))))
        except Exception:                                # noqa: BLE001
            pass
        nxt = _value(current, "GetNextView")
        current = _wrap_view(nxt) if nxt is not None else None
    return out


def _ensure_mm_units(md) -> dict:
    """把工程图单位强制为毫米（+2 位小数）。返回改前/改后的单位值。"""
    # swUserPreferenceIntegerValue_e: swUnitsLinear=47, swUnitsLinearDecimalPlaces=49
    # swLengthUnit_e: swMM=0, swINCHES=3
    out = {"before": None, "after": None, "changed": False, "unit": "unknown"}
    try:
        # 注意：GetUserPreferenceInteger 必须带 (枚举值, 配置) 两个参数，
        # 用 _value() 无参调用会报「非选择性的参数」——v0.7 就踩在这里。
        ext = _value(md, "Extension")
        before = int(ext.GetUserPreferenceInteger(47, 0) or 0)   # 47 = swUnitsLinear
        out["before"] = before
        if before != 0:
            ext.SetUserPreferenceInteger(47, 0, 0)               # 0 = swMM
            ext.SetUserPreferenceInteger(49, 0, 2)               # 49 = 小数位
            out["changed"] = True
        after = int(ext.GetUserPreferenceInteger(47, 0) or 0)
        out["after"] = after
        out["unit"] = {0: "mm", 1: "cm", 2: "m", 3: "inch", 4: "feet"}.get(after, str(after))
    except Exception as exc:                             # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def count_dimensions(drawing_path: str | None = None) -> dict:
    """统计当前图纸每个视图的尺寸数量（只读）。"""
    from .session import get_session

    sw = get_session().sw()
    md = _drawing_document(sw, drawing_path)
    rows = []
    for view, name in _view_list(md):
        try:
            n = int(_value(view, "GetDimensionCount4") or 0)
        except Exception:                                # noqa: BLE001
            n = 0
        rows.append({"view": name, "dimensions": n})
    return {"ok": True, "views": rows,
            "total": sum(r["dimensions"] for r in rows)}


def add_dimensions(drawing_path: str | None = None, all_views: bool = True,
                   holes: bool = True, center_marks: bool = False,
                   duplicate: bool = False, relayout: bool = True,
                   overall: bool = False) -> dict:
    """把模型里的驱动尺寸自动插进工程图（v0.6 新增）。

    这是「基础三视图只能看形状，不能制造」这个缺口的直接补法：
    调用 `InsertModelAnnotations4` 把模型的驱动尺寸批量带进视图。

    参数
    ----
    all_views    True 时所有视图都插，False 只插当前选中视图
    holes        是否带孔标注
    center_marks 是否带中心标记
    duplicate    是否允许重复标注

    返回
    ----
    dict，含 before / after 的尺寸数量与本次增量。
    注意：**不会自动加公差和粗糙度** —— 那些属于设计决策，不自动编造。
    """
    from .session import get_session

    sw = get_session().sw()
    md = _drawing_document(sw, drawing_path)
    before = count_dimensions(drawing_path)

    types = _INS_DIMS | _INS_DIMS_MARKED | _INS_DIMS_NOT_MARKED
    if holes:
        types |= _INS_HOLES
    if center_marks:
        types |= _INS_CENTERMARKS

    # 单位统一成毫米：模板若继承英制，自动标注会显示成 inch（3.94 而不是 100）
    units = _ensure_mm_units(md)
    err = ""
    try:
        md.ClearSelection2(True)
    except Exception:                                    # noqa: BLE001
        pass
    try:
        # InsertModelAnnotations4(Option, Types, AllViews, DuplicateDims,
        #   HiddenFeatureDims, UsePlacementInSketch, InsertAllAnnotations,
        #   InsertAllReferenceGeometry)
        md.InsertModelAnnotations4(0, types, bool(all_views), bool(duplicate),
                                   False, True, False, False)
    except Exception as exc:                             # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"

    # 可选：补总长/总高。
    # InsertModelAnnotations4 只插模型驱动尺寸且跨视图去重（上限约 18 个），
    # 拿不到总尺寸，所以总尺寸必须由 dims 模块显式建。
    overall_result = None
    if overall:
        try:
            from .dims import add_overall_dimensions
            overall_result = add_overall_dimensions(drawing_path)
        except Exception as exc:                         # noqa: BLE001
            overall_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    after = count_dimensions(drawing_path)
    # 标注带上尺寸线后会改变视图外廓，重排一次避免压几何/出界
    layout = None
    if relayout:
        try:
            layout = normalize_layout(drawing_path)
        except Exception as exc:                         # noqa: BLE001
            layout = {"ok": False, "error": str(exc)}
    return {
        "ok": not err,
        "error": err,
        "before": before["total"],
        "after": after["total"],
        "added": after["total"] - before["total"],
        "views": after["views"],
        "units": units,
        "overall": overall_result,
        "layout": layout,
        "note": "自动标注只插入模型驱动尺寸；公差与粗糙度需人工补，不自动编造",
    }


def _close_open_document(path: str) -> bool:
    """关掉指向 path 的已打开文档，避免重复出图时被文件锁挡住。

    返回是否真的关掉了。找不到对应文档、或关闭失败，都返回 False，
    让后续 SaveAs 自己报错 —— 比静默吞掉更安全。
    """
    from .session import get_session, _value

    wanted = os.path.normcase(os.path.abspath(path))
    try:
        sw = get_session().sw()
        docs = _value(sw, "GetDocuments") or []
    except Exception:                                     # noqa: BLE001
        return False

    closed = False
    for doc in docs:
        try:
            title = str(_value(doc, "GetPathName") or "")
            if title and os.path.normcase(os.path.abspath(title)) == wanted:
                sw.CloseDoc(title)
                closed = True
        except Exception:                                 # noqa: BLE001
            continue
    return closed


def _save_as(md, path):
    from win32com.client import VARIANT
    import pythoncom

    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    # ExportData is an IDispatch pointer. Python None alone becomes VT_EMPTY
    # and some SW type libraries reject it with DISP_E_TYPEMISMATCH.
    export_data = VARIANT(pythoncom.VT_DISPATCH, None)
    if str(path).lower().endswith('.pdf'):
        from .session import get_session
        export_data=get_session().sw().GetExportFileData(1)
        names=list(_value(md,'GetSheetNames'))
        if not export_data.SetSheets(3,VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,names)):
            raise RuntimeError('PDF 导出图纸范围设置失败')
        export_data.ViewPdfAfterSaving=False
        export_data.ExportAs3D=False
    ok = bool(md.Extension.SaveAs(path, 0, 1, export_data, err, warn))
    return ok and err.value == 0, int(err.value), int(warn.value)


def _vt_pt(x: float, y: float):
    """把 (x, y) 包成 VARIANT(VT_ARRAY|VT_R8)。

    `IView.Position` 是**属性写**，直接赋元组会静默失败（moved=0 但不报错），
    必须走 DISPATCH_PROPERTYPUT + VARIANT 数组。
    """
    from win32com.client import VARIANT
    import pythoncom

    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(x), float(y)])


def have_mechdog() -> bool:
    try:
        import solidworks_assetmate_mechdog.tools.pipeline  # noqa: F401
        return True
    except Exception:                                    # noqa: BLE001
        return False


# ---------------------------------------------------------------------- 出图
def produce(model_path: str, out_path: str | None = None, paper: str = "A3",
            views: list[str] | None = None, *, annotations=False, template=None,
            keep_open=True, max_documents=8) -> dict:
    """Create a native views-only drawing by default; annotation pipeline is opt-in."""
    from .resources import document_scope
    if not annotations and os.path.splitext(model_path)[1].lower()!='.sldprt':
        raise ValueError('基础三视图模式目前仅验证 .SLDPRT；装配图尚未纳入本版验收')
    target=os.path.abspath(out_path or os.path.splitext(model_path)[0]+"_AI出图.SLDDRW")
    if not target.lower().endswith(".slddrw"):
        raise ValueError("工程图输出必须使用 .SLDDRW 扩展名")
    # 同一路径重复出图会撞车：实测连跑两次，第一次 err=0，第二次 err=1。
    # 原因是上一张图还开在 SolidWorks 里，文件被锁，SaveAs 写不进去。
    # 所以出图前先把「指向同一路径的已打开文档」关掉，再删旧文件。
    _close_open_document(target)
    if os.path.isfile(target):
        try:
            os.remove(target)
        except OSError:
            pass
    if template is not None and (not os.path.isfile(template) or not str(template).lower().endswith(".drwdot")):
        raise ValueError("template 必须是存在的 .drwdot 文件")
    with document_scope(target,keep_open=keep_open,max_documents=max_documents,
                        log_path=target+".operations.jsonl",related_paths=[model_path]) as lease:
        result=_produce(model_path,target,paper,views,annotations=annotations,template=template,lease=lease)
        lease.failed=not result.get('ok',False)
        result["ready_for_manufacture"]=False
        result["review_required"]=True
        return result


def _produce(model_path: str, out_path: str | None = None, paper: str = "A3",
             views=None, *, annotations=False, template=None, lease=None) -> dict:
    """一条命令出图：台账 → 规划 → 建图 → 标注 → 自检。"""
    model_path = os.path.abspath(model_path)
    if not os.path.isfile(model_path):
        raise ValueError(f"模型文件不存在：{model_path}")
    paper = paper.upper()
    paper_sizes = {"A0": 11, "A1": 10, "A2": 9, "A3": 8, "A4": 6}
    if paper not in paper_sizes:
        raise ValueError("纸张必须为 A0~A4")
    if out_path is None:
        base = os.path.splitext(model_path)[0]
        out_path = base + "_AI出图.SLDDRW"

    if annotations:
        if template is not None:
            raise ValueError("MechDog 标注流水线不支持指定模板；请使用基础三视图模式")
        if not have_mechdog():
            raise RuntimeError("annotations=True 需要 MechDog")
        from solidworks_assetmate_mechdog.tools import pipeline

        r = pipeline.produce_drawing(
            model_path, output_path=out_path, paper=paper,
            views=views or ["front", "top", "right"],
        )
        r = dict(r) if isinstance(r, dict) else {"raw": r}
        r["degraded"] = False
        r["engine"] = "mechdog"
        r["annotations_requested"] = True
        return r

    # ---- 降级路径：只建三视图
    from .session import get_session

    sess = get_session()
    sw = sess.sw()
    if views and views != ["front", "top", "right"]:
        raise ValueError("内置出图仅支持 front/top/right；其他视图需 MechDog")
    template = template or _default_template("drawing", paper)
    if not template:
        raise RuntimeError("找不到工程图模板，请设置 SW_TEMPLATE_DIR")
    md = sw.NewDocument(
        template, paper_sizes[paper], 0, 0,
    )
    if md is None:
        raise RuntimeError("新建工程图失败")
    if lease is not None:
        lease.own(md)
    view = md.CreateDrawViewFromModelView3(model_path, "*前视", 0.18, 0.20, 0)
    top = md.CreateDrawViewFromModelView3(model_path, "*上视", 0.18, 0.10, 0)
    right = md.CreateDrawViewFromModelView3(model_path, "*右视", 0.36, 0.20, 0)
    if view is None or top is None or right is None:
        return {"ok": False, "engine": "builtin", "degraded": True,
                "error": "未能创建完整三视图，未保存工程图"}
    _value(md, "EditRebuild3")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    ok, err, warn = _save_as(md, out_path)
    return {
        "ok": bool(ok) and os.path.isfile(out_path) and os.path.getsize(out_path) > 0,
        "err": err, "warn": warn,
        "drawing": out_path,
        "engine": "builtin",
        "degraded": False,
        "annotations_requested": False,
        "template": template,
        "note": "基础三视图；未自动拟定尺寸、公差或粗糙度，需设计审核",
        "first_view": str(view) if view else None,
    }


_PAPER_SIZES = ("a0", "a1", "a2", "a3", "a4", "a4p")


def _template_dirs():
    """按已装 SW 版本定位模板目录，不写死年份。"""
    import glob

    out = []
    env = os.environ.get("SW_TEMPLATE_DIR")
    if env:
        out.append(env)
    base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    for vendor in ("SOLIDWORKS", "SolidWorks"):
        for d in sorted(glob.glob(os.path.join(base, vendor, "SOLIDWORKS *", "templates")),
                        reverse=True):
            out.append(d)
    for letter in ("E", "D", "C", "F"):
        out.append(letter + r":\SW2025\SOLIDWORKS\data\templates")
        for d in sorted(glob.glob(letter + r":\SW*\SOLIDWORKS\data\templates"), reverse=True):
            out.append(d)
    out.append(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\data\templates")
    seen, uniq = set(), []
    for d in out:
        k = os.path.normcase(os.path.abspath(d))
        if k not in seen and os.path.isdir(d):
            seen.add(k)
            uniq.append(d)
    return uniq


def _default_template(kind="drawing", paper="A3"):
    """找一个可用的工程图模板。

    优先顺序（v0.8 修正）：
    1. ``gb_<纸张>.drwdot`` —— 中文 GB 模板，带图框标题栏、毫米单位
    2. 其它纸张的中文 GB 模板
    3. ``Drawing.drwdot`` —— 英文模板，英制且常无图框，仅在没有中文模板时使用

    v0.7 把英文 ``GB.drwdot`` 排在最前，导致出的图是英寸且没有图框。
    """
    dirs = _template_dirs()
    if kind == "assembly":
        for d in dirs:
            for name in ("gb_assembly.asmdot", "Assembly.asmdot"):
                cand = os.path.join(d, name)
                if os.path.isfile(cand):
                    return cand
        return ""

    want = str(paper).lower()
    order = [want] + [x for x in _PAPER_SIZES if x != want]
    for size in order:
        for d in dirs:
            for name in ("gb_" + size + ".drwdot", "gb_" + size.upper() + ".drwdot"):
                cand = os.path.join(d, name)
                if os.path.isfile(cand):
                    return cand
    for d in dirs:
        for name in ("GB.drwdot", "Drawing.drwdot"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
    return ""


def template_warnings(template):
    """模板是否具备 GB 图框与毫米单位，返回告警列表。"""
    out = []
    if not template:
        return ["没有可用工程图模板"]
    if not os.path.basename(template).lower().startswith("gb_"):
        out.append("模板不是中文 GB 模板，可能是英制且没有 GB 图框")
    return out


def export_pdf(drawing_path: str, pdf_path: str | None = None,
               fmt: str = "pdf") -> dict:
    """导出工程图到 PDF / DWG / DXF。"""
    fmt = fmt.lower()
    if fmt not in {"pdf", "dwg", "dxf"}:
        raise ValueError("导出格式必须是 pdf、dwg 或 dxf")
    if pdf_path is None:
        pdf_path = os.path.splitext(drawing_path)[0] + "." + fmt
    from .session import get_session

    sw = get_session().sw()
    md = _drawing_document(sw, drawing_path)
    pdf_path = os.path.abspath(pdf_path)
    if os.path.normcase(pdf_path) == os.path.normcase(os.path.abspath(drawing_path)):
        raise ValueError("导出路径不能覆盖源工程图")
    if os.path.splitext(pdf_path)[1].lower() != "." + fmt:
        raise ValueError("导出文件扩展名与 fmt 不一致")
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".swforge_export_", suffix="." + fmt,
                                     dir=os.path.dirname(pdf_path))
    os.close(fd)
    try:
        md.ClearSelection2(True)
        sw_ok, err, warn = _save_as(md, temporary)
        ok = sw_ok and os.path.isfile(temporary) and os.path.getsize(temporary) > 0
        validation=None
        if fmt == "pdf" and os.path.getsize(temporary)>0:
            validation=_validate_pdf(temporary,len(_value(md,'GetSheetNames')))
            ok=ok and validation['ok']
        if ok:
            os.replace(temporary, pdf_path)
        result={"ok": bool(ok), "path": pdf_path, "fmt": fmt,
                "err": err, "warn": warn,
                "sw_reported_ok":bool(sw_ok),"validation":validation,
                "error": "" if ok else "导出失败或未生成有效的新文件，原输出文件已保留"}
        from datetime import datetime,timezone
        with open(pdf_path+'.operations.jsonl','a',encoding='utf-8') as stream:
            stream.write(json.dumps({"time_utc":datetime.now(timezone.utc).isoformat(),
                "operation":"export","source":os.path.abspath(drawing_path),**result},ensure_ascii=False)+'\n')
        return result
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate_pdf(path,expected_pages):
    """Independently open every page; header alone is not sufficient."""
    try:
        import pypdfium2 as pdfium
        doc=pdfium.PdfDocument(path)
        try:
            count=len(doc)
            if count!=expected_pages or count<1:
                raise ValueError(f'页数 {count} 与图纸数 {expected_pages} 不一致')
            for index in range(count):
                page=doc[index]
                try:
                    if min(page.get_size())<=0:
                        raise ValueError('页面尺寸无效')
                    bitmap=page.render(scale=0.15)
                    bitmap.close()
                finally:
                    page.close()
            return {"ok":True,"page_count":count,"engine":"pdfium","all_pages_rendered":True}
        finally:
            doc.close()
    except Exception as exc:
        return {"ok":False,"error":str(exc),"note":"PDF 验证需要安装 .[pdf] 可选依赖"}


def delivery_check(drawing_path: str, model_path: str | None = None,
                   strict_attachments: bool = True) -> dict:
    """这张图能不能交。"""
    if have_mechdog():
        from solidworks_assetmate_mechdog.tools import drawing as mech
        if not model_path:
            from .session import get_session
            md=_drawing_document(get_session().sw(),drawing_path)
            first=_value(md,"GetFirstView")
            view=_value(first,"GetNextView")
            if view is not None:
                model_path=str(_value(view,"GetReferencedModelName"))
        if not model_path:
            return {"ok":False,"verdict":"UNKNOWN","ready_for_manufacture":False,
                    "error":"无法确定源模型，请传入 model_path"}
        result=mech.delivery_check(model_path,drawing_path,strict_attachments=strict_attachments)
        # Readiness is separate from successful execution of the audit.
        result["ready_for_manufacture"]=bool(result.get("ok") and result.get("verdict")=="可制造"
                                            and not result.get("blockers") and not result.get("pending"))
        return result
    return {"ok": False, "verdict": "UNKNOWN",
            "note": "需要 solidworks-assetmate-mechdog 才能做交付自检"}


# ---------------------------------------------------------------------- 排版
def normalize_layout(drawing_path: str | None = None,
                     gap_mm: float = 35.0, iso: bool = True,
                     auto_scale: bool = True, margin_ratio: float = 0.05,
                     title_block_reserve: float = 0.20,
                     dry_run: bool = False) -> dict:
    """重排当前 sheet 的 1~4 个标准视图，保留实际轮廓间距。

    主/俯视 X 相同，主/右视 Y 相同。标题栏保留为右侧安全带。
    使用 GetOutline 的完整边界，不再扣除与模板相关的经验常数。
    超过四视图或无法量取边界时返回失败，不部分改动图纸。
    """
    for name, value in (("gap_mm", gap_mm), ("margin_ratio", margin_ratio),
                        ("title_block_reserve", title_block_reserve)):
        if not math.isfinite(value):
            raise ValueError(f"{name} 必须是有限数")
    if gap_mm < 0 or not 0 <= margin_ratio < 0.5 or not 0 <= title_block_reserve < 1:
        raise ValueError("间距必须非负，margin_ratio 为 0~0.5，标题栏比例为 0~1（不含上限）")
    from .session import get_session

    md = _drawing_document(get_session().sw(), drawing_path)

    def wrap(obj):
        if obj is None or hasattr(obj, "GetNextView"):
            return obj
        import win32com.client
        return win32com.client.Dispatch(obj)

    sheet = _value(md, "GetCurrentSheet")
    props = _value(sheet, "GetProperties")
    pw, ph = float(props[5]), float(props[6])
    if not all(math.isfinite(x) and x > 0 for x in (pw, ph)):
        return {"ok": False, "error": "无法读取有效图纸尺寸"}
    # GetFirstView starts with the current sheet view; its linked list never
    # traverses another sheet (unlike GetViews, which returns every sheet).
    sheet_view = wrap(_value(md, "GetFirstView"))
    current = wrap(_value(sheet_view, "GetNextView")) if sheet_view else None
    views = []
    while current is not None:
        views.append(current)
        if len(views) > 4:
            return {"ok": False, "views": len(views),
                    "error": "当前页超过四个视图，请先选择需要排版的标准视图页"}
        current = wrap(_value(current, "GetNextView"))
    if not views:
        return {"ok": False, "views": 0, "error": "当前图纸没有视图"}
    if len(views) == 4 and not iso:
        return {"ok": False, "views": 4, "error": "四视图排版需要 iso=True"}

    warnings = []
    roles = {}
    for view in views:
        try:
            name = str(_value(view, "GetOrientationName")).lower().replace("*", "")
        except Exception:
            name = ""
        for role, aliases in (("main", ("front", "前视")), ("top", ("top", "上视")),
                              ("right", ("right", "右视")), ("iso", ("isometric", "等轴测"))):
            if name in aliases and role not in roles:
                roles[role] = view
    if len(roles) == len(views) and "main" in roles:
        main, top, right, extra = (roles.get(k) for k in ("main", "top", "right", "iso"))
    else:
        main = views[0]
        top = views[1] if len(views) > 1 else None
        right = views[2] if len(views) > 2 else None
        extra = views[3] if len(views) > 3 else None
        warnings.append("部分视图朝向不可识别，按创建顺序解释为主/俯/右/等轴测")
    ordered = [(k, v) for k, v in (("main", main), ("top", top),
                                   ("right", right), ("iso", extra)) if v is not None]
    bounds, old_scales = {}, {}
    for role, view in ordered:
        try:
            outline = tuple(float(x) for x in _value(view, "GetOutline"))
            position = tuple(float(x) for x in _value(view, "Position"))
            if len(outline) < 4 or len(position) < 2 or not all(math.isfinite(x) for x in (*outline, *position)):
                raise ValueError("边界不是有限数组")
            if outline[2] <= outline[0] or outline[3] <= outline[1]:
                raise ValueError("视图轮廓为空")
            bounds[role] = (outline[0] - position[0], outline[1] - position[1],
                            outline[2] - position[0], outline[3] - position[1])
            old_scales[role] = float(view.ScaleDecimal)
            if old_scales[role] <= 0 or not math.isfinite(old_scales[role]):
                raise ValueError("视图比例无效")
        except Exception as exc:
            return {"ok": False, "views": len(views), "error": f"无法读取 {role} 视图：{exc}"}

    left = [bounds[k] for k in ("main", "top") if k in bounds]
    right_col = [bounds[k] for k in ("right", "iso") if k in bounds]
    upper = [bounds[k] for k in ("main", "right") if k in bounds]
    lower = [bounds[k] for k in ("top", "iso") if k in bounds]
    lx0, lx1 = min(b[0] for b in left), max(b[2] for b in left)
    uy0, uy1 = min(b[1] for b in upper), max(b[3] for b in upper)
    rx0 = min(b[0] for b in right_col) if right_col else 0
    rx1 = max(b[2] for b in right_col) if right_col else 0
    ly0 = min(b[1] for b in lower) if lower else 0
    ly1 = max(b[3] for b in lower) if lower else 0
    gap = gap_mm / 1000
    safe_x0, safe_y0 = pw * margin_ratio, ph * margin_ratio
    avail_w = pw * (1 - 2 * margin_ratio) * (1 - title_block_reserve)
    avail_h = ph * (1 - 2 * margin_ratio)
    geometry_w = lx1 - lx0 + rx1 - rx0
    geometry_h = uy1 - uy0 + ly1 - ly0
    gap_w, gap_h = (gap if right_col else 0), (gap if lower else 0)
    if avail_w <= gap_w or avail_h <= gap_h:
        return {"ok": False, "error": "图纸安全区小于指定间距"}
    fit = min((avail_w - gap_w) / geometry_w, (avail_h - gap_h) / geometry_h)
    if fit < 1 and not auto_scale:
        return {"ok": False, "error": "视图超出安全区，auto_scale=False", "views": len(views)}
    scale = min(1.0, fit * 0.98) if fit < 1 else 1.0
    if scale < 1:
        warnings.append(f"视图自动缩放到原比例的 {scale:.3f}，间距仍保持 {gap_mm:g} mm")
    block_w, block_h = geometry_w * scale + gap_w, geometry_h * scale + gap_h
    shift_x = safe_x0 + (avail_w - block_w) / 2 - lx0 * scale
    # Lower-row minimum is uy0*s-gap-(ly1-ly0)*s.
    bottom = uy0 * scale - gap_h - (ly1 - ly0) * scale
    shift_y = safe_y0 + (avail_h - block_h) / 2 - bottom
    right_x = (lx1 - rx0) * scale + gap_w
    lower_y = (uy0 - ly1) * scale - gap_h
    plan = [(role, view,
             shift_x + (right_x if role in ("right", "iso") else 0),
             shift_y + (lower_y if role in ("top", "iso") else 0))
            for role, view in ordered]
    result = {"ok": True, "dry_run": dry_run, "views": len(views),
              "sheet_mm": [round(pw * 1000, 1), round(ph * 1000, 1)],
              "scale": round(scale, 6), "block_mm": [round(block_w * 1000, 2), round(block_h * 1000, 2)],
              "positions_m": [[round(x, 6), round(y, 6)] for _, _, x, y in plan],
              "roles": [role for role, _, _, _ in plan], "warnings": warnings}
    if dry_run:
        return result
    errors, moved = [], 0
    # Stop if a scale is rejected; do not continue positioning using an untrue size.
    for role, view, _, _ in plan:
        if scale != 1:
            try:
                view.UseSheetScale = False
                view.UseParentScale = False
                view.ScaleDecimal = old_scales[role] * scale
                if abs(float(view.ScaleDecimal) - old_scales[role] * scale) > 1e-7:
                    raise RuntimeError("比例回读不一致")
            except Exception as exc:
                errors.append(f"{role} 比例设置失败：{exc}")
    # Outline padding, labels and annotations do not necessarily scale with
    # model geometry. After a real scale change, measure again and solve the
    # positions from those actual bounds. Preview calls remain read-only.
    if not errors and scale != 1:
        cumulative_scale = scale
        for attempt in range(4):
            try:
                _value(md, "EditRebuild3")
                measured = normalize_layout(
                    drawing_path, gap_mm=gap_mm, iso=iso, auto_scale=auto_scale,
                    margin_ratio=margin_ratio, title_block_reserve=title_block_reserve,
                    dry_run=True,
                )
                if not measured["ok"]:
                    raise RuntimeError(measured.get("error", "缩放后无法量取视图"))
                additional_scale = measured["scale"]
                if additional_scale >= 1:
                    by_role = {role: view for role, view, _, _ in plan}
                    plan = [(role, by_role[role], point[0], point[1])
                            for role, point in zip(measured["roles"], measured["positions_m"])]
                    initial_warnings = result["warnings"]
                    result.update(measured)
                    result.update(dry_run=False, scale=round(cumulative_scale, 6),
                                  warnings=initial_warnings + measured["warnings"])
                    break
                if attempt == 3:
                    raise RuntimeError("缩放四次后，标注或固定边框仍无法放入安全区")
                for role, view, _, _ in plan:
                    target_scale = float(view.ScaleDecimal) * additional_scale
                    view.ScaleDecimal = target_scale
                    if abs(float(view.ScaleDecimal) - target_scale) > 1e-7:
                        raise RuntimeError(f"{role} 再次缩放回读不一致")
                cumulative_scale *= additional_scale
            except Exception as exc:
                errors.append(f"缩放后重新排版失败：{exc}")
                break
    if not errors:
        for role, view, x, y in plan:
            try:
                view.Position = _vt_pt(x, y)
                actual = _value(view, "Position")
                if max(abs(actual[0] - x), abs(actual[1] - y)) > 1e-6:
                    raise RuntimeError("位置回读不一致")
                moved += 1
            except Exception as exc:
                errors.append(f"{role} 位置设置失败：{exc}")
    saved = False
    if not errors:
        try:
            from .colors import _save
            _value(md, "EditRebuild3")
            actual = {role: tuple(_value(view, "GetOutline")) for role, view, _, _ in plan}
            safe_x1, safe_y1 = safe_x0 + avail_w, safe_y0 + avail_h
            for role, outline in actual.items():
                if (outline[0] < safe_x0 - 1e-6 or outline[1] < safe_y0 - 1e-6
                        or outline[2] > safe_x1 + 1e-6 or outline[3] > safe_y1 + 1e-6):
                    errors.append(f"{role} 实测边界仍超出安全区")
            names = list(actual)
            for i, role in enumerate(names):
                a = actual[role]
                for other in names[i + 1:]:
                    b = actual[other]
                    separation = max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])
                    if separation < gap - 1e-6:
                        errors.append(f"{role}/{other} 实测间距不足 {gap_mm:g} mm")
            if errors:
                result.update(ok=False, moved=moved, saved=False, errors=errors)
                return result
            saved, err, warn = _save(md)
            if not saved:
                errors.append(f"工程图保存失败（错误 {err}，警告 {warn}）")
        except Exception as exc:
            errors.append(f"工程图保存失败：{exc}")
    result.update(ok=not errors and moved == len(plan) and saved, moved=moved,
                  saved=saved, errors=errors)
    return result


# ---------------------------------------------------------------------- 图集
def make_atlas(pages: list[dict], out_pdf: str, title: str = "技术图集",
               subtitle: str = "", cover_items: list[tuple] | None = None,
               paper: str = "A3") -> dict:
    """把一组「文字页 + 图片页」拼成多页 PDF 图集。

    `pages` 每项：
        {"type": "cover"|"text"|"image",
         "title": str, "lines": [str], "image": path, "caption": str}
    """
    from PIL import Image, ImageDraw, ImageFont

    SIZES = {"A4": (2480, 3508), "A3": (3508, 2480), "A2": (4961, 3508)}
    PW, PH = SIZES.get(paper.upper(), SIZES["A3"])
    M = 120
    X0, X1 = M, PW - M
    CW = X1 - X0
    BAR = 170
    TOP = BAR + 90

    def font(sz, bold=False):
        for c in (([r"C:\Windows\Fonts\msyhbd.ttc"] if bold else [])
                  + [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]):
            if os.path.isfile(c):
                try:
                    return ImageFont.truetype(c, sz)
                except Exception:                        # noqa: BLE001
                    pass
        return ImageFont.load_default()

    F_TITLE = font(int(PW * 0.034), True)
    F_SUB = font(int(PW * 0.025), True)
    F_SEC = font(int(PW * 0.022), True)
    F_TD = font(int(PW * 0.016))
    F_SM = font(int(PW * 0.0125))

    def wrap(d, text, f, maxw):
        lines = []
        for raw in str(text).split("\n"):
            cur = ""
            for ch in raw:
                if d.textlength(cur + ch, font=f) <= maxw:
                    cur += ch
                else:
                    if cur:
                        lines.append(cur)
                    cur = ch
            lines.append(cur)
        return lines

    rendered = []
    total = len(pages)
    for idx, spec in enumerate(pages, 1):
        kind = spec.get("type", "image")
        if kind == "cover":
            p = Image.new("RGB", (PW, PH), "white")
            d = ImageDraw.Draw(p)
            d.rectangle([0, 0, PW, 48], fill=(48, 48, 54))
            d.rectangle([0, PH - 48, PW, PH], fill=(48, 48, 54))
            t = spec.get("title", title)
            d.text(((PW - d.textlength(t, font=F_TITLE)) / 2, int(PH * 0.19)),
                   t, font=F_TITLE, fill=(16, 16, 16))
            if subtitle:
                d.text(((PW - d.textlength(subtitle, font=F_SUB)) / 2, int(PH * 0.27)),
                       subtitle, font=F_SUB, fill=(52, 52, 52))
            d.line([(PW * 0.20, int(PH * 0.33)), (PW * 0.80, int(PH * 0.33))],
                   fill=(172, 172, 178), width=6)
            y = int(PH * 0.38)
            for k, v in (cover_items or []):
                d.text((int(PW * 0.16), y), k, font=F_TD, fill=(118, 118, 118))
                d.text((int(PW * 0.16) + 330, y), v, font=F_TD, fill=(32, 32, 32))
                y += int(PH * 0.048)
            rendered.append(p)
            continue

        p = Image.new("RGB", (PW, PH), "white")
        d = ImageDraw.Draw(p)
        d.rectangle([0, 0, PW, BAR], fill=(232, 232, 236))
        d.line([(0, BAR), (PW, BAR)], fill=(165, 165, 170), width=4)
        d.text((X0, 40), spec.get("title", ""), font=F_SEC, fill=(20, 20, 20))
        s = f"{idx} / {total}"
        d.text((X1 - d.textlength(s, font=F_SM), 62), s, font=F_SM, fill=(110, 110, 110))

        if kind == "text":
            y = TOP
            for line in spec.get("lines", []):
                bold = line.startswith("■")
                f = F_SEC if bold else F_TD
                for w in wrap(d, line, f, CW):
                    d.text((X0, y), w, font=f, fill=(30 if bold else 55,) * 3)
                    y += int(PH * 0.031) if bold else int(PH * 0.026)
                y += int(PH * 0.006)
        else:
            img_path = spec.get("image")
            if img_path and os.path.isfile(img_path):
                im = Image.open(img_path).convert("RGB")
                aw, ah = CW, PH - TOP - M
                sc = min(aw / im.width, ah / im.height)
                nw, nh = int(im.width * sc), int(im.height * sc)
                im2 = im.resize((nw, nh), Image.LANCZOS)
                px, py = (PW - nw) // 2, TOP + (ah - nh) // 2
                p.paste(im2, (px, py))
                d.rectangle([px - 3, py - 3, px + nw + 3, py + nh + 3],
                            outline=(195, 195, 200), width=3)
            else:
                d.text((X0, TOP + 200), f"（图片缺失：{img_path}）",
                       font=F_TD, fill=(170, 60, 60))
        rendered.append(p)

    if not rendered:
        raise RuntimeError("没有可输出的页面")
    rendered[0].save(out_pdf, "PDF", resolution=300.0,
                     save_all=True, append_images=rendered[1:])
    return {
        "ok": True, "path": out_pdf, "pages": len(rendered),
        "size_mb": round(os.path.getsize(out_pdf) / 1048576, 2),
    }




