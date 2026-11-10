"""Multi-sheet creation, currentness, reserved-region checks and copy-only moves."""
from pathlib import Path
import json,math,shutil
from .session import _value,get_session
from .drawing_review import drawing_snapshot,review_snapshot,_intersection
from .native_bridge import target_document
from .variants import file_sha256


def _regions(regions):
    if regions is None:return {}
    if not isinstance(regions,dict):raise ValueError('Reserved regions must map sheet names to rectangle lists')
    for sheet,rectangles in regions.items():
        for r in rectangles:
            if len(r)!=4 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in r) or r[2]<=r[0] or r[3]<=r[1]:raise ValueError('Positive finite rectangles [left,bottom,right,top] in sheet metres required')
    return regions


def drawing_book_snapshot(drawing_path):
    sw,md,_=target_document(drawing_path,3);original=_value(_value(md,'GetCurrentSheet'),'GetName');rows=[]
    try:
        for name in _value(md,'GetSheetNames'):
            if not md.ActivateSheet(name):raise RuntimeError('Cannot activate sheet '+name)
            snap=drawing_snapshot(drawing_path)
            from .drawing import _view_list
            relations={}
            for view,vname in _view_list(md):
                base=_value(view,'GetBaseView')
                relations[vname]=dict(type=int(_value(view,'Type')),base=str(_value(base,'Name')) if base else '',position_locked=bool(view.PositionLocked))
            snap['relations']=relations;rows.append(snap)
        return dict(ok=True,drawing=str(Path(drawing_path).resolve()),active_sheet=original,sheets=rows,
                    model_fingerprints={v['model_path']:file_sha256(v['model_path']) for s in rows for v in s['views']})
    finally:md.ActivateSheet(original)


def review_drawing_book(drawing_path,*,reserved_regions=None):
    regions=_regions(reserved_regions);snap=drawing_book_snapshot(drawing_path);results=[]
    for sheet in snap['sheets']:
        result=review_snapshot(sheet)
        for rectangle in regions.get(sheet['sheet'],[]):
            for v in sheet['views']:
                if _intersection(v['outline_m'],rectangle)>1e-10:result['findings'].append(dict(code='view_in_reserved_region',severity='error',view=v['name'],region_m=rectangle))
            for a in sheet['annotations']:
                b=a.get('bounds_m')
                if b and a['view']!=sheet['sheet'] and _intersection(b,rectangle)>1e-10:result['findings'].append(dict(code='annotation_in_reserved_region',severity='error',annotation_type=a['type'],region_m=rectangle))
        result['passed']=not any(f['severity']=='error' for f in result['findings']);results.append(result)
    manifest=Path(str(Path(drawing_path).resolve())+'.book.json');current='unverified'
    if manifest.exists():
        stamp=json.loads(manifest.read_text(encoding='utf8'));current='matched' if stamp['model_fingerprints']==snap['model_fingerprints'] and stamp['drawing_sha256']==file_sha256(drawing_path) else 'stale'
    return dict(ok=True,passed=all(r['passed'] for r in results) and current!='stale',sheets=results,currentness=current,
                active_sheet_restored=snap['active_sheet'],review_required=True,ready_for_manufacture=False)


def stamp_drawing_book(drawing_path):
    snap=drawing_book_snapshot(drawing_path)
    if any(s.get('drawing_modified') or any(v.get('model_modified') for v in s['views']) for s in snap['sheets']):raise ValueError('Save book and models explicitly before stamping')
    stamp=dict(drawing_sha256=file_sha256(drawing_path),model_fingerprints=snap['model_fingerprints'],
               configurations={s['sheet']:{v['name']:v['configuration'] for v in s['views']} for s in snap['sheets']})
    Path(str(Path(drawing_path).resolve())+'.book.json').write_text(json.dumps(stamp,ensure_ascii=False,indent=2),encoding='utf8')
    return stamp


def create_drawing_book(model_paths,out_path):
    from .drawing import produce,normalize_layout,_save_as,_fit_new_template_notes
    from .resources import document_scope
    models=[str(Path(p).resolve()) for p in model_paths];out=Path(out_path).resolve()
    if not 1<=len(models)<=6 or any(not Path(p).is_file() for p in models):raise ValueError('1..6 existing model paths required')
    if out.exists() or out.suffix.lower()!='.slddrw':raise ValueError('New drawing path required')
    with document_scope(str(out),keep_open=False,related_paths=models) as lease:
        result=produce(models[0],str(out),keep_open=True)
        if not result['ok']:return result
        sw,md,_=target_document(out,3);lease.own(md);sheet=_value(md,'GetCurrentSheet');props=list(_value(sheet,'GetProperties'));template=_value(sheet,'GetTemplateName');layouts=[]
        from .gb_styles import gb_template_path
        packaged_format=str(Path(gb_template_path()).with_suffix('.slddrt'))
        if Path(packaged_format).is_file():template=packaged_format
        layouts.append(normalize_layout(str(out)))
        for index,path in enumerate(models[1:],2):
            from .resources import ensure_capacity
            if sw.GetOpenDocumentByName(path) is None:
                if not ensure_capacity(1)['allowed']:raise RuntimeError('Document limit before adding page')
                sw.OpenDoc(path,2 if path.lower().endswith('.sldasm') else 1)
                target_document(out,3)
            if not md.NewSheet4('SWFORGE_'+str(index),int(props[0]),12 if template else int(props[1]),float(props[2]),float(props[3]),bool(props[4]),template,float(props[5]),float(props[6]),'',.01,.01,.01,.01,4,6):raise RuntimeError('NewSheet4 failed')
            for orientation,x,y in [('*前视',.18,.20),('*上视',.18,.10),('*右视',.36,.20)]:
                if md.CreateDrawViewFromModelView3(path,orientation,x,y,0) is None:raise RuntimeError('Page view creation failed')
            _value(md,'EditRebuild3');_fit_new_template_notes(md);layouts.append(normalize_layout(str(out)))
        if not _save_as(md,str(out))[0]:raise RuntimeError('Book save failed')
        stamp=stamp_drawing_book(str(out));review=review_drawing_book(str(out))
        result=dict(ok=all(x['ok'] for x in layouts) and review['passed'],drawing=str(out),sheets=len(models),layouts=layouts,review=review,stamp=stamp)
        lease.failed=not result['ok'];return result


def layout_drawing_book(source_path,out_path,placements,*,reserved_regions=None):
    from .drawing import _view_list,_save_as
    from .resources import document_scope
    _regions(reserved_regions);source=Path(source_path).resolve();out=Path(out_path).resolve()
    if out.exists() or out.name.casefold()==source.name.casefold() or out.suffix.lower()!='.slddrw':raise ValueError('New drawing filename required')
    if not isinstance(placements,dict):raise ValueError('Map sheet -> view -> explicit [x,y] in metres')
    before=file_sha256(source);snap=drawing_book_snapshot(str(source));known={s['sheet']:s for s in snap['sheets']}
    for sheet,views in placements.items():
        if sheet not in known:raise ValueError('Unknown sheet')
        names={v['name'] for v in known[sheet]['views']}
        for name,xy in views.items():
            if name not in names or len(xy)!=2 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in xy):raise ValueError('Unknown view or invalid placement')
            if known[sheet]['relations'][name]['position_locked']:raise ValueError('View is position-locked; explicit constraint review required')
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as dst,source.open('rb') as src:shutil.copyfileobj(src,dst)
    with document_scope(str(out),keep_open=False) as lease:
        sw,md,_=target_document(out,3);lease.own(md)
        for sheet,views in placements.items():
            md.ActivateSheet(sheet)
            for view,name in _view_list(md):
                if name not in views:continue
                import pythoncom
                from win32com.client import VARIANT
                view.Position=VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,views[name]);actual=list(view.Position)
                if any(abs(a-b)>1e-7 for a,b in zip(actual,views[name])):raise RuntimeError('Native view alignment rejected placement; inspect copy')
        if not _save_as(md,str(out))[0]:raise RuntimeError('Book save failed')
        review=review_drawing_book(str(out),reserved_regions=reserved_regions)
        result=dict(ok=review['passed'] and file_sha256(source)==before,drawing=str(out),source_unchanged=file_sha256(source)==before,review=review)
        if result['ok']:stamp_drawing_book(str(out))
        lease.failed=not result['ok'];return result
