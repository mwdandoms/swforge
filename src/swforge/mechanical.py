"""Verified native SHS frames and unshifted involute spur gears; units mm."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import time

from .modeling import _number


def frame_plan(length=600, width=400, height=500, section=40, wall=3):
    """12 straight square-tube members with explicitly square, butt-ended joints."""
    vals={k:_number(v,k,True) for k,v in locals().copy().items()}
    l,w,h,s,t=vals.values()
    if t>=s/2 or min(l,w,h)<=2*s:
        raise ValueError('wall < section/2 and each overall dimension > 2*section required')
    lines=[]
    for y in (s/2,w-s/2):
        for z in (s/2,h-s/2): lines.append([[0,y,z],[l,y,z]])
    for x in (s/2,l-s/2):
        for z in (s/2,h-s/2): lines.append([[x,s,z],[x,w-s,z]])
    for x in (s/2,l-s/2):
        for y in (s/2,w-s/2): lines.append([[x,y,s],[x,y,h-s]])
    lengths=[math.dist(*p) for p in lines]
    area=s*s-(s-2*t)**2
    return dict(kind='shs_frame',parameters=vals,lines_mm=lines,lengths_mm=lengths,
                member_count=len(lines),
                section_area_mm2=area,expected_volume_mm3=sum(lengths)*area,
                joint='square butt, no weld gap; sharp idealized SHS section')


def spur_gear_plan(module=2, teeth=24, pressure_angle=20, face_width=20,
                   bore=12, hub_diameter=0, hub_length=0, chord_error=0.005):
    """Zero profile shift, ha*=1, hf*=1.25. Radial root transition, not a hob trochoid."""
    if isinstance(teeth,bool) or not isinstance(teeth,int) or not 18<=teeth<=120:
        raise ValueError('teeth must be an integer in 18..120')
    m=_number(module,'module',True);pa=_number(pressure_angle,'pressure_angle',True)
    b=_number(face_width,'face_width',True);hole=_number(bore,'bore',True)
    hd=_number(hub_diameter,'hub_diameter');hl=_number(hub_length,'hub_length')
    tol=_number(chord_error,'chord_error',True)
    if not 0.5<=m<=10 or not 20<=pa<=25 or not 0.001<=tol<=0.02:
        raise ValueError('module 0.5..10, pressure angle 20..25 degrees, chord_error .001...02 mm')
    if teeth<math.ceil(2/math.sin(math.radians(pa))**2):
        raise ValueError('Undercut-prone parameter combination is not supported')
    r=m*teeth/2;rb=r*math.cos(math.radians(pa));ra=r+m;rf=r-1.25*m
    if hole>=2*rf-2*m or min(hd,hl)<0 or bool(hd)!=bool(hl) or (hd and not hole+2*m<hd<=2*rf):
        raise ValueError('Bore/hub leaves insufficient rim or inconsistent hub parameters')
    inv_pitch=math.tan(math.radians(pa))-math.radians(pa)
    def half(rad):
        a=math.acos(min(1,rb/rad)) if rad>rb else 0
        return math.pi/(2*teeth)+inv_pitch-(math.tan(a)-a)
    if half(ra)<=0: raise ValueError('Tooth tip has nonpositive thickness')
    start=max(rb,rf)
    def point(rad,sign=1): return [rad*math.cos(half(rad)),sign*rad*math.sin(half(rad))]
    def distance(p,a,c):
        dx=c[0]-a[0];dy=c[1]-a[1]
        return abs(dx*(a[1]-p[1])-(a[0]-p[0])*dy)/math.hypot(dx,dy)
    # Adaptive radial subdivision, including exact pitch circle for independent tooth-thickness check.
    intervals=[]
    def split(a,c,depth=0):
        errors=[distance(point(a+(c-a)*f),point(a),point(c)) for f in (.25,.5,.75)]
        if max(errors)>tol/4 and depth<20:
            mid=(a+c)/2;split(a,mid,depth+1);split(mid,c,depth+1)
        else: intervals.append((a,c,max(errors)))
    split(start,r);split(r,ra)
    radii=[intervals[0][0]]+[item[1] for item in intervals]
    lower=[point(rad,-1) for rad in radii]
    top_angle=half(ra)
    n=max(2,math.ceil(2*top_angle/(2*math.acos(1-tol/(4*ra)))))
    tip=[[ra*math.cos(-top_angle+2*top_angle*i/n),ra*math.sin(-top_angle+2*top_angle*i/n)] for i in range(1,n)]
    inner=rf-min(.1*m,.05)
    a0=half(start)
    polygon=[[inner*math.cos(a0),-inner*math.sin(a0)]]+lower+tip+[point(rad) for rad in reversed(radii)]+[[inner*math.cos(a0),inner*math.sin(a0)]]
    # Independent radial area quadrature (does not reuse polygon shoelace volume).
    n_int=20000;step=(ra-rf)/n_int
    integral=sum((2*half(rf+i*step)*(rf+i*step))*(.5 if i in (0,n_int) else 1) for i in range(n_int+1))*step
    expected=(math.pi*(rf*rf-hole*hole/4)+teeth*integral)*b
    if hd: expected+=math.pi*(hd*hd-hole*hole)*hl/4
    params=dict(module=m,teeth=teeth,pressure_angle=pa,face_width=b,bore=hole,hub_diameter=hd,hub_length=hl,chord_error=tol)
    return dict(kind='spur_gear',parameters=params,pitch_diameter_mm=2*r,base_diameter_mm=2*rb,
                outside_diameter_mm=2*ra,root_diameter_mm=2*rf,pitch_thickness_mm=math.pi*m/2,
                circular_pitch_mm=math.pi*m,seed_polygon_mm=polygon,
                sampled_flank_error_mm=max(i[2] for i in intervals),expected_volume_mm3=expected,
                root_form='radial transition; not generated trochoid',profile_shift=0)


def _output(path,suffix):
    p=Path(path).resolve()
    if p.suffix.lower()!=suffix or p.exists(): raise ValueError('New '+suffix+' path required: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True)
    return str(p)


def _metadata(path):
    from .variants import file_sha256
    data=json.loads(Path(path+'.swforge.json').read_text(encoding='utf8'))
    if data.get('schema')!='swforge-mechanical-1' or data.get('kind') not in ('shs_frame','spur_gear'):
        raise ValueError('Unsupported mechanical metadata schema/kind')
    if data.get('model_sha256')!=file_sha256(path): raise ValueError('Source changed; mechanical metadata is stale')
    return data


def verify_mechanical_readback(plan,result):
    """Compare native bodies/pattern/vertices with independent family geometry."""
    if not result.get('ok'): return {'ok':False,'error':'Native operation failed'}
    try:
        if plan['kind']=='shs_frame':
            nominal=plan['section_area_mm2']
            # 用实测总体积反推真实截面积。素材库轮廓是真实冷弯/热轧截面，带内圆角，
            # 截面积比名义尖角环小约 1%，直接用名义值会把每根长度都算错。
            total_volume=sum(body['volume_mm3'] for body in result['bodies'])
            total_length=sum(plan['lengths_mm'])
            actual=total_volume/total_length if total_length else nominal
            lengths=sorted(body['volume_mm3']/actual for body in result['bodies'])
            wanted=sorted(plan['lengths_mm'])
            # 相对容差 0.1%：既容得下体素/精度噪声，又抓得住长度真的错了
            expect=plan.get('member_count',12)
            if len(lengths)!=expect or any(abs(a-b)>max(1e-3,abs(b)*1e-3)
                                       for a,b in zip(lengths,wanted)):
                raise ValueError('Native individual stock lengths/volumes differ')
            rows=[]
            for item in result['cut_list']:
                props=item['properties'];length=props.get('LENGTH',props.get('Length',props.get('长度')))
                if length is None: raise ValueError('Native cut-list length property missing')
                rows.extend([float(length)]*item['quantity'])
            if sorted(rows)!=sorted(plan['lengths_mm']): raise ValueError('Native cut-list lengths or quantities differ')
            return {'ok':True,'native_member_lengths_mm':lengths,'cut_list_quantity':len(rows),'section_area_nominal_mm2':nominal,'section_area_actual_mm2':actual,'section_area_ratio':actual/nominal if nominal else None}
        p=plan['parameters'];z=p['teeth'];r=plan['pitch_diameter_mm']/2;ra=plan['outside_diameter_mm']/2
        if result['body_count']!=1: raise ValueError('Gear must be one connected solid')
        patterns=[f for f in result['features'] if f['type']=='CirPattern']
        if len(patterns)!=1 or patterns[0]['instances']!=z: raise ValueError('Native tooth instance count differs')
        points={(round(v[0],7),round(v[1],7)) for v in result['vertices_mm'] if abs(v[2])<1e-5}
        if abs(max(math.hypot(*v) for v in points)-ra)>1e-5: raise ValueError('Native tooth-tip radius differs')
        pitch=sorted(math.atan2(y,x)%(2*math.pi) for x,y in points if abs(math.hypot(x,y)-r)<1e-5)
        if len(pitch)!=2*z: raise ValueError('Native pitch-circle flank count differs')
        phase_errors=[min(abs(((a-2*math.pi*k/z-sign*math.pi/(2*z)+math.pi)%(2*math.pi))-math.pi) for k in range(z) for sign in (-1,1)) for a in pitch]
        if max(phase_errors)*r>1e-5: raise ValueError('Pitch thickness or symmetry differs')
        cylinders=result['cylinders']
        if not any(abs(c['radius_mm']-p['bore']/2)<1e-6 and math.hypot(*c['center_mm'][:2])<1e-6 and abs(abs(c['axis'][2])-1)<1e-6 for c in cylinders):
            raise ValueError('Bore radius/axis differs')
        return {'ok':True,'native_teeth':z,'native_pitch_flank_vertices':len(pitch),
                'max_pitch_phase_error_mm':max(phase_errors)*r,'native_outside_diameter_mm':2*ra,
                'relative_volume_error':abs(result['volume_mm3']/plan['expected_volume_mm3']-1),
                'sampled_flank_chord_error_mm':plan['sampled_flank_error_mm']}
    except (KeyError,ValueError,TypeError) as exc:
        return {'ok':False,'error':str(exc)}


def _build(plan,out_path,material,keep_open,drawing_path,profile_path=None):
    from .session import get_session,_value
    from .resources import ensure_capacity,document_inventory
    from .gb_materials import lookup,ensure_library,GB_MATERIALS
    from .drawing import _template_dirs
    from .native_bridge import run_native
    from .mechanical_native import engine
    start=time.monotonic();out=_output(out_path,'.sldprt')
    drw=_output(drawing_path,'.slddrw') if drawing_path else None
    props=lookup(material)
    if props is None: raise ValueError('Explicit supported GB material required')
    material=next(k for k,v in GB_MATERIALS.items() if k.lower()==str(material).lower())
    sw=get_session().sw();before=document_inventory(sw)
    capacity=ensure_capacity(2)
    if not capacity['allowed']: return capacity
    stem=Path(out).with_suffix('')
    # 素材库优先：给了现成轮廓就不用现场生成
    if profile_path:
        profile=str(profile_path);profile_source='library'
        if not Path(profile).is_file():
            raise ValueError('Library profile not found: '+profile)
    else:
        profile=str(stem)+'.sldlfp';profile_source='generated'
    metadata=out+'.swforge.json'
    clash=[metadata] if profile_source=='library' else [metadata,profile]
    if any(Path(p).exists() for p in clash):
        raise ValueError('Related output already exists; use a fresh stem')
    if any(str(row['title']).rsplit('.',1)[0].lower()==Path(out).stem.lower() for row in before['documents']):
        raise ValueError('A document with this basename is already open')
    template=next((str(p) for d in _template_dirs() for p in Path(d).glob('*.prtdot')),'')
    if not template: raise ValueError('No part template found')
    command=dict(mode='build',plan=plan,out=out,profile=profile,
                 profile_source=profile_source,material=material,
                 material_db=ensure_library(),density=props[0],template=template,
                 process_id=int(_value(sw,'GetProcessID')),keep_open=keep_open,max_documents=8)
    result=run_native(command,timeout_s=300,engine=engine())
    if result.get('ok'):
        result['geometry_verification']=verify_mechanical_readback(plan,result)
        if not result['geometry_verification']['ok']:
            result.update(ok=False,error=result['geometry_verification']['error'],partial_outputs=[out])
    if result.get('ok'):
        from .variants import file_sha256
        spec=dict(schema='swforge-mechanical-1',kind=plan['kind'],parameters=plan['parameters'],material=material,model_sha256=file_sha256(out))
        Path(metadata).write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf8')
        result['metadata']=metadata
        if drw:
            draw=mechanical_drawing(out,drw,keep_open=keep_open,_owned_model=True)
            result['drawing']=draw
            if not draw.get('ok'): result.update(ok=False,partial_outputs=[out,metadata],error='Model accepted, drawing failed')
    result.update(elapsed_s=round(time.monotonic()-start,3),before=before,after=document_inventory(sw),review_required=True,ready_for_manufacture=False)
    Path(out+'.operations.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def create_weldment_frame(out_path,*,length=600,width=400,height=500,section=40,wall=3,material='Q235',drawing_path=None,keep_open=False,use_library=True,profile_path=None):
    """建一个方管框架。

    use_library  默认 True：先去 GB 型材素材库找同名规格的现成轮廓。
                 找到了就用库里的原生型材截面（有圆角、真实壁厚），
                 找不到才回退到现场生成矩形环。
    profile_path 直接指定某个 .SLDLFP，跳过查库。
    """
    resolved=dict(ok=False,source='generated',path=None,advice='')
    if profile_path:
        resolved=dict(ok=True,source='explicit',path=str(profile_path),advice='调用方指定')
    elif use_library:
        try:
            from .library import MaterialLibrary
            hit=MaterialLibrary().resolve_section(shape='shs',a=section,b=section,t=wall)
            resolved=dict(ok=bool(hit.get('ok')),
                          source='library' if hit.get('ok') else 'generated',
                          path=hit.get('path'),advice=hit.get('advice',''),
                          candidates=hit.get('candidates',[])[:3],
                          profile=hit.get('profile'))
        except Exception as exc:
            resolved=dict(ok=False,source='generated',path=None,
                          advice=f'素材库查询失败，回退现场建模：{type(exc).__name__}: {exc}')
    return _build_with_library_fallback(frame_plan(length,width,height,section,wall),
                                        out_path,material,keep_open,drawing_path,resolved)




def _build_with_library_fallback(plan,out_path,material,keep_open,drawing_path,resolved):
    """先按素材库轮廓建；失败就自动回退现场建模，并如实记录。

    resolved 是 library 查询结果。返回的 result 里 profile_resolution.source 可能是：
      library            素材库轮廓建成了
      generated          本来就没查到，现场建
      generated_fallback 查到了但该轮廓不能当结构构件，回退现场建
      explicit           调用方直接指定了轮廓
    """
    import os as _os
    attempt=_build(plan,out_path,material,keep_open,drawing_path,
                   profile_path=resolved.get('path') if resolved.get('ok') else None)
    if attempt.get('ok') or not resolved.get('ok'):
        attempt['profile_resolution']=resolved
        return attempt
    # ---- 素材库轮廓没建成：清理半成品，回退现场建模
    first_error=str(attempt.get('error') or '')[:300]
    for suffix in ('','.swforge.json','.operations.json','.sldlfp'):
        f=out_path+suffix
        try:
            if _os.path.isfile(f): _os.remove(f)
        except OSError:
            pass
    retry=_build(plan,out_path,material,keep_open,drawing_path,profile_path=None)
    retry['profile_resolution']=dict(
        ok=False,source='generated_fallback',path=resolved.get('path'),
        advice=(f"素材库有同型号（{resolved.get('path')}）但该轮廓不能直接当结构构件用，"
                "已回退现场建模；要严格按型材截面请换一个轮廓或手工确认"),
        library_error=first_error,
        attempted_profile=resolved.get('profile'))
    if retry.get('ok'):
        retry['warning']='素材库轮廓不可用，已回退现场建模'
    return retry


def member_plan(length=1000, section=50, wall=2, axis='x'):
    """一根直型材的 plan。section/wall 只用于回退建模和名义截面积。"""
    vals={k:_number(v,k,True) for k,v in locals().copy().items() if k!='axis'}
    l,s,t=vals['length'],vals['section'],vals['wall']
    if t>=s/2: raise ValueError('wall must be < section/2')
    half=s/2
    if axis=='x':   lines=[[[0,half,half],[l,half,half]]]
    elif axis=='y': lines=[[[half,0,half],[half,l,half]]]
    elif axis=='z': lines=[[[half,half,0],[half,half,l]]]
    else: raise ValueError("axis must be x, y or z")
    lengths=[math.dist(*p) for p in lines]
    area=s*s-(s-2*t)**2
    return dict(kind='shs_frame',parameters=vals,lines_mm=lines,lengths_mm=lengths,
                member_count=len(lines),
                section_area_mm2=area,expected_volume_mm3=sum(lengths)*area,
                joint='single straight member; sharp idealized SHS section')


def create_standard_member(out_path,*,shape='shs',a=None,b=None,t=None,d=None,length=1000,
                           axis='x',material='Q235',drawing_path=None,keep_open=False,
                           use_library=True,profile_path=None):
    """建一根标准型材 —— **默认先查素材库**。

    这是「用户要一根方管/圆管/角钢」时的正规入口。它会：
      1. 去 GB 型材素材库找同型号的现成轮廓（1306 个）
      2. 找到就用库里的原生型材截面建结构构件（有内圆角、真壁厚）
      3. 找不到才回退到现场建模，并在 advice 里提示最接近的候选

    参数
    ----
    shape   shs方管 / rhs矩型管 / chs圆管 / angle-eq等边角钢 / hbeam H型钢 ...
    a,b,t   边长与壁厚（mm）；圆管用 d
    length  长度（mm）
    axis    x / y / z

    返回里的 ``profile_resolution.source`` 说明走的是 ``library`` 还是 ``generated``。
    """
    resolved=dict(ok=False,source='generated',path=None,advice='')
    if profile_path:
        resolved=dict(ok=True,source='explicit',path=str(profile_path),advice='调用方指定')
    elif use_library:
        try:
            from .library import MaterialLibrary
            hit=MaterialLibrary().resolve_section(shape=shape,a=a,b=b,t=t,d=d)
            resolved=dict(ok=bool(hit.get('ok')),
                          source='library' if hit.get('ok') else 'generated',
                          path=hit.get('path'),advice=hit.get('advice',''),
                          candidates=hit.get('candidates',[])[:3],
                          profile=hit.get('profile'))
        except Exception as exc:
            resolved=dict(ok=False,source='generated',path=None,
                          advice=f'素材库查询失败，回退现场建模：{type(exc).__name__}: {exc}')
    # 名义截面：圆管按外径算，其余按方管近似（只影响回退建模与名义面积）
    if shape in ('chs','圆管') or (d and not a):
        sec=float(d or a or 50); wall=float(t or 2)
    else:
        sec=float(a or b or 50); wall=float(t or 2)
    plan=member_plan(length=length,section=sec,wall=wall,axis=axis)
    return _build_with_library_fallback(plan,out_path,material,keep_open,
                                        drawing_path,resolved)


def create_spur_gear(out_path,*,module=2,teeth=24,pressure_angle=20,face_width=20,bore=12,hub_diameter=0,hub_length=0,chord_error=.005,material='45',drawing_path=None,keep_open=False):
    return _build(spur_gear_plan(module,teeth,pressure_angle,face_width,bore,hub_diameter,hub_length,chord_error),out_path,material,keep_open,drawing_path)


def inspect_mechanical(part_path):
    from .native_bridge import run_native,target_document
    from .mechanical_native import engine
    _,_,guard=target_document(part_path,1)
    return run_native(dict(guard,mode='inspect'),engine=engine())


def create_mechanical_variant(source_path,out_path,*,parameters=None,drawing_path=None,keep_open=False):
    """Regenerate a parameter-family copy; never edits the source or retargets old drawings."""
    from .variants import file_sha256
    from .native_bridge import target_document
    from .session import _value,get_session
    from .resources import document_inventory
    source=str(Path(source_path).resolve());before=file_sha256(source)
    data=_metadata(source)
    if data['model_sha256']!=before: raise ValueError('Source changed; mechanical metadata is stale')
    initial=document_inventory(get_session().sw())
    was_open=any(os.path.normcase(r['path'])==os.path.normcase(source) for r in initial['documents'])
    sw,doc,_=target_document(source,1)
    if bool(_value(doc,'GetSaveFlag')): raise ValueError('Source has unsaved changes')
    args=dict(data['parameters']);changes=parameters or {}
    if set(changes)-set(args): raise ValueError('Unknown parameter names')
    args.update(changes)
    build=create_weldment_frame if data['kind']=='shs_frame' else create_spur_gear
    try:
        result=build(out_path,**args,material=data['material'],drawing_path=drawing_path,keep_open=keep_open)
        result.update(source=source,source_unchanged=file_sha256(source)==before,variant_mode='regenerated native feature family')
        if not result['source_unchanged']: result.update(ok=False,error='Source fingerprint changed')
        return result
    finally:
        if not was_open and not _value(doc,'GetSaveFlag'): sw.CloseDoc(source)


def mechanical_drawing(part_path,out_path,*,keep_open=False,_owned_model=False):
    from .native_bridge import run_native,target_document
    from .mechanical_native import engine
    from .variants import file_sha256
    from .drawing import produce,add_dimensions,_save_as
    from .drawing_review import record_drawing_revision,audit_drawing
    from .resources import document_scope,document_inventory
    path=str(Path(part_path).resolve());out=_output(out_path,'.slddrw')
    meta=_metadata(path)
    if meta['model_sha256']!=file_sha256(path): raise ValueError('Model and parameter metadata differ')
    from .session import get_session,_value
    sw=get_session().sw()
    initial=document_inventory(sw)
    already_open=any(os.path.normcase(row['path'])==os.path.normcase(path) for row in initial['documents'])
    if already_open:
        model=sw.GetOpenDocumentByName(path)
        if _value(model,'GetSaveFlag'): raise ValueError('Model has unsaved changes')
    with document_scope(out,keep_open=keep_open,related_paths=[path]) as lease:
        result=produce(path,out,keep_open=True)
        if not result.get('ok'): lease.failed=True;return result
        # Layout and overall dimensions reuse the controlled v1.5 pipeline.
        dimensions=add_dimensions(out,internal=0)
        _,doc,guard=target_document(out,3)
        diameter_results=[]
        section_result=None
        if meta['kind']=='spur_gear':
            from .circle_dimensions import list_drawing_circles,add_diameter_dimension
            from .drawing import _view_list
            view,name=_view_list(doc)[0]
            circles=list_drawing_circles(out,name)
            for diameter in [meta['parameters']['bore']]+([meta['parameters']['hub_diameter']] if meta['parameters']['hub_diameter'] else []):
                matches=[c for c in circles.get('circles',[]) if abs(c['diameter_mm']-diameter)<1e-6 and math.hypot(*c['center_model_mm'][:2])<1e-6]
                if not matches:
                    diameter_results.append({'ok':False,'error':'Expected bore/hub circle is not visible','diameter_mm':diameter})
                    continue
                circle=matches[0];cx,cy,*_=circle['center_sheet_m']
                diameter_results.append(add_diameter_dimension(out,circle,cx+.018,cy-.018-.012*len(diameter_results)))
            if meta['parameters']['hub_diameter']:
                from .views_extra import add_section_view
                section_result=add_section_view(out,view_name=name,label='A',offset=.12,offset_y=-.10)
        native=run_native(dict(guard,mode='drawing',metadata=meta,
                              section_name=section_result.get('name','') if section_result else ''),engine=engine())
        if section_result and section_result.get('ok') and native.get('ok'):
            from .section_check import verify_section_bore
            params=meta['parameters']
            section_result['geometry']=verify_section_bore(out,section_result['name'],bore_mm=params['bore'],
                total_width_mm=params['face_width']+params['hub_length'])
            section_result['ok']=section_result['geometry']['ok']
        result.update(dimensions=dimensions,diameters=diameter_results,section=section_result,native=native,ok=dimensions.get('ok',False) and native.get('ok',False) and all(d['ok'] for d in diameter_results) and (section_result is None or section_result['ok']))
        if result['ok']:
            # Native cut-list table creation can dirty cached properties in the referenced model.
            # Persist only a model opened by this workflow; never silently save a user-open model.
            model=sw.GetOpenDocumentByName(path)
            if model is not None and _value(model,'GetSaveFlag') and (not already_open or _owned_model):
                _,model,_=target_document(path,1)
                if not _save_as(model,path)[0]: raise RuntimeError('Referenced cut-list cache save failed')
                meta['model_sha256']=file_sha256(path)
                Path(path+'.swforge.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
                _,doc,_=target_document(out,3)
            saved,err,warn=_save_as(doc,out)
            result['ok']=bool(saved) and err==0
            result['revision']=record_drawing_revision(out)
            result['ok']=result['ok'] and result['revision'].get('ok',False)
            result['audit']=audit_drawing(out)
            result['ok']=result['ok'] and result['audit'].get('passed',False)
            if any(f['code']=='view_overlap' for f in result['audit'].get('findings',[])):
                result.update(ok=False,error='Controlled mechanical drawing contains overlapping views')
        lease.failed=not result['ok']
        return result
