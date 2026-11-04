"""v1.4.1 实机验收：双同径孔、阶梯销、旋转、持久面引用和失败回退。

python examples/verify_face_mates.py --work-dir <新的证据目录> [--keep]
只清理本轮创建的文档；不修改原有文档，不覆盖既有试件。
"""
from __future__ import annotations
import argparse
import base64
import copy
import json
import math
from pathlib import Path
import traceback
import subprocess
import tempfile


def _rotate_fixture(assembly_path, component, transform):
    """仅供试件布置；IMathUtility.CreateTransform 在本机后期绑定下不可直接调用。"""
    from swforge.modeling import _find_sw_dir
    from swforge.mates import _PS, _cs_str
    directory=Path(_find_sw_dir())
    source=r'''
using System;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
public class RotateFixture141 {
 public static string Run(){
  ISldWorks sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));
  IModelDoc2 md=(IModelDoc2)sw.ActiveDoc;
  if(md==null||!String.Equals(md.GetPathName(),__PATH__,StringComparison.OrdinalIgnoreCase))throw new Exception("试件装配路径不符");
  IComponent2 c=((IAssemblyDoc)md).GetComponentByName(__COMP__);
  IMathUtility math=(IMathUtility)sw.GetMathUtility();
  c.Transform2=(MathTransform)math.CreateTransform(new double[]{__TRANSFORM__});
  md.EditRebuild3();
  return new JavaScriptSerializer().Serialize((double[])c.Transform2.ArrayData);
 }
}
'''.replace('__PATH__',_cs_str(str(assembly_path))).replace('__COMP__',_cs_str(component)).replace('__TRANSFORM__',','.join(str(float(v)) for v in transform))
    with tempfile.TemporaryDirectory(prefix='swforge_fixture_rotation_') as work:
        path=Path(work)/'rotate.cs';path.write_text(source,encoding='utf8')
        ps=_PS.format(dll=str(directory/'SolidWorks.Interop.sldworks.dll').replace("'","''"),
                      cst=str(directory/'SolidWorks.Interop.swconst.dll').replace("'","''"),
                      cs=str(path).replace("'","''"),cls='RotateFixture141')
        ps=ps.replace("-ErrorAction Stop","-ErrorAction Stop").replace("-ReferencedAssemblies ","-ReferencedAssemblies 'System.Web.Extensions',")
        script=Path(work)/'run.ps1';script.write_text(ps,encoding='utf-8-sig')
        proc=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=90)
        if proc.returncode:raise RuntimeError(proc.stderr)
        return json.loads(proc.stdout)


def verify(work_dir, keep=False):
    from swforge import (PartBuilder, AssemblyBuilder, MateBuilder, list_mate_faces,
                         apply_face_mates, inspect_face_mates, check_interference,
                         get_session, document_inventory)
    from swforge.session import _value
    from swforge.drawing import _save_as
    from swforge.mates import _activate_assembly
    from win32com.client import VARIANT
    import pythoncom

    root=Path(work_dir).resolve();root.mkdir(parents=True,exist_ok=True)
    bracket=root/'m141_双孔支架.SLDPRT';pin=root/'m141_阶梯定位销.SLDPRT';assembly=root/'m141_显式选面演示.SLDASM'
    sw=get_session().sw();report=dict(ok=False,before=document_inventory(sw),checks=[])
    owned=[]
    if any(p.exists() for p in (bracket,pin,assembly)):
        raise ValueError('请指定新目录，避免覆盖已有试件')
    names={p.name.casefold() for p in (bracket,pin,assembly)}
    if any(Path(d['path']).name.casefold() in names for d in report['before']['documents'] if d['path']):
        raise ValueError('同名演示文档已打开，请先保存并关闭，避免跨路径激活混淆')

    def check(name,condition,detail):
        report['checks'].append(dict(name=name,ok=bool(condition),detail=detail))
        print(f"{'PASS' if condition else 'FAIL'} {name}",flush=True)
        if not condition:raise AssertionError(f'{name}: {detail}')

    def unique(items,label):
        items=list(items)
        if len(items)!=1:raise ValueError(f'{label} 匹配 {len(items)} 项，拒绝猜选')
        return items[0]

    def pin_transform(component):
        return list(_value(_value(sw.ActiveDoc.GetComponentByName(component),'Transform2'),'ArrayData'))

    def preview(name):
        md=sw.ActiveDoc;sw.Visible=True
        md.ShowNamedView2('',7)
        _value(md,'ViewZoomtofit2');_value(md,'GraphicsRedraw2')
        r=_save_as(md,str(root/(name+'.png')))
        report[name+'_export']=r

    try:
        owned.extend([bracket,pin,assembly])
        b=PartBuilder(str(bracket),material='Q235')
        b.revolve('干扰孔环',[(8,0),(14,0),(14,20),(8,20)],axis='y',x=20,z=50,color='steel')
        b.revolve('目标孔环',[(8,0),(20,0),(20,20),(8,20)],axis='y',x=80,z=50,color='steel')
        b.box('连接腹板',20,80,0,20,60,66,color='steel')
        rb=b.build(paint=True,keep_open=False)
        check('支架几何材质回读',rb.ok and rb.volume_mm3>0 and rb.material_applied=='Q235',rb.__dict__)
        b=PartBuilder(str(pin),material='45')
        b.cylinder('定位轴段',axis='y',r=7.8,h=30,color='yellow')
        b.cylinder('轴肩',axis='y',y=30,r=12,h=5,color='yellow')
        rp=b.build(paint=True,keep_open=False)
        check('阶梯销几何材质回读',rp.ok and rp.volume_mm3>0,rp.__dict__)
        made=AssemblyBuilder(str(assembly)).add(str(bracket),fixed=True).add(str(pin),x=200,y=40,z=50).build()
        check('装配与固定基件',made['ok'],made)
        faces=list_mate_faces(str(assembly));check('装配面枚举',faces['ok'],faces)
        rows=faces['faces'];report['faces']=faces
        holes=[f for f in rows if f['kind']=='cylinder' and abs(f['radius_mm']-8)<1e-6]
        check('两个真实同径孔候选',len(holes)==2,[{k:f[k] for k in ('component','radius_mm','origin_local_mm')} for f in holes])
        hole=unique((f for f in holes if abs(f['origin_local_mm'][0]-80)<1e-6),'目标孔')
        decoy=unique((f for f in holes if abs(f['origin_local_mm'][0]-20)<1e-6),'干扰孔')
        shaft=unique((f for f in rows if f['kind']=='cylinder' and abs(f['radius_mm']-7.8)<1e-6),'销轴面')
        top=unique((f for f in rows if f['component']==hole['component'] and f['kind']=='plane'
                    and abs(f['origin_local_mm'][1]-20)<1e-6 and f['direction_local'][1]>.99 and f['origin_local_mm'][0]>80),'目标孔环顶面')
        shoulder=unique((f for f in rows if f['component']==shaft['component'] and f['kind']=='plane'
                         and abs(f['origin_local_mm'][1]-30)<1e-6 and f['direction_local'][1]<-.99),'轴肩底面')
        specs=[dict(type='concentric',face_a=hole,face_b=shaft),
               dict(type='coincident',face_a=top,face_b=shoulder,alignment='anti_aligned')]
        (root/'mate_spec.json').write_text(json.dumps(dict(mates=specs),ensure_ascii=False,indent=2),encoding='utf8')
        before_transform=pin_transform(shaft['component'])
        bad=copy.deepcopy(specs[0]);bad['face_a']['face_ref']=base64.b64encode(b'invalid-native-reference').decode()
        invalid=apply_face_mates(str(assembly),[bad])
        check('无效持久引用拒绝且不修改',not invalid['ok'] and not invalid['modified'] and pin_transform(shaft['component'])==before_transform,invalid)
        wrong=copy.deepcopy(specs[0]);wrong['face_a']['component']=shaft['component'];wrong['face_a']['part_path']=shaft['part_path']
        wrong_result=apply_face_mates(str(assembly),[wrong])
        check('错误组件引用拒绝',not wrong_result['ok'] and not wrong_result.get('modified',False),wrong_result)
        late_bad=apply_face_mates(str(assembly),[specs[0],bad])
        check('全批预检避免部分修改',not late_bad['ok'] and not late_bad['modified'],late_bad)
        rollback=apply_face_mates(str(assembly),[specs[0],specs[0]])
        after_transform=pin_transform(shaft['component'])
        check('中途失败撤销新配合并恢复变换',not rollback['ok'] and rollback.get('rollback_ok') is True
              and rollback['mate_count_after']==0 and all(abs(a-b)<1e-8 for a,b in zip(before_transform,after_transform)),rollback)
        # 先把销旋转90°，检验组件局部轴与装配轴不能混用。
        transform=[0.,1.,0.,-1.,0.,0.,0.,0.,1.,.2,.04,.05,1.,0.,0.,0.]
        actual=_rotate_fixture(assembly,shaft['component'],transform)
        check('试件旋转变换写入并回读',all(abs(a-b)<1e-8 for a,b in zip(actual,transform)),actual)
        rotated=list_mate_faces(str(assembly),component=shaft['component'],kind='cylinder')
        rotated_shaft=unique((f for f in rotated.get('faces',[]) if abs(f['radius_mm']-7.8)<1e-6),'旋转销轴')
        check('旋转组件装配轴回读',abs(rotated_shaft['direction_assembly'][0])>.99 and abs(rotated_shaft['direction_local'][1])>.99,rotated_shaft)
        preview('配合前')
        result=MateBuilder(str(assembly)).concentric_faces(hole,shaft).coincident_faces(top,shoulder,alignment='anti_aligned').apply()
        report['apply']=result
        check('旋转销显式同心及重合',result['ok'] and result['built']==2 and result['mate_count_after']==2,result)
        check('原生配合实体身份一致',all(m['entity_identity_match'] for m in result['mates']),result['mates'])
        check('轴距和平面间距回读',all(m['geometry']['gap_mm']<=.001 and m['geometry']['parallel_error_deg']<=.001 for m in result['mates']),result['mates'])
        check('孔轴半径不同仍正确同心',abs(hole['radius_mm']-shaft['radius_mm']-.2)<1e-6,dict(hole_radius=hole['radius_mm'],shaft_radius=shaft['radius_mm']))
        updated=list_mate_faces(str(assembly),kind='cylinder');check('配合后圆柱几何可回读',updated['ok'],updated)
        target=unique((f for f in updated['faces'] if f['component']==hole['component'] and abs(f['radius_mm']-8)<1e-6 and abs(f['origin_local_mm'][0]-80)<1e-6),'已配合目标')
        distractor=unique((f for f in updated['faces'] if f['component']==hole['component'] and abs(f['radius_mm']-8)<1e-6 and abs(f['origin_local_mm'][0]-20)<1e-6),'已配合干扰孔')
        current_shaft=unique((f for f in updated['faces'] if f['component']==shaft['component'] and abs(f['radius_mm']-7.8)<1e-6),'已配合销轴')
        def axis_distance(a,b):
            d=[x-y for x,y in zip(a['origin_assembly_mm'],b['origin_assembly_mm'])];u=a['direction_assembly']
            cross=[d[1]*u[2]-d[2]*u[1],d[2]*u[0]-d[0]*u[2],d[0]*u[1]-d[1]*u[0]]
            return math.sqrt(sum(v*v for v in cross))
        correct=axis_distance(target,current_shaft);wrong_gap=axis_distance(distractor,current_shaft)
        check('指定80孔而非20孔',correct<=.001 and abs(wrong_gap-60)<.001,dict(target_axis_gap_mm=correct,decoy_axis_gap_mm=wrong_gap))
        interference=check_interference(str(assembly))
        check('无错误落位造成的干涉',interference['ok'] and interference.get('interference_count')==0,interference)
        saved=_save_as(sw.ActiveDoc,str(assembly));check('保存原生装配',saved[0] and saved[1]==0,saved)
        for path in (assembly,pin,bracket):sw.CloseDoc(str(path))
        reopened=inspect_face_mates(str(assembly),json.loads((root/'mate_spec.json').read_text(encoding='utf8'))['mates'])
        check('保存重开持久面引用和配合仍正确',reopened['ok'] and reopened['mate_count_after']==2,reopened)
        repeated=apply_face_mates(str(assembly),[specs[0]])
        check('重复配合拒绝且不新增',not repeated['ok'] and not repeated['modified'] and repeated['mate_count_before']==2,repeated)
        config_bad=copy.deepcopy(specs[0]);config_bad['face_a']['component_configuration']='不存在的配置'
        config_result=apply_face_mates(str(assembly),[config_bad])
        check('零件配置变化拒绝旧引用',not config_result['ok'] and not config_result['modified'],config_result)
        final=inspect_face_mates(str(assembly),specs)
        check('失败请求未破坏既有配合',final['ok'] and final['mate_count_after']==2,final)
        preview('配合后')
        report['final_inspection']=final;report['ok']=True
    except Exception:
        report['exception']=traceback.format_exc();raise
    finally:
        if not keep or not report['ok']:
            for path in reversed(owned):sw.CloseDoc(str(path))
        else:
            _activate_assembly(str(assembly));_value(sw.ActiveDoc,'ViewZoomtofit2')
        report['after']=document_inventory(sw)
        (root/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir',required=True);parser.add_argument('--keep',action='store_true')
    args=parser.parse_args();verify(args.work_dir,args.keep)
