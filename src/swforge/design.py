"""Explicit design parameters and copy-only recipe regeneration (not native equations)."""
from __future__ import annotations
import ast
import copy
import json
import math
import operator
from pathlib import Path

_OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
_CMP={ast.Lt:operator.lt,ast.LtE:operator.le,ast.Gt:operator.gt,ast.GtE:operator.ge,ast.Eq:operator.eq,ast.NotEq:operator.ne}

def _numeric(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Design values must be finite numbers')
    if abs(value)>1e9:
        raise ValueError('Design value exceeds 1e9')
    return value

def _expression(value,lookup,comparison=False):
    if not isinstance(value,str) or not value.startswith('=') or len(value)>256:
        return _numeric(value)
    try:root=ast.parse(value[1:],mode='eval').body
    except SyntaxError as exc:raise ValueError('Invalid design expression: '+value) from exc
    def walk(node):
        if isinstance(node,ast.Constant):return _numeric(node.value)
        if isinstance(node,ast.Name):return lookup(node.id)
        if isinstance(node,ast.BinOp) and type(node.op) in _OPS:
            try:return _numeric(_OPS[type(node.op)](walk(node.left),walk(node.right)))
            except ZeroDivisionError as exc:raise ValueError('Division by zero in '+value) from exc
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return _numeric(walk(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1))
        if comparison and isinstance(node,ast.Compare):
            left=walk(node.left)
            for op,right_node in zip(node.ops,node.comparators):
                if type(op) not in _CMP:raise ValueError('Unsupported comparison')
                right=walk(right_node)
                if not _CMP[type(op)](left,right):return False
                left=right
            return True
        raise ValueError('Only numbers, parameter names and + - * / are allowed: '+value)
    return walk(root)

def resolve_design(spec,parameters=None):
    """Resolve a bounded arithmetic DAG and explicit requirements without connecting SW."""
    if not isinstance(spec,dict):raise ValueError('spec must be an object')
    raw=copy.deepcopy(spec.get('parameters',{}))
    if not isinstance(raw,dict) or len(raw)>64 or any(not isinstance(k,str) or not k.isidentifier() for k in raw):
        raise ValueError('parameters must contain at most 64 identifier names')
    if parameters is not None:
        if not isinstance(parameters,dict) or set(parameters)-set(raw):raise ValueError('Unknown design parameter override')
        for k,v in parameters.items():raw[k]=_numeric(v)
    resolved={};visiting=set()
    def lookup(name):
        if name in resolved:return resolved[name]
        if name not in raw:raise ValueError('Unknown design parameter: '+name)
        if name in visiting:raise ValueError('Cyclic design parameter: '+name)
        visiting.add(name)
        resolved[name]=_numeric(_expression(raw[name],lookup));visiting.remove(name)
        return resolved[name]
    for name in raw:lookup(name)
    requirements=spec.get('requirements',[])
    if not isinstance(requirements,list) or len(requirements)>64:raise ValueError('requirements must be an array of at most 64 comparisons')
    for rule in requirements:
        if not isinstance(rule,str) or not rule.startswith('=') or _expression(rule,lookup,True) is not True:
            raise ValueError('Design requirement failed: '+str(rule))
    bindings=[]
    def substitute(value,path):
        if isinstance(value,str) and value.startswith('='):
            bindings.append({'field':path,'expression':value})
            return _numeric(_expression(value,lookup))
        if isinstance(value,dict):return {k:substitute(v,path+'.'+k) for k,v in value.items()}
        if isinstance(value,list):return [substitute(v,f'{path}[{i}]') for i,v in enumerate(value)]
        return value
    body={k:v for k,v in spec.items() if k not in ('parameters','requirements')}
    return {'ok':True,'parameters':resolved,'bindings':bindings,'spec':substitute(body,'spec'),
            'requirements':requirements,'native_equations':False}

def create_design_variant(source_path,out_path,parameters,*,keep_open=False,max_documents=8):
    """Rebuild a new part from its fingerprinted design sidecar; never overwrite a source.

    This creates new native feature identities. Use create_variant for native dimension
    edits that must preserve the existing feature structure; do not substitute assembled
    components automatically with regenerated parts.
    """
    from .variants import file_sha256
    from .session import get_session,_value
    from .spec import builder_from_spec
    try:
        source=Path(source_path).resolve();output=Path(out_path).resolve()
        if source==output or output.exists() or source.name.casefold()==output.name.casefold():
            raise ValueError('Use a new output filename')
        manifest=json.loads(Path(str(source)+'.design.json').read_text(encoding='utf8'))
        if manifest.get('schema')!=1 or file_sha256(source)!=manifest['model_sha256']:
            raise ValueError('Source model differs from its design manifest; reconcile manual edits first')
        sw=get_session().sw();opened=sw.GetOpenDocumentByName(str(source))
        if opened is not None and _value(opened,'GetSaveFlag'):
            raise ValueError('Source has unsaved changes')
        new_spec=copy.deepcopy(manifest['design'])
        resolve_design(new_spec,parameters)  # Validate overrides, including unknown names.
        new_spec['parameters'].update(parameters)
        builder=builder_from_spec(str(output),new_spec)
        result=builder.build(keep_open=keep_open,max_documents=max_documents)
        unchanged=file_sha256(source)==manifest['model_sha256']
        if not unchanged:result.ok=False;result.error='Source changed during regeneration'
        return dict(result.__dict__,source_unchanged=unchanged,
                    edit_mode='recipe_regeneration',feature_identity_preserved=False)
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}
