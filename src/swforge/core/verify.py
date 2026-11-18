"""Translate existing readback into a stable task verdict."""
from dataclasses import asdict, dataclass

_RANK = {"pass":0,"warning":1,"fail":2,"blocked":3}
_ALIASES = {"ok":"pass","passed":"pass","success":"pass","succeeded":"pass","verified":"pass","warn":"warning",
            "failed":"fail","error":"fail","unknown":"blocked","unverified":"blocked","skipped":"blocked"}


@dataclass(frozen=True)
class VerificationResult:
    status: str
    reason_code: str
    checks: list
    schema_version: int = 1

    def to_dict(self):
        return dict(asdict(self),manual_review_required=self.status!="pass")


def explicit_readback(result):
    """A generic ok flag does not establish task success for writes."""
    return isinstance(result,dict) and result.get("ok") is True and result.get("task_verified") is True


def _status(value):
    if not isinstance(value,str):
        return "blocked"
    value = value.strip().casefold()
    return _ALIASES.get(value,value if value in _RANK else "blocked")


def verification_result(result, *, read_only=False, delivery=None):
    checks = []
    if not isinstance(result,dict):
        return VerificationResult("blocked","verification_unavailable",checks)
    if result.get("mutation_state")=="unknown" or result.get("state")=="unknown":
        return VerificationResult("blocked","mutation_unknown",checks)
    if result.get("ok") is not True:
        return VerificationResult("fail","operation_failed",checks)

    if delivery is not None:
        base = "pass" if delivery.get("ok") is True else "blocked"
        reason = "output_content_verified" if base=="pass" else "output_evidence_failed"
    elif read_only or explicit_readback(result):
        base, reason = "pass","read_completed" if read_only else "explicit_readback"
    else:
        base, reason = "blocked","verification_unavailable"

    supplied = result.get("verification_checks")
    if supplied is not None:
        if not isinstance(supplied,list) or not supplied:
            return VerificationResult("blocked","verification_unavailable",checks)
        for row in supplied:
            if not isinstance(row,dict):
                checks.append(dict(id="invalid_check",status="blocked",required=True))
                continue
            status = _status(row.get("status"))
            required = row.get("required") is not False
            if not required and status in {"fail","blocked"}:
                status = "warning"
            checks.append(dict(id=row.get("id"),status=status,required=required))
        worst = max((check["status"] for check in checks),key=_RANK.get)
        if _RANK[worst]>_RANK[base]:
            base, reason = worst,"readback_checks"
    return VerificationResult(base,reason,checks)
