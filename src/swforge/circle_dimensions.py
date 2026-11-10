"""Explicit diameter dimensions on visible circular edges; no hole/boss inference."""
from __future__ import annotations
import math
import os
from .annotations import _drawing,_active,_wrap,_project_point,_position
from .session import _value


def _circles(md,view_name,objects=False,only_index=None):
    import pythoncom
    from win32com.client import VARIANT
    from .views_extra import _pick_view
    view,name,error=_pick_view(md,view_name)
    if view is None:raise ValueError(error)
    matrix=list(_value(_value(view,'ModelToViewTransform'),'ArrayData'))
    edges=view.GetVisibleEntities2(VARIANT(pythoncom.VT_DISPATCH,None),1) or []
    rows=[]
    for index,item in enumerate(edges):
        # A caller-supplied edge index is still checked against freshly read geometry.
        # Avoid thousands of unrelated late-bound curve calls on patterned gears.
        if only_index is not None and index!=only_index:continue
        edge=_wrap(item);curve=_wrap(_value(edge,'GetCurve'))
        if not bool(_value(curve,'IsCircle')):continue
        c=list(_value(curve,'CircleParams'))
        center=_project_point(c[:3],matrix)
        end=_project_point([c[i]+c[i+3] for i in range(3)],matrix)
        # Only face-on circles: projected axis must be negligible.
        if math.hypot(end[0]-center[0],end[1]-center[1])>1e-6:continue
        row={'drawing':str(_value(md,'GetPathName')),'view':name,'edge_index':index,'diameter_mm':c[6]*2000,
             'center_model_mm':[v*1000 for v in c[:3]],'center_sheet_m':center}
        sv=_wrap(_value(edge,'GetStartVertex'));ev=_wrap(_value(edge,'GetEndVertex'))
        row['full_circle']=sv is None or ev is None or sum((a-b)**2 for a,b in zip(_value(sv,'GetPoint'),_value(ev,'GetPoint')))<1e-18
        if objects:row['edge_obj']=edge
        rows.append(row)
    return view,rows


def list_drawing_circles(drawing_path,view_name):
    """Read visible face-on circular edges, including bosses/arcs; caller chooses target."""
    try:
        sw,md=_drawing(drawing_path)
        _,rows=_circles(md,view_name)
        _active(sw,md)
        return {'ok':True,'drawing':os.path.abspath(drawing_path),'circles':rows,
                'note':'Explicit geometry targets; does not classify holes versus bosses'}
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}','circles':[]}


def add_diameter_dimension(drawing_path,circle,x,y):
    """Attach a native diameter dimension to an exact freshly enumerated circle.

    Positions use sheet metres; readback nominal is mm. Changes memory only.
    Check modified on failure; failed mutations must not be automatically retried.
    """
    modified=False
    try:
        if not isinstance(circle,dict) or set(('drawing','view','edge_index','diameter_mm','center_model_mm'))-set(circle):
            raise ValueError('circle must be a list_drawing_circles row')
        sw,md=_drawing(drawing_path)
        if os.path.normcase(os.path.abspath(circle['drawing']))!=os.path.normcase(os.path.abspath(str(_value(md,'GetPathName')))):
            raise ValueError('Circle reference belongs to another drawing')
        view,rows=_circles(md,circle['view'],True,only_index=circle['edge_index'])
        matches=[r for r in rows if r['edge_index']==circle['edge_index']]
        if len(matches)!=1:raise ValueError('Circle is missing; enumerate again')
        target=matches[0]
        if abs(target['diameter_mm']-circle['diameter_mm'])>1e-6 or len(circle['center_model_mm'])!=3 or any(abs(a-b)>1e-6 for a,b in zip(target['center_model_mm'],circle['center_model_mm'])):
            raise ValueError('Circle geometry changed since enumeration')
        x,y=_position(md,x,y,circle['view'],0,0)
        # Do not silently create a second diameter on the same circular geometry.
        display=_wrap(_value(view,'GetFirstDisplayDimension5'))
        while display is not None:
            annotation=_wrap(_value(display,'GetAnnotation'))
            for item in _value(annotation,'GetAttachedEntities3') or []:
                try:
                    curve=_wrap(_value(_wrap(item),'GetCurve'))
                    if not bool(_value(curve,'IsCircle')):continue
                    c=list(_value(curve,'CircleParams'))
                    if abs(c[6]*2000-target['diameter_mm'])<1e-6 and all(abs(c[i]*1000-target['center_model_mm'][i])<1e-6 for i in range(3)):
                        raise ValueError('A dimension already references this circle')
                except ValueError:raise
                except Exception:continue
            display=_wrap(_value(display,'GetNext5'))
        _active(sw,md)
        md.ClearSelection2(True);md.ActivateView(circle['view'])
        if not view.SelectEntity(target['edge_obj'],False):raise RuntimeError('Cannot select requested circular edge')
        dimension=_wrap(md.AddDiameterDimension2(x,y,0))
        if dimension is None:raise RuntimeError('Native diameter dimension returned null')
        modified=True
        native=_wrap(dimension.GetDimension2(0))
        got=float(_value(native,'SystemValue'))*1000
        annotation=_wrap(_value(dimension,'GetAnnotation'))
        if abs(got-target['diameter_mm'])>1e-6 or bool(_value(annotation,'IsDangling')):
            raise RuntimeError('Diameter readback mismatch or dangling native annotation')
        md.ClearSelection2(True);_active(sw,md)
        return {'ok':True,'modified':True,'name':str(_value(native,'FullName')),'view':circle['view'],
                'diameter_mm':got,'attached_entity_count':int(_value(annotation,'GetAttachedEntityCount3')),
                'position_m':list(_value(annotation,'GetPosition')),'review_required':True}
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}','modified':modified}


def add_curated_diameters(drawing_path,*,limit=6):
    """Bounded full-circle diameters; no automatic hole/boss classification."""
    from .drawing import _view_list
    from .drawing_review import drawing_snapshot
    if isinstance(limit,bool) or not isinstance(limit,int) or not 0<=limit<=12:
        raise ValueError('limit must be integer 0..12')
    sw,md=_drawing(drawing_path)
    existing=[d for v in drawing_snapshot(drawing_path)['views'] for d in v['dimensions'] if d['type']==6]
    seen=set();results=[]
    for view,name in _view_list(md):
        _,circles=_circles(md,name)
        outline=list(_value(view,'GetOutline'))
        for c in sorted(circles,key=lambda r:r['diameter_mm']):
            if not c['full_circle']:continue
            key=(round(c['diameter_mm'],5),tuple(round(x,5) for x in c['center_model_mm']))
            # Front/back coplanar circles describe the same projected cylinder.
            projected=(round(c['diameter_mm'],5),round(c['center_sheet_m'][0],7),round(c['center_sheet_m'][1],7),name)
            if key in seen or projected in seen:continue
            seen.add(key);seen.add(projected)
            if len(results)>=limit:break
            if any(d['view']==name and abs(d.get('value_mm',0)-c['diameter_mm'])<1e-5 for d in existing):continue
            x=outline[2]+.012
            y=max(.012,min(.28,outline[3]-.009-len(results)*.009))
            result=add_diameter_dimension(drawing_path,c,x,y);result['target']=c;results.append(result)
    return {'ok':all(r['ok'] for r in results),'added':sum(r['ok'] for r in results),'results':results,
            'review_required':True,'note':'Full-circle geometry only; no machining or dimension-completeness inference'}
