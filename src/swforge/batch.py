# -*- coding: utf-8 -*-
"""批量出图：一个文件夹的零件 → 一批带 GB 图框的工程图。

为什么这个功能重要
------------------
单件出图只是"省一点手"，**批量出图才是质变**：

    以前：50 个零件，每件 20~40 分钟出图 → 两三天
    现在：50 个零件，一批跑完 → 十几分钟（还要人工补公差）

而且它天然适合演示 —— 屏幕上不是"出了一张图"，是"刷出来一列图"。

设计要点
--------
1. **走已有的 produce() 链路**，不重造轮子，所以图框、标注、排版、PDF 全都自动带上
2. **逐件隔离失败**：一个零件崩了不能拖垮整批，失败原因单独记
3. **资源守卫**：SolidWorks 默认 8 个文档上限，所以每件出完就关
4. **可中断可续跑**：已经存在的图默认跳过（`--skip-existing`），断了能接着跑
5. **进度可见**：每件打一行，长任务最怕没反馈
"""

from __future__ import annotations

import fnmatch
import json
import os
import time
from dataclasses import dataclass, field, asdict

__all__ = ["batch_drawings", "collect_models"]


# ---------------------------------------------------------------- 模型收集
def collect_models(folder: str, pattern: str = "*.SLDPRT",
                   recursive: bool = False) -> list[str]:
    """收集待出图的模型路径。

    pattern 不区分大小写（Windows 上 .SLDPRT / .sldprt 都存在）。
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise ValueError(f"不是文件夹：{folder}")

    pat = pattern.lower()
    out: list[str] = []

    if recursive:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fnmatch.fnmatch(fn.lower(), pat):
                    out.append(os.path.join(dirpath, fn))
    else:
        for fn in os.listdir(folder):
            full = os.path.join(folder, fn)
            if os.path.isfile(full) and fnmatch.fnmatch(fn.lower(), pat):
                out.append(full)

    return sorted(out)


def _release(*paths: str) -> None:
    """关掉指向这些路径的已打开文档，释放 SolidWorks 文档名额。"""
    try:
        from .drawing import _close_open_document
    except Exception:
        return
    for p in paths:
        if not p:
            continue
        try:
            _close_open_document(p)
        except Exception:
            continue


# ---------------------------------------------------------------- 结果结构
@dataclass
class ItemResult:
    model: str
    drawing: str = ""
    ok: bool = False
    skipped: bool = False
    dims: int = 0
    overall_done: int = 0
    pdf: str = ""
    pdf_ok: bool = False
    seconds: float = 0.0
    error: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class BatchResult:
    ok: bool = True
    folder: str = ""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    pdf_ok: int = 0
    seconds: float = 0.0
    items: list = field(default_factory=list)
    error: str = ""

    def to_dict(self):
        d = asdict(self)
        return d

    def summary_line(self) -> str:
        return (f"{self.succeeded}/{self.total} 成功"
                f"，失败 {self.failed}，跳过 {self.skipped}"
                f"，PDF {self.pdf_ok}，耗时 {self.seconds:.1f} 秒")


# ---------------------------------------------------------------- 主流程
def batch_drawings(folder: str,
                   out_dir: str | None = None,
                   pattern: str = "*.SLDPRT",
                   recursive: bool = False,
                   paper: str = "A3",
                   overall: bool = True,
                   pdf: bool = False,
                   skip_existing: bool = True,
                   limit: int = 0,
                   max_documents: int = 8,
                   progress=None) -> dict:
    """批量出图。

    参数
    ----
    folder          模型所在文件夹
    out_dir         输出文件夹（默认与模型同目录）
    pattern         文件名通配，默认 `*.SLDPRT`
    recursive       是否递归子目录
    paper           纸张 A0~A4
    overall         是否补总尺寸
    pdf             是否同时导 PDF
    skip_existing   目标图已存在时跳过（支持断点续跑）
    limit           最多处理几个（0 = 不限，调试用）
    max_documents   单批允许占用的 SW 文档数
    progress        回调 fn(idx, total, item: ItemResult)，用于实时打印

    返回 `BatchResult.to_dict()`。

    注意
    ----
    这个函数**不吞异常**：单件失败会记进 items 并在 summary 里体现，
    但不会中断整批 —— 批量任务里"一个坏件毁掉全部"是不可接受的。
    """
    from .drawing import produce, add_dimensions
    from .resources import sweep_documents

    started = time.monotonic()
    folder = os.path.abspath(folder)
    out_dir = os.path.abspath(out_dir) if out_dir else folder

    models = collect_models(folder, pattern=pattern, recursive=recursive)
    if limit and limit > 0:
        models = models[:limit]

    result = BatchResult(folder=folder, total=len(models))
    if not models:
        result.ok = False
        result.error = f"在 {folder} 里没找到匹配 {pattern} 的文件"
        result.seconds = round(time.monotonic() - started, 2)
        return result.to_dict()

    os.makedirs(out_dir, exist_ok=True)

    for idx, model in enumerate(models, 1):
        item = ItemResult(model=model)
        t0 = time.monotonic()

        stem = os.path.splitext(os.path.basename(model))[0]
        dwg = os.path.join(out_dir, stem + ".SLDDRW")
        pdf_path = os.path.join(out_dir, stem + ".pdf")
        item.drawing = dwg

        # ---- 已存在就跳过
        if skip_existing and os.path.isfile(dwg):
            item.skipped = True
            item.ok = True
            item.seconds = 0.0
            result.skipped += 1
            result.items.append(item.to_dict())
            if progress:
                progress(idx, result.total, item)
            continue

        try:
            # 每件开始前清一次场：SolidWorks 默认 8 文档上限，
            # 批量场景下不清就会在第 8 件之后全部「静默失败」
            try:
                sweep_documents(dry_run=False)
            except Exception:
                pass

            r = produce(model, dwg, paper=paper,
                        keep_open=True, max_documents=max_documents)
            if not r.get("ok"):
                item.error = str(r.get("error") or f"produce err={r.get('err')}")
                item.seconds = round(time.monotonic() - t0, 2)
                result.failed += 1
                result.items.append(item.to_dict())
                if progress:
                    progress(idx, result.total, item)
                continue

            # 标注（含总尺寸）
            try:
                d = add_dimensions(dwg, overall=overall)
                item.dims = int(d.get("after") or 0)
                ov = d.get("overall") or {}
                item.overall_done = int(ov.get("done") or 0)
            except Exception as exc:                      # noqa: BLE001
                item.error = f"标注失败：{type(exc).__name__}: {exc}"

            # 可选 PDF
            if pdf:
                try:
                    from .drawing import export_pdf
                    pr = export_pdf(dwg, pdf_path)
                    item.pdf = pdf_path
                    item.pdf_ok = bool(pr.get("ok"))
                    if item.pdf_ok:
                        result.pdf_ok += 1
                except Exception as exc:                  # noqa: BLE001
                    item.error = (item.error + "；" if item.error else "") + \
                                 f"PDF 失败：{type(exc).__name__}: {exc}"

            item.ok = not item.error
            if item.ok:
                result.succeeded += 1
            else:
                result.failed += 1

        except Exception as exc:                          # noqa: BLE001
            item.error = f"{type(exc).__name__}: {exc}"
            result.failed += 1
        finally:
            # 每件结束必须释放文档。SolidWorks 默认只允许 8 个文档同时打开，
            # 批处理不清场会在第 8 件之后整批静默失败 —— 实测第 5 件就撞上了
            # （模型 + 工程图各占一个，加上前一件残留）。
            _release(model, dwg)
            item.seconds = round(time.monotonic() - t0, 2)
            result.items.append(item.to_dict())
            if progress:
                progress(idx, result.total, item)

    result.seconds = round(time.monotonic() - started, 2)
    result.ok = result.failed == 0 and result.succeeded > 0
    return result.to_dict()


def write_report(result: dict, path: str) -> str:
    """把批量结果写成 JSON 报告，便于事后查哪件失败了。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    return path
