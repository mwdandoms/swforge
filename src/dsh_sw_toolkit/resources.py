"""SW 文档/进程资源清点、健康分级与遗留文档清扫。

设计目标（v0.4.1 新增）
-----------------------
SolidWorks 同时打开的文档数过多会显著变慢甚至崩溃。v0.4 只在**创建前**做
一次硬性上限检查（达到 8 个直接拒绝），存在三个问题：

1. **没有渐进告警** —— 只有「行」和「拒绝」两档，调用方无法提前收手。
2. **没有手动清扫入口** —— 遗留的测试/临时文档只能逐个关。
3. **没有内存维度** —— 文档数没超、内存已经很高的情况看不到。

本模块提供三档健康状态（ok / warn / critical）、按路径模式的安全清扫，
以及创建前的容量预检。**仍然只关闭明确属于临时/测试目录的文档，
绝不关闭用户打开的工作文档，也不强杀 SW 进程。**
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from .session import get_session, _value, SWError

__all__ = [
    "DEFAULT_LIMIT", "DEFAULT_WARN_RATIO", "DEFAULT_MEM_WARN_MB",
    "document_inventory", "resource_status", "sweep_documents",
    "ensure_capacity", "document_scope",
]

DEFAULT_LIMIT = 8
DEFAULT_WARN_RATIO = 0.75        # 达到上限 75% 即 warn（默认 6/8）
DEFAULT_MEM_WARN_MB = 2500.0     # 工作集超过 2.5 GB 视为 warn
DEFAULT_SWEEP_MARKERS = ("pytest-of-", "dshsw_it", "dshsw_")


# ---------------------------------------------------------------------- 清点
def _dispatch_rows(sw):
    import win32com.client

    rows = []
    for raw in (_value(sw, "GetDocuments") or []):
        doc = raw if hasattr(raw, "GetPathName") else win32com.client.Dispatch(raw)
        rows.append({
            "path": str(_value(doc, "GetPathName")),
            "title": str(_value(doc, "GetTitle")),
            "modified": bool(_value(doc, "GetSaveFlag")),
        })
    return rows


def document_inventory(sw=None):
    """只读清点：文档清单 + SW 进程号 + 工作集内存。"""
    sw = sw if sw is not None else get_session().sw()
    rows = _dispatch_rows(sw)
    result = {"ok": True, "document_count": len(rows), "documents": rows}
    try:
        import win32api
        import win32process

        pid = int(_value(sw, "GetProcessID"))
        handle = win32api.OpenProcess(0x410, False, pid)
        try:
            memory = win32process.GetProcessMemoryInfo(handle)
            result.update(process_id=pid,
                          working_set_mb=round(memory["WorkingSetSize"] / 1048576, 2))
        finally:
            handle.Close()
    except Exception as exc:                             # noqa: BLE001
        result["memory_error"] = str(exc)
    return result


# ---------------------------------------------------------------------- 健康分级
def resource_status(limit=DEFAULT_LIMIT, warn_ratio=DEFAULT_WARN_RATIO,
                    mem_warn_mb=DEFAULT_MEM_WARN_MB, sw=None) -> dict:
    """三档健康检查。**只读，不关闭任何文档。**

    返回 level
    ----------
    ok        文档数 < limit*warn_ratio 且内存正常
    warn      达到告警线（默认 6/8）或内存超阈值 —— 还能建，但该收了
    critical  已达到或超过 limit —— 再建会被拒绝
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit 必须为正整数")
    warn_at = max(1, int(round(limit * float(warn_ratio))))

    inv = document_inventory(sw)
    count = inv["document_count"]
    mem = inv.get("working_set_mb")
    warnings = []

    if count >= limit:
        level = "critical"
        warnings.append(f"文档数 {count} 已达上限 {limit}，再创建会被拒绝")
    elif count >= warn_at:
        level = "warn"
        warnings.append(f"文档数 {count} 已达告警线 {warn_at}/{limit}")
    else:
        level = "ok"

    if isinstance(mem, (int, float)) and mem >= mem_warn_mb:
        warnings.append(f"SW 工作集 {mem:.0f} MB 超过阈值 {mem_warn_mb:.0f} MB")
        if level == "ok":
            level = "warn"

    headroom = max(0, limit - count)
    leftover = [d for d in inv["documents"] if _looks_like_tmp(d.get("path", ""))]

    return {
        "ok": level != "critical",
        "level": level,
        "document_count": count,
        "limit": limit,
        "warn_at": warn_at,
        "headroom": headroom,
        "working_set_mb": mem,
        "process_id": inv.get("process_id"),
        "warnings": warnings,
        "leftover_documents": leftover,
        "leftover_count": len(leftover),
        "documents": inv["documents"],
    }


def _looks_like_tmp(path: str, markers=DEFAULT_SWEEP_MARKERS,
                    extra_roots=()) -> bool:
    """判断一个路径是否属于「可安全关闭」的临时/测试产物。"""
    if not path:
        return False
    low = path.lower()
    if any(m.lower() in low for m in markers):
        return True
    try:
        root = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        target = os.path.normcase(os.path.abspath(path))
    except Exception:                                    # noqa: BLE001
        return False
    if target.startswith(root + os.sep):
        return True
    for extra in extra_roots:
        try:
            er = os.path.normcase(os.path.abspath(extra))
        except Exception:                                # noqa: BLE001
            continue
        if target.startswith(er + os.sep):
            return True
    return False


# ---------------------------------------------------------------------- 清扫
def sweep_documents(dry_run=True, markers=DEFAULT_SWEEP_MARKERS,
                    extra_roots=(), keep=(), limit=None) -> dict:
    """关闭遗留的临时/测试文档。**默认 dry_run，只列不关。**

    安全边界
    --------
    * 只匹配 `markers` 或位于系统临时目录 / `extra_roots` 下的文档
    * `keep` 里的路径永不关闭
    * 有未保存修改的文档跳过（不丢用户工作）
    """
    sw = get_session().sw()
    inv = document_inventory(sw)
    keep_norm = {os.path.normcase(os.path.abspath(p)) for p in keep if p}
    candidates = []
    for d in inv["documents"]:
        path = d.get("path") or ""
        if not path:
            continue                                    # 无路径（新建未存）不碰
        if os.path.normcase(os.path.abspath(path)) in keep_norm:
            continue
        if not _looks_like_tmp(path, markers, extra_roots):
            continue
        candidates.append(d)

    if limit is not None:
        candidates = candidates[:max(0, int(limit))]

    closed, skipped = [], []
    for d in candidates:
        if dry_run:
            closed.append(d["path"])
            continue
        if d.get("modified"):
            skipped.append({"path": d["path"], "reason": "有未保存修改，跳过"})
            continue
        try:
            sw.CloseDoc(d["path"] or d["title"])
            closed.append(d["path"])
        except Exception as exc:                         # noqa: BLE001
            skipped.append({"path": d["path"], "reason": str(exc)})

    after = document_inventory(sw)
    return {
        "ok": True,
        "dry_run": dry_run,
        "before": inv["document_count"],
        "after": after["document_count"],
        "candidates": [d["path"] for d in candidates],
        "closed": closed,
        "skipped": skipped,
        "working_set_mb": after.get("working_set_mb"),
    }


# ---------------------------------------------------------------------- 创建前预检
def ensure_capacity(need=1, limit=DEFAULT_LIMIT, warn_ratio=DEFAULT_WARN_RATIO,
                    auto_sweep=False, dry_run=False) -> dict:
    """建文档之前的容量预检。

    `auto_sweep=True` 时，名额不足会先清扫临时文档再复检一次。
    """
    if isinstance(need, bool) or not isinstance(need, int) or need < 1:
        raise ValueError("need 必须为正整数")

    status = resource_status(limit=limit, warn_ratio=warn_ratio)
    swept = None
    if status["headroom"] < need and auto_sweep:
        swept = sweep_documents(dry_run=False)
        status = resource_status(limit=limit, warn_ratio=warn_ratio)

    allowed = status["headroom"] >= need
    out = {
        "ok": allowed,
        "allowed": allowed,
        "need": need,
        "headroom": status["headroom"],
        "level": status["level"],
        "warnings": list(status["warnings"]),
        "status": {k: status[k] for k in
                   ("document_count", "limit", "warn_at", "working_set_mb", "process_id")},
    }
    if not allowed:
        out["error"] = (f"SW 文档名额不足：需要 {need}，当前 {status['document_count']}/{limit}。"
                        f"可先调用 sweep_documents() 清理临时文档，或关闭不需要的图纸。")
    if swept is not None:
        out["sweep"] = {"before": swept["before"], "after": swept["after"],
                        "closed": len(swept["closed"]) + len(swept["skipped"])}
    if dry_run:
        out["dry_run"] = True
    return out


# ---------------------------------------------------------------------- 作用域
@contextmanager
def document_scope(out_path, *, keep_open=True, max_documents=DEFAULT_LIMIT,
                   log_path=None, related_paths=()):
    """限定本次操作「拥有」的文档；退出时只回收自己新建的。

    A scope never closes a document present on entry, even if it shares the
    requested output path. No global close-all or process termination.
    """
    if isinstance(max_documents, bool) or not isinstance(max_documents, int) or max_documents < 0:
        raise ValueError("max_documents 必须为非负整数（0 表示不允许再建文档）")
    sw = get_session().sw()
    before = document_inventory(sw)
    related = {os.path.normcase(os.path.abspath(p)) for p in related_paths}
    already_open = {os.path.normcase(os.path.abspath(r["path"])) for r in before["documents"] if r["path"]}
    reserve = 1 + len(related - already_open)
    if before["document_count"] + reserve > max_documents:
        raise SWError(f"SW 已打开 {before['document_count']} 个文档，达到上限 {max_documents}")
    initial = {(r["path"].lower(), r["title"]) for r in before["documents"]}
    target = os.path.normcase(os.path.abspath(out_path))
    started = time.monotonic()
    failed = False
    closed = []

    class Lease:
        failed = False
        owned = []

        def own(self, doc):
            self.owned.append(doc)

    lease = Lease()
    try:
        yield lease
    except BaseException:
        failed = True
        raise
    finally:
        after = document_inventory(sw)
        failed = failed or lease.failed
        if failed or not keep_open:
            for doc in lease.owned:
                path = str(_value(doc, "GetPathName"))
                title = str(_value(doc, "GetTitle"))
                if (path.lower(), title) not in initial:
                    sw.CloseDoc(path or title)
                    closed.append(path or title)
            after = document_inventory(sw)
            for row in after["documents"]:
                key = (row["path"].lower(), row["title"])
                normalized = os.path.normcase(os.path.abspath(row["path"])) if row["path"] else ""
                if key not in initial and row["path"] and (normalized == target or
                        (normalized in related and not row["modified"])):
                    sw.CloseDoc(row["path"])
                    closed.append(row["path"])
        final = document_inventory(sw)
        if log_path:
            record = {"time_utc": datetime.now(timezone.utc).isoformat(),
                      "operation": "drawing", "target": target, "failed": failed,
                      "elapsed_s": round(time.monotonic() - started, 3),
                      "before": before, "peak_observed": after["document_count"],
                      "after": final, "closed": closed}
            os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
