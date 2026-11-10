"""Read-only drawing checks with explicit coverage and model revision fingerprints."""
from __future__ import annotations
import itertools
import json
import math
from pathlib import Path

from .native_bridge import target_document,run_native


def drawing_snapshot(drawing_path):
    _,_,target=target_document(drawing_path,3)
    result=run_native(dict(target,mode='drawing'))
    if not result.get('ok'):
        raise RuntimeError(result.get('error','Drawing inspection failed')+' '+result.get('details',''))
    return result


def _intersection(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def review_snapshot(snapshot,required_properties=None,*,spacing_mm=2):
    """Evaluate a native snapshot without COM; text extents are explicitly heuristic."""
    if not isinstance(snapshot,dict) or not snapshot.get('ok'):
        raise ValueError('A valid native drawing snapshot is required')
    if isinstance(spacing_mm,bool) or not math.isfinite(float(spacing_mm)) or not 0<float(spacing_mm)<=20:
        raise ValueError('spacing_mm must be in (0,20]')
    if required_properties is not None and (not isinstance(required_properties,list) or any(not isinstance(x,str) or not x for x in required_properties)):
        raise ValueError('required_properties must be a list of exact property names')
    width,height=snapshot['width_m'],snapshot['height_m']
    if not width>0 or not height>0:
        raise ValueError('Invalid sheet dimensions')
    findings=[]
    def issue(code,severity,**details):
        findings.append(dict(code=code,severity=severity,**details))
    views=snapshot['views'];margin=1e-6
    if snapshot.get('drawing_modified'):
        issue('drawing_unsaved_changes','warning',reason='Current memory state differs from saved drawing')
    for view in views:
        a=view['outline_m']
        if a[0]<-margin or a[1]<-margin or a[2]>width+margin or a[3]>height+margin:
            issue('view_outside_sheet','error',view=view['name'],outline_m=a)
        if not view['reference_loaded'] or not view['configuration_exists']:
            issue('model_reference_unresolved','error',view=view['name'],model=view['model_path'],configuration=view['configuration'])
        if view.get('model_modified'):
            issue('model_unsaved_changes','warning',view=view['name'],model=view['model_path'])
    for a,b in itertools.combinations(views,2):
        area=_intersection(a['outline_m'],b['outline_m'])
        if area>1e-8:
            issue('view_overlap','warning',views=[a['name'],b['name']],overlap_mm2=area*1e6)
    dims=[dim for view in views for dim in view.get('dimensions',[])]
    for annotation in snapshot['annotations']:
        if annotation['dangling']:
            issue('dangling_annotation','error',view=annotation['view'],annotation_type=annotation['type'])
        p=annotation['position_m']
        if p and (p[0]<-margin or p[1]<-margin or p[0]>width+margin or p[1]>height+margin):
            issue('annotation_anchor_outside_sheet','error',view=annotation['view'],position_m=p)
        bounds=annotation.get('bounds_m')
        # Native font glyph extents on GB zone labels overshoot the paper by ~0.022 mm.
        # Allow 0.05 mm font/numeric noise; displaced tables still fail by centimetres.
        extent_margin=.00005
        if bounds and (bounds[0]<-extent_margin or bounds[1]<-extent_margin or bounds[2]>width+extent_margin or bounds[3]>height+extent_margin):
            issue('annotation_extent_outside_sheet','error',view=annotation['view'],bounds_m=bounds,source=annotation.get('bounds_source'))
    for a,b in itertools.combinations(dims,2):
        p,q=a['position_m'],b['position_m']
        if not p or not q:continue
        h=max(a.get('char_height_m',.0035),b.get('char_height_m',.0035))
        wa=max(.003,len(a.get('text',''))*h*.65);wb=max(.003,len(b.get('text',''))*h*.65)
        if abs(p[0]-q[0])<(wa+wb)/2+spacing_mm/1000 and abs(p[1]-q[1])<h:
            issue('dimension_text_overlap_possible','warning',dimensions=[a['name'],b['name']],method='estimated text width; manual review required')
    for name in required_properties or []:
        if not str(snapshot.get('properties',{}).get(name,'')).strip():
            issue('required_property_missing','error',property=name)
    return {'ok':True,'passed':not any(f['severity']=='error' for f in findings),'findings':findings,
        'sheet':snapshot['sheet'],'views_checked':len(views),'dimensions_checked':len(dims),
        'coverage':{'sheets':'current sheet only','other_sheet_count':max(0,len(snapshot.get('sheet_names',[]))-1),
                    'view_bounds':'native outline','dangling':'native IsDangling','dimension_overlap':'heuristic',
                    'dimension_completeness':'not assessed','machining_suitability':'not assessed'},
        'review_required':True,'ready_for_manufacture':False}


def _revision_path(drawing_path):
    return Path(str(Path(drawing_path).resolve())+'.swforge-revision.json')


def record_drawing_revision(drawing_path):
    """Record fingerprints of saved referenced models; does not claim engineering approval."""
    from .variants import file_sha256
    try:
        snap=drawing_snapshot(drawing_path)
        if snap.get('drawing_modified'):
            raise ValueError('Save the drawing explicitly before recording a revision fingerprint')
        if any(v.get('model_modified') for v in snap['views']):
            raise ValueError('Cannot stamp a drawing against models with unsaved changes')
        models={}
        for view in snap['views']:
            model=Path(view['model_path']).resolve()
            if not model.is_file() or not view['reference_loaded'] or not view['configuration_exists']:
                raise ValueError('Cannot stamp an unresolved model reference')
            models[str(model)]=file_sha256(model)
        if not models:
            raise ValueError('No model views to fingerprint')
        stamp={'schema':1,'drawing':str(Path(drawing_path).resolve()),'drawing_sha256':file_sha256(drawing_path),
               'models':models,'configurations':{v['name']:v['configuration'] for v in snap['views']},
               'review_required':True,'ready_for_manufacture':False}
        path=_revision_path(drawing_path)
        path.write_text(json.dumps(stamp,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        return {'ok':True,'manifest':str(path),'models':models}
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def audit_drawing(drawing_path,required_properties=None,*,spacing_mm=2):
    """Inspect current sheet without edits; missing revision evidence is unverified."""
    from .variants import file_sha256
    try:
        snap=drawing_snapshot(drawing_path)
        result=review_snapshot(snap,required_properties,spacing_mm=spacing_mm)
        path=_revision_path(drawing_path)
        revision={'status':'unverified','reason':'No fingerprint manifest; currentness not inferred from timestamps'}
        if path.is_file():
            stamp=json.loads(path.read_text(encoding='utf8'))
            current_models={str(Path(v['model_path']).resolve()) for v in snap['views']}
            expected_configs={v['name']:v['configuration'] for v in snap['views']}
            reasons=[]
            if stamp.get('schema')!=1 or stamp.get('drawing')!=str(Path(drawing_path).resolve()):
                reasons.append('manifest identity mismatch')
            if set(stamp.get('models',{}))!=current_models or stamp.get('configurations')!=expected_configs:
                reasons.append('model references or configurations changed')
            for model,expected in stamp.get('models',{}).items():
                if not Path(model).is_file() or file_sha256(model)!=expected:
                    reasons.append('model fingerprint changed: '+model)
            if file_sha256(drawing_path)!=stamp.get('drawing_sha256'):
                reasons.append('drawing fingerprint changed')
            revision={'status':'mismatch' if reasons else 'unverified' if snap.get('drawing_modified') else 'matched','reasons':reasons}
            if reasons:
                result['findings'].append({'code':'revision_mismatch','severity':'error','reasons':reasons})
                result['passed']=False
        result['revision']=revision
        result['path']=snap['path']
        return result
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def suggest_drawing_layout(drawing_path):
    """Read-only proposed view centers using the existing native view outlines.

    Does not move annotations or promise globally optimal packing. Use the existing
    normalize_layout on owned drawings and audit again before accepting changes.
    """
    try:
        snap=drawing_snapshot(drawing_path)
        views=snap['views'];width=snap['width_m'];height=snap['height_m']
        if not 1<=len(views)<=3:
            raise ValueError('v1.5 layout suggestions support 1-3 model views')
        centers=[(.30*width,.62*height),(.30*width,.30*height),(.68*width,.62*height)]
        proposal=[]
        for view,(x,y) in zip(views,centers):
            box=view['outline_m'];p=view['position_m']
            moved=[box[0]+x-p[0],box[1]+y-p[1],box[2]+x-p[0],box[3]+y-p[1]]
            if moved[0]<.01 or moved[1]<.02 or moved[2]>width-.01 or moved[3]>height-.01:
                raise ValueError('Views do not fit at the current scale; adjust scale or sheet before moving')
            proposal.append({'view':view['name'],'before_m':p,'proposed_position_m':[x,y],'proposed_outline_m':moved})
        if any(_intersection(a['proposed_outline_m'],b['proposed_outline_m'])>1e-8 for a,b in itertools.combinations(proposal,2)):
            raise ValueError('Proposed view rectangles overlap; manual layout required')
        return {'ok':True,'dry_run':True,'proposal':proposal,'review_required':True,'scope':'view centers only; title block and text packing require review'}
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}','dry_run':True}
