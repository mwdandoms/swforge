"""Only four MCP facades are public; registered implementations stay private."""
import inspect
import os
from pathlib import Path
from typing import get_type_hints
from .core.state import Execution,execute
from .core.trace import CURRENT_EXECUTION
from .core.approval import ApprovalStore


def classify(name):
    if name in ('sw_close_all','sw_purge_giant','sw_purge_small','sw_sweep_documents'):
        return 'admin','destructive'
    if name in ('sw_ping','sw_capabilities','sw_resources','sw_resource_status'):
        return 'system','read'
    if any(x in name for x in ('check','inspect','review','audit','snapshot','suggest','list','read','preview','plan','validate')):
        return 'review','read'
    if any(x in name for x in ('export','atlas','bom')):
        return 'delivery','write'
    if any(x in name for x in ('drawing','dimension','tolerance','gdt','surface','title','requirements','styles','layout')):
        return 'drawing','write'
    return ('assembly' if any(x in name for x in ('assembly','mates')) else 'model'),'write'


class Gateway:
    def __init__(self, enabled_groups=None, approvals=None):
        self.registry={}
        self.enabled_groups=set(('system','model','assembly','drawing','review','delivery') if enabled_groups is None else enabled_groups)
        self.approvals=approvals or ApprovalStore()
        self.executions=[]

    def register(self,fn):
        from pydantic import create_model
        sig=inspect.signature(fn);hints=get_type_hints(fn)
        fields={k:(hints.get(k,object),... if p.default is inspect.Parameter.empty else p.default) for k,p in sig.parameters.items()}
        args_model=create_model(fn.__name__+'_arguments',__config__={'extra':'forbid'},**fields)
        group,risk=classify(fn.__name__)
        self.registry[fn.__name__]=dict(fn=fn,model=args_model,group=group,risk=risk,description=inspect.getdoc(fn) or '')
        return fn

    def discover(self,group=None):
        return dict(ok=True,groups=sorted(self.enabled_groups),operations=[dict(name=n,group=r['group'],risk=r['risk'],enabled=r['group'] in self.enabled_groups) for n,r in self.registry.items() if group is None or r['group']==group])

    def describe(self,names):
        from .capability_matrix import capability
        return dict(ok=True,operations=[dict(name=n,description=self.registry[n]['description'],group=self.registry[n]['group'],risk=self.registry[n]['risk'],inputSchema=self.registry[n]['model'].model_json_schema(),capability=capability(n)) if n in self.registry else dict(name=n,error='unregistered') for n in names])

    def invoke(self,name,args,approval_token=None):
        from .capability_matrix import capability
        if name not in self.registry:
            return dict(ok=False,error='unregistered')
        row=self.registry[name]
        if row['group'] not in self.enabled_groups:
            return dict(ok=False,error='group_disabled',group=row['group'])
        try:
            arguments=row['model'].model_validate(args).model_dump()
            cap=capability(name)
            if cap['status']=='blocked':
                return dict(ok=False,error='capability_blocked',capability=cap)
            destructive=row['risk']=='destructive'
            if row['risk']=='write':
                destructive=any(isinstance(v,str) and Path(v).is_file() for k,v in arguments.items() if k in ('out_path','pdf_path','out_pdf'))
            if destructive:
                if not approval_token:
                    return dict(ok=False,error='approval_required',reason='Destructive operation or existing output')
                from .guard import active_path,switches_detected
                self.approvals.consume(approval_token,name,arguments,active_path=active_path(),switch_count=switches_detected()['count'])
            record=Execution(name,arguments)
            self.executions.append(record)
            marker=CURRENT_EXECUTION.set(record)
            def verify(result):
                if row['risk']=='read':
                    return isinstance(result,dict) and result.get('ok') is True
                return isinstance(result,dict) and (result.get('task_verified') is True or result.get('artifact',{}).get('produced_this_run') is True)
            try:
                result=execute(record,lambda:row['fn'](**arguments),verify)
            finally:
                CURRENT_EXECUTION.reset(marker)
            return dict(result,execution=record.as_dict(),capability=cap) if isinstance(result,dict) else dict(ok=True,result=result,execution=record.as_dict())
        except Exception as exc:
            return dict(ok=False,error=f'{type(exc).__name__}: {exc}')

    def status(self,connect=False):
        from .capability_matrix import host_status
        return dict(host_status(connect),executions=[r.as_dict() for r in self.executions[-20:]],enabled_groups=sorted(self.enabled_groups))
