"""Existence alone never establishes a deliverable produced in this run."""
from pathlib import Path
import json
import time
import functools
import inspect
from ..variants import file_sha256


def _state(path):
    p = Path(path)
    if not p.is_file():
        return None
    stat = p.stat()
    return dict(sha256=file_sha256(p), mtime_ns=stat.st_mtime_ns, size=stat.st_size)


def capture_artifact(path):
    return dict(path=str(Path(path).resolve()), before=_state(path), started_ns=time.time_ns())


def finalize_artifact(capture, *, tool_success, verified=False):
    after = _state(capture['path'])
    # Ordered before/after fingerprints avoid filesystem clock-resolution skew.
    changed = after is not None and after != capture['before']
    freshness = True if tool_success and verified and changed else 'stale' if after and after == capture['before'] else 'unverified'
    return dict(path=capture['path'], produced_this_run=freshness, before=capture['before'], after=after,
                task_verified=bool(verified), source='swforge execution')


def delivery_manifest(entries, path=None):
    # Recheck the hash when constructing the manifest, not just when exporting.
    entries = [dict(e) for e in entries]
    for row in entries:
        if row.get('produced_this_run') is True and _state(row['path']) != row.get('after'):
            row['produced_this_run'] = 'stale'
        if any(_state(p)!=state for p,state in row.get('sources',{}).items()):
            row['produced_this_run']='stale'
    blocked = [e['path'] for e in entries if e.get('produced_this_run') is not True]
    result = dict(ok=not blocked, delivery='blocked' if blocked else 'ready_for_review', entries=entries,
                  blocked=blocked, review_required=True, ready_for_manufacture=False)
    if path:
        Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def track_output(argument, default=None):
    """Track existing export APIs without changing their call signatures."""
    def decorate(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            bound = inspect.signature(fn).bind(*args, **kwargs)
            bound.apply_defaults()
            output = bound.arguments.get(argument) or (default(bound.arguments) if default else None)
            if not output:
                return fn(*args, **kwargs)
            capture = capture_artifact(output)
            sources={str(Path(v).resolve()):_state(v) for k,v in bound.arguments.items()
                     if k in ('model_path','drawing_path') and isinstance(v,str) and Path(v).is_file()}
            result = fn(*args, **kwargs)
            success = isinstance(result, dict) and result.get('ok') is True
            # Artifact verification is separate from GB or geometry acceptance.
            valid = success and Path(output).is_file() and Path(output).stat().st_size > 0
            entry = finalize_artifact(capture, tool_success=success, verified=valid)
            entry['sources']=sources
            if isinstance(result, dict):
                result['artifact'] = entry
                result['delivery'] = delivery_manifest([entry], str(output)+'.swforge-ledger.json')
            return result
        return run
    return decorate
