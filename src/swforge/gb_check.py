"""Drawing-family completeness checks, separate from native collection.

GBSpec is a caller's inspection contract, not a proof of GB conformity or
manufacturability. Property text alone cannot prove visible drawing content.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass
class GBSpec:
    min_views: int = 2
    min_dimensions: int = 6
    max_dangling: int = 0
    require_title_block: tuple = ('图样名称', '图样代号', '材料', '比例')
    require_tech_requirements: bool = True
    require_projection_symbol: bool = True
    require_surface_finish: bool = True
    require_tolerance: bool = True
    # Each row: kind (linear/diameter/position), value_mm, optional name/view.
    required_dimensions: list[dict] = field(default_factory=list)
    placeholder_values: frozenset = frozenset({'图样名称','图样代号','材料','比例','设计','设计者',''})


DEMO_SPEC = GBSpec(min_views=3, min_dimensions=8)


def collect_drawing_snapshot(drawing_path=None):
    from .drawing_review import drawing_snapshot
    from .annotations import _drawing
    from .session import _value
    try:
        if drawing_path is None:
            _, md = _drawing(None)
            drawing_path = str(_value(md, 'GetPathName'))
            if not drawing_path:
                raise ValueError('Save the drawing before collecting a guarded snapshot')
        result=drawing_snapshot(drawing_path)
        from .gb_styles import read_gb_styles
        result['gb_native']=read_gb_styles(drawing_path)
        return result
    except Exception as exc:
        return {'ok':False, 'error':f'{type(exc).__name__}: {exc}'}


def evaluate_gb_completeness(snapshot, spec=None):
    spec = spec or GBSpec()
    if not snapshot.get('ok'):
        return dict(ok=False, status='FAILED', critical=['取数失败：'+str(snapshot.get('error'))],
                    warning=[], info=[], facts={}, ready_for_manufacture=False)
    views = snapshot.get('views', [])
    dims = [d for v in views for d in v.get('dimensions', [])]
    annotations = snapshot.get('annotations', [])
    # A display dimension may also occur in annotations; count each once.
    dangling = [a for a in annotations if a.get('dangling')]
    if not annotations:
        dangling = [d for d in dims if d.get('dangling')]
    props = snapshot.get('properties', {})
    notes = [str(a.get('text','')).strip() for a in annotations if a.get('text')]
    visible = '\n'.join(notes)
    critical, warning = [], []
    if len(views) < spec.min_views: critical.append(f'视图数 {len(views)} 少于约定 {spec.min_views}')
    if len(dims) < spec.min_dimensions: critical.append(f'尺寸数 {len(dims)} 少于图样族约定 {spec.min_dimensions}')
    if len(dangling) > spec.max_dangling: critical.append(f'悬空标注 {len(dangling)} 个')
    for key in spec.require_title_block:
        value = str(props.get(key,'')).strip()
        if value in spec.placeholder_values: critical.append(f'标题栏「{key}」缺失或仍为占位符')
        elif not any(value in t for t in notes): critical.append(f'标题栏「{key}」只有属性，未回读到可见文字')
    tech = str(props.get('技术要求','')).strip()
    if spec.require_tech_requirements and (not tech or not all(t.strip() in visible for t in tech.splitlines() if t.strip())):
        critical.append('未回读到图纸上的技术要求区块')
    if spec.require_projection_symbol:
        native=snapshot.get('gb_native',{})
        if not native.get('evidence',{}).get('projection',{}).get('passed'):
            critical.append('未验证第一角投影属性及原生图形符号；文字说明不算图形符号')
    if spec.require_surface_finish and not any(a.get('type')==1 for a in annotations):
        warning.append('未检出原生表面粗糙度符号')
    if spec.require_tolerance and not any(d.get('tolerance_type',0) not in (0,None) for d in dims):
        warning.append('未检出逐尺寸原生公差；通用要求不替代关键配合公差')
    matched = []
    for requirement in spec.required_dimensions:
        value = float(requirement['value_mm'])
        if not math.isfinite(value) or value <= 0: raise ValueError('Required nominal must be finite and positive')
        kind = requirement.get('kind','linear')
        if kind not in ('linear','diameter','position'): raise ValueError('Unknown required dimension kind')
        candidates = []
        for d in dims:
            if requirement.get('view') and d.get('view')!=requirement['view']:continue
            if requirement.get('name') and d.get('name')!=requirement['name']:continue
            if kind=='diameter' and d.get('type')!=6:continue
            if kind!='diameter' and d.get('type') not in (2,11,12):continue
            # Position must name an explicitly targeted native dimension. A 20mm
            # unrelated thickness is not evidence of a 20mm axial location.
            if kind=='position' and not requirement.get('name'):continue
            if abs(float(d.get('value_mm',-1))-value)>requirement.get('tolerance_mm',1e-5):continue
            if d.get('dangling') or d.get('attached_entity_count',0)<1:continue
            candidates.append(d['name'])
        matched.append(dict(requirement=requirement, matched=candidates))
        if not candidates:critical.append(f'缺少关键尺寸 {requirement.get("label",kind)} {value:g} mm')
    from .drawing_review import review_snapshot
    if all(k in snapshot for k in ('width_m','height_m','annotations','sheet')):
        layout = review_snapshot(snapshot)
        critical.extend(f'图纸检查：{f["code"]}' for f in layout['findings'] if f['severity']=='error')
        warning.extend(f'图纸复核：{f["code"]}' for f in layout['findings'] if f['severity']=='warning')
    status = 'FAILED' if critical else 'REVIEW' if warning else 'PASSED'
    return dict(ok=status!='FAILED', status=status, critical=critical, warning=warning, info=[],
                facts=dict(views=len(views),dimensions=len(dims),dangling=len(dangling),required_dimensions=matched),
                ready_for_manufacture=False, review_required=True,
                notes=['只核对当前页及调用方约定，不认证GB全条文或制造完整性；未指定关键尺寸的数量检查不能证明尺寸齐全。'])


def check_gb_drawing(drawing_path=None, spec=None, snapshot=None):
    return evaluate_gb_completeness(snapshot if snapshot is not None else collect_drawing_snapshot(drawing_path), spec)


def format_report(result):
    return '\n'.join([f'图纸完整性：{result["status"]}']+
                     [f'[{level}] {item}' for level,key in [('CRITICAL','critical'),('WARNING','warning')]
                      for item in result.get(key,[])])
