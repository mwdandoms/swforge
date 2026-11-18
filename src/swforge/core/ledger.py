"""File evidence for a known output path, independent of the export result."""
from pathlib import Path
import functools
import inspect
import json
import stat
import time

from ..variants import file_sha256

_SCHEMA = 2


def _state(path):
    """Return None only for a missing path. An unreadable file is not an empty baseline."""
    p = Path(path)
    try:
        before = p.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Expected a regular file: "+str(p))
    digest = file_sha256(p)
    after = p.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError("File changed during fingerprint: "+str(p))
    return dict(sha256=digest,mtime_ns=after.st_mtime_ns,size=after.st_size)


def _hash(state):
    return state.get("sha256") if isinstance(state,dict) else None


def capture_artifact(path):
    output = str(Path(path).absolute())
    row = dict(path=output,before=None,baseline_complete=False,started_ns=time.time_ns())
    try:
        if Path(output).is_symlink():
            raise ValueError("Output is a symbolic link")
        row["before"] = _state(output)
        row["baseline_complete"] = True
    except (OSError,ValueError) as exc:
        row["baseline_error"] = str(exc)
    return row


def finalize_artifact(capture, *, tool_success, verified=False):
    row = dict(capture,schema_version=_SCHEMA,produced_this_run=None,after=None,
               task_verified=bool(verified),source="swforge execution")
    try:
        if Path(row["path"]).is_symlink():
            raise ValueError("Output is a symbolic link")
        row["after"] = _state(row["path"])
    except (OSError,ValueError) as exc:
        return dict(row,reason_code="output_unreadable",output_error=str(exc))
    before, after = row["before"], row["after"]
    if not row.get("baseline_complete"):
        return dict(row,reason_code="incomplete_baseline")
    if after is None:
        return dict(row,produced_this_run=False,reason_code="missing_output")
    if after["size"]==0:
        return dict(row,produced_this_run=False,reason_code="empty_output")
    if _hash(before)==_hash(after):
        return dict(row,produced_this_run=False,reason_code="unchanged_content")
    if not tool_success or not verified:
        return dict(row,reason_code="output_not_verified")
    return dict(row,produced_this_run=True,reason_code="new_at_captured_path" if before is None else "hash_changed")


def _recheck(entry):
    row = dict(entry)
    row["schema_version"] = _SCHEMA
    claim = row.get("produced_this_run")
    if claim is not True:
        row["produced_this_run"] = False if claim is False or claim=="stale" else None
        row.setdefault("reason_code","legacy_stale" if claim=="stale" else "unverified")
        return row
    prior, exported = row.get("before"),row.get("after")
    if not row.get("path") or not _hash(exported) or (prior is None and not row.get("baseline_complete")):
        return dict(row,produced_this_run=None,reason_code="incomplete_baseline")
    if not exported.get("size"):
        return dict(row,produced_this_run=False,reason_code="empty_output")
    if prior is not None and not _hash(prior):
        return dict(row,produced_this_run=None,reason_code="incomplete_baseline")
    if _hash(prior)==_hash(exported):
        return dict(row,produced_this_run=False,reason_code="unchanged_content")
    try:
        if Path(row["path"]).is_symlink():
            raise ValueError("Output is a symbolic link")
        if _hash(_state(row["path"]))!=_hash(exported):
            return dict(row,produced_this_run=False,reason_code="output_changed")
        sources = row.get("sources",{})
        if not isinstance(sources,dict):
            raise ValueError("Invalid source evidence")
        for path, original in sources.items():
            if not _hash(original):
                return dict(row,produced_this_run=None,reason_code="source_baseline_unavailable")
            if _hash(_state(path))!=_hash(original):
                return dict(row,produced_this_run=False,reason_code="source_changed")
    except (OSError,ValueError) as exc:
        return dict(row,produced_this_run=None,reason_code="recheck_unavailable",recheck_error=str(exc))
    row.setdefault("reason_code","new_at_captured_path" if prior is None else "hash_changed")
    return row


def delivery_manifest(entries, path=None):
    rows = [_recheck(entry) for entry in entries]
    blocked = [row.get("path") for row in rows if row["produced_this_run"] is not True]
    ok = bool(rows) and not blocked
    result = dict(schema_version=_SCHEMA,ok=ok,delivery="ready_for_review" if ok else "blocked",
                  entries=rows,blocked=blocked,review_required=True,ready_for_manufacture=False,
                  reason_code="no_artifacts" if not rows else "ready_for_review" if ok else "evidence_failed")
    if path:
        Path(path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def track_output(argument, default=None, extra_sources=None):
    """Capture the declared output and sources before invoking the exporter."""
    def decorate(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            bound = inspect.signature(fn).bind(*args,**kwargs)
            bound.apply_defaults()
            output = bound.arguments.get(argument) or (default(bound.arguments) if default else None)
            if not output:
                return fn(*args,**kwargs)
            capture = capture_artifact(output)
            from .delivery import capture_sources
            paths = [bound.arguments[key] for key in ("model_path","drawing_path")
                     if isinstance(bound.arguments.get(key),(str,Path)) and bound.arguments[key]]
            if extra_sources:
                paths.extend(extra_sources(bound.arguments))
            if any(Path(value).resolve()==Path(output).resolve() for value in paths):
                raise ValueError("Output and source paths must be distinct")
            sources = capture_sources(paths)
            result = fn(*args,**kwargs)
            if isinstance(result,dict):
                success = result.get("ok") is True
                entry = finalize_artifact(capture,tool_success=success,verified=success)
                entry["sources"] = sources
                result["artifact"] = entry
                result["delivery"] = delivery_manifest([entry],str(output)+".swforge-ledger.json")
            return result
        return run
    return decorate
