"""The MCP gateway publishes four facades and keeps implementations private."""
import inspect
from typing import get_type_hints

from .core.approval import ApprovalStore
from .core.delivery import atlas_sources, capture_delivery, finalize_delivery
from .core.state import Execution, execute
from .core.trace import CURRENT_EXECUTION
from .core.verify import verification_result
from .discovery import rank_operations
from .operation_policy import classify, effective_risk, output_paths

_FILE_PROOF = {"sw_produce_drawing", "sw_export_pdf", "sw_make_atlas"}


class Gateway:
    def __init__(self, enabled_groups=None, approvals=None):
        self.registry = {}
        self.enabled_groups = set(("system","model","assembly","drawing","review","delivery")
                                  if enabled_groups is None else enabled_groups)
        self.approvals = approvals or ApprovalStore()
        self.executions = []

    def register(self, fn):
        from pydantic import create_model

        sig = inspect.signature(fn)
        hints = get_type_hints(fn)
        fields = {k:(hints.get(k,object),... if p.default is inspect.Parameter.empty else p.default)
                  for k,p in sig.parameters.items()}
        name = fn.__name__
        model = create_model(name+"_arguments",__config__={"extra":"forbid"},**fields)
        group,risk = classify(name)
        self.registry[name] = dict(fn=fn,model=model,group=group,risk=risk,description=inspect.getdoc(fn) or "")
        return fn

    def discover(self, group=None, query=None, limit=None):
        rows = [dict(name=name,group=row["group"],risk=row["risk"],
                     enabled=row["group"] in self.enabled_groups and row["risk"]!="unknown")
                for name,row in self.registry.items() if group is None or row["group"]==group]
        if query is not None and (not isinstance(query,str) or not 1<=len(query.strip())<=512):
            return dict(ok=False,error="invalid_query",reason="Query must contain 1 to 512 characters")
        if limit is not None and (type(limit) is not int or not 1<=limit<=20):
            return dict(ok=False,error="invalid_limit",reason="Limit must be an integer between 1 and 20")
        if query is not None:
            rows = rank_operations(query,[dict(r,description=self.registry[r["name"]]["description"]) for r in rows],
                                   limit if limit is not None else 5)
        elif limit is not None:
            rows = rows[:limit]
        return dict(ok=True,groups=sorted(self.enabled_groups),operations=rows)

    def describe(self, names):
        from .capability_matrix import capability

        operations = []
        for name in names:
            row = self.registry.get(name)
            if row is None:
                operations.append(dict(name=name,error="unregistered"))
                continue
            cap = capability(name)
            operations.append(dict(name=name,description=row["description"],group=row["group"],
                risk=row["risk"],effect=row["risk"],approval_required=row["risk"]=="destructive",
                approval_if_output_exists=row["risk"]=="write",
                available=row["group"] in self.enabled_groups and row["risk"]!="unknown" and cap["status"]!="blocked",
                inputSchema=row["model"].model_json_schema(),capability=cap))
        return dict(ok=True,operations=operations)

    def invoke(self, name, args, approval_token=None):
        from .capability_matrix import capability

        row = self.registry.get(name)
        if row is None:
            return dict(ok=False,error="unregistered")
        if row["risk"]=="unknown":
            return dict(ok=False,error="effect_unregistered")
        if row["group"] not in self.enabled_groups:
            return dict(ok=False,error="group_disabled",group=row["group"])
        try:
            arguments = row["model"].model_validate(args).model_dump()
            cap = capability(name)
            if cap["status"]=="blocked":
                return dict(ok=False,error="capability_blocked",capability=cap)
            risk = effective_risk(name,row["risk"],arguments)
            if risk=="destructive":
                if not approval_token:
                    return dict(ok=False,error="approval_required",effect=risk,
                                reason="Destructive operation or existing output")
                from .guard import active_path, switches_detected
                self.approvals.consume(approval_token,name,arguments,active_path=active_path(),
                                       switch_count=switches_detected()["count"])
            return self._execute(name,row,arguments,risk,cap)
        except Exception as exc:
            return dict(ok=False,error=f"{type(exc).__name__}: {exc}")

    def _execute(self, name, row, arguments, risk, cap):
        baseline = None
        if name in _FILE_PROOF:
            paths = [arguments[key] for key in ("model_path","drawing_path") if arguments.get(key)]
            if name=="sw_make_atlas":
                paths.extend(atlas_sources(arguments["pages"]))
            baseline = capture_delivery(output_paths(name,arguments),paths)
        record = Execution(name,arguments)
        self.executions.append(record)
        marker = CURRENT_EXECUTION.set(record)
        delivery = None
        verdict = None

        def verify(result):
            nonlocal delivery,verdict
            if baseline is not None:
                delivery = finalize_delivery(baseline,tool_success=True,verified=True)
            verdict = verification_result(result,read_only=risk=="read",delivery=delivery)
            return verdict.status=="pass"

        try:
            result = execute(record,lambda:row["fn"](**arguments),verify)
        finally:
            CURRENT_EXECUTION.reset(marker)
        if verdict is None:
            verdict = verification_result(result,read_only=risk=="read")
        response = dict(result) if isinstance(result,dict) else dict(ok=False,result=result)
        # The handler's file claims are never evidence for an operation.
        if baseline is not None:
            response.pop("artifact",None)
            response.pop("delivery",None)
            if delivery is not None:
                response.update(artifact=delivery["entries"][0],delivery=delivery)
        response.update(execution=record.as_dict(),capability=cap,verification=verdict.to_dict())
        return response

    def status(self, connect=False):
        from .capability_matrix import host_status
        return dict(host_status(connect),executions=[r.as_dict() for r in self.executions[-20:]],
                    enabled_groups=sorted(self.enabled_groups))
