"""Review multiple declared output files and separately supplied native measurements."""
from datetime import datetime, timezone
import math
import os
from pathlib import Path

from .ledger import capture_artifact, delivery_manifest, finalize_artifact


def _path_key(path):
    if not isinstance(path,(str,Path)) or not str(path).strip():
        raise ValueError("A non-empty file path is required")
    return os.path.normcase(str(Path(path).resolve()))


def capture_delivery(outputs, sources=()):
    """Record exact output and source paths before a multi-file operation."""
    outputs = list(outputs)
    sources = list(sources)
    keys = [_path_key(path) for path in outputs]
    if not keys or len(keys)!=len(set(keys)):
        raise ValueError("Declare at least one output and do not repeat output paths")
    if set(keys).intersection(_path_key(path) for path in sources):
        raise ValueError("Output and source paths must be distinct")
    return dict(outputs=[capture_artifact(path) for path in outputs],sources=capture_sources(sources))


def capture_sources(paths):
    result = {}
    for path in paths:
        entry = capture_artifact(path)
        result[entry["path"]] = entry["before"] if entry["baseline_complete"] else None
    return result


def finalize_delivery(baseline, *, tool_success, verified=False):
    entries = [dict(finalize_artifact(item,tool_success=tool_success,verified=verified),
                    sources=baseline["sources"]) for item in baseline["outputs"]]
    return delivery_manifest(entries)


def atlas_sources(pages):
    """Resolve every page image that the atlas renderer reads."""
    sources = []
    for index,page in enumerate(pages,1):
        if page.get("type","image") in {"cover","text"}:
            continue
        image = page.get("image")
        if not isinstance(image,(str,Path)) or not Path(image).is_file():
            raise ValueError(f"Atlas image missing on page {index}: {image}")
        sources.append(image)
    return sources


def _check(id_, status, code, target=None, **details):
    return dict(id=id_,status=status,reason_code=code,target=target,**details)


def _native_check(item, verified_outputs):
    if not isinstance(item,dict):
        return _check("native_measurement","blocked","invalid_measurement")
    id_ = item.get("id")
    target = item.get("target")
    if not isinstance(id_,str) or not id_.strip() or not isinstance(item.get("unit"),str) or not item["unit"]:
        return _check("native_measurement","blocked","invalid_measurement",target)
    try:
        output = verified_outputs.get(_path_key(target))
    except (ValueError,OSError):
        return _check(id_,"blocked","invalid_target",target)
    if not output or item.get("sha256")!=output["after"]["sha256"]:
        return _check(id_,"blocked","measurement_revision_unverified",target)
    values = [item.get(k) for k in ("expected","actual","tolerance")]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        return _check(id_,"blocked","invalid_measurement",target)
    expected,actual,tolerance = values
    if tolerance<0:
        return _check(id_,"blocked","invalid_measurement",target)
    passed = abs(expected-actual)<=tolerance
    return _check(id_,"pass" if passed else "fail","within_tolerance" if passed else "outside_tolerance",
                  target,expected=expected,actual=actual,tolerance=tolerance,unit=item["unit"],sha256=item["sha256"])


def delivery_report(manifests, *, required_outputs=(), native_measurements=None):
    """Recheck each artifact. Native readings count only for the exact verified file revision."""
    entries = []
    checks = []
    for index,manifest in enumerate(manifests,1):
        if not isinstance(manifest,dict) or not isinstance(manifest.get("entries"),list) or not manifest["entries"]:
            checks.append(_check(f"ledger_{index}","blocked","invalid_or_empty_ledger"))
            continue
        for entry in manifest["entries"]:
            if not isinstance(entry,dict) or not isinstance(entry.get("path"),str) or not entry["path"].strip():
                checks.append(_check(f"ledger_{index}","blocked","invalid_artifact_entry"))
            else:
                entries.append(entry)
    file_result = delivery_manifest(entries)
    verified_outputs = {}
    seen = set()
    for entry in file_result["entries"]:
        path = entry["path"]
        key = _path_key(path)
        if key in seen:
            checks.append(_check("artifact","blocked","duplicate_output_claim",path))
            verified_outputs.pop(key,None)
            continue
        seen.add(key)
        passed = entry["produced_this_run"] is True
        checks.append(_check("artifact","pass" if passed else "blocked",entry["reason_code"],path))
        if passed:
            verified_outputs[key] = entry
    for path in required_outputs:
        if _path_key(path) not in seen:
            checks.append(_check("required_output","blocked","required_output_missing",str(path)))
    if not entries:
        checks.append(_check("artifacts","blocked","no_artifacts"))
    if not native_measurements:
        checks.append(_check("native_measurements","warning","native_measurements_not_supplied"))
    else:
        checks.extend(_native_check(row,verified_outputs) for row in native_measurements)
    status = next(value for value in ("blocked","fail","warning","pass")
                  if any(check["status"]==value for check in checks))
    return dict(schema_version=1,checked_at=datetime.now(timezone.utc).isoformat(),
                ok=status in {"pass","warning"},overall_status=status,checks=checks,
                outputs=file_result["entries"],review_required=True,ready_for_manufacture=False)
