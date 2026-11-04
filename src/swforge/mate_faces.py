"""显式配合选面：持久引用、装配坐标与原生配合实体三重回读。"""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from .session import get_session, _value

__all__ = ['list_mate_faces', 'apply_face_mates', 'inspect_face_mates']


def _face_reference(face):
    if not isinstance(face, dict):
        raise ValueError('面引用必须是 list_mate_faces 返回的字典，不能只给面序号')
    keys = ('assembly_path', 'assembly_configuration', 'component', 'part_path',
            'component_configuration', 'face_ref', 'kind')
    for key in keys:
        if not isinstance(face.get(key), str) or not face[key]:
            raise ValueError(f'面引用缺少 {key}')
    if face['kind'] not in ('cylinder', 'plane'):
        raise ValueError('只支持圆柱面或平面')
    try:
        raw = base64.b64decode(face['face_ref'], validate=True)
        if not raw or len(raw) > 131072:
            raise ValueError('面引用长度无效')
    except (ValueError, TypeError) as exc:
        raise ValueError('face_ref 必须是有效的 Base64 持久引用') from exc
    return {key: face[key] for key in keys}


def _operation(spec):
    if not isinstance(spec, dict) or spec.get('type') not in ('concentric', 'coincident'):
        raise ValueError('配合 type 必须为 concentric 或 coincident')
    a, b = _face_reference(spec.get('face_a')), _face_reference(spec.get('face_b'))
    kind = 'cylinder' if spec['type'] == 'concentric' else 'plane'
    if a['kind'] != kind or b['kind'] != kind:
        raise ValueError(f"{spec['type']} 要求两面均为 {kind}")
    if os.path.normcase(os.path.abspath(a['assembly_path'])) != os.path.normcase(os.path.abspath(b['assembly_path'])):
        raise ValueError('两面来自不同装配体')
    if a['assembly_configuration'] != b['assembly_configuration']:
        raise ValueError('两面来自不同装配配置')
    if a['component'] == b['component']:
        raise ValueError('配合必须指定两个不同组件实例')
    alignment = spec.get('alignment', 'closest')
    if alignment not in ('closest', 'aligned', 'anti_aligned'):
        raise ValueError('alignment 必须为 closest/aligned/anti_aligned')
    tolerance = spec.get('verify_tolerance_mm', .001)
    if isinstance(tolerance, bool) or not math.isfinite(float(tolerance)) or not 0 < float(tolerance) <= .1:
        raise ValueError('verify_tolerance_mm 必须在 (0, 0.1] 毫米内')
    return dict(type=spec['type'], face_a=a, face_b=b, alignment=alignment,
                verify_tolerance_mm=float(tolerance))


def _target(path):
    from .mates import _activate_assembly
    from .resources import ensure_capacity
    sw = get_session().sw()
    if path:
        path = os.path.abspath(os.fspath(path))
        if not os.path.isfile(path):
            raise ValueError(f'装配体不存在：{path}')
        if sw.GetOpenDocumentByName(path) is None:
            cap = ensure_capacity(1)
            if not cap['allowed']:
                raise RuntimeError(cap['error'])
        _activate_assembly(path)
    md = sw.ActiveDoc
    if md is None or int(_value(md, 'GetType')) != 2:
        raise ValueError('当前文档不是装配体')
    actual = str(_value(md, 'GetPathName') or '')
    if not actual:
        raise ValueError('请先保存装配体，持久面引用需要明确的文档路径')
    if path and os.path.normcase(actual) != os.path.normcase(path):
        raise RuntimeError('活动装配路径不符，停止操作')
    configuration = str(_value(_value(_value(md, 'ConfigurationManager'), 'ActiveConfiguration'), 'Name'))
    return dict(assembly_path=os.path.abspath(actual), assembly_configuration=configuration,
                process_id=int(_value(sw, 'GetProcessID')))


def _run(command, timeout_s=120):
    from .modeling import _find_sw_dir
    directory = _find_sw_dir()
    if not directory:
        return {'ok': False, 'error': '找不到 SolidWorks Interop DLL，请设置 SW_INSTALL_DIR'}
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='swforge_face_mate_') as work:
        root = Path(work)
        name = 'ExplicitMate_' + uuid.uuid4().hex
        source = root/'bridge.cs'
        source.write_text(_ENGINE.replace('__CLASS__', name), encoding='utf8')
        data = root/'command.json'
        data.write_text(json.dumps(command, ensure_ascii=False), encoding='utf8')
        quote = lambda value: str(value).replace("'", "''")
        dll = Path(directory)/'SolidWorks.Interop.sldworks.dll'
        const = Path(directory)/'SolidWorks.Interop.swconst.dll'
        script = root/'run.ps1'
        script.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"[System.Reflection.Assembly]::LoadFrom('{quote(dll)}') | Out-Null\n"
            f"Add-Type -TypeDefinition ([System.IO.File]::ReadAllText('{quote(source)}',[System.Text.Encoding]::UTF8)) "
            f"-ReferencedAssemblies '{quote(dll)}','{quote(const)}','System.Web.Extensions'\n"
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
            f"[{name}]::Run('{quote(data)}')\n", encoding='utf-8-sig')
        try:
            proc = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                  capture_output=True, text=True, encoding='utf8', errors='replace', timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': '显式配合桥接超时；操作状态未知，请检查装配，不能自动重试',
                    'mutation_state': 'unknown'}
        if proc.returncode:
            return {'ok': False, 'error': '显式配合桥接编译或执行失败', 'details': proc.stderr[-12000:]}
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            return {'ok': False, 'error': '显式配合桥接未返回有效 JSON', 'details': proc.stdout[-12000:]}
        result['elapsed_s'] = round(time.monotonic()-start, 3)
        return result


def list_mate_faces(assembly_path=None, component=None, kind=None) -> dict:
    """只读枚举顶层已解析零件的圆柱面/平面，单位毫米，含局部与装配坐标和持久面引用。"""
    try:
        if kind not in (None, 'cylinder', 'plane'):
            raise ValueError('kind 必须为 cylinder/plane 或 None')
        target = _target(assembly_path)
        return _run(dict(target, mode='list', component=component, kind=kind))
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'faces': []}


def apply_face_mates(assembly_path=None, mates=None, timeout_s=120) -> dict:
    """按持久面引用建立同心/重合配合，不用半径相等作为选面条件。

    全部请求先验证；运行失败停止并尝试回退本批次新配合及组件变换。
    默认只改内存，由调用方检查结果后保存。ok 包含目标实体身份和几何回读。
    """
    try:
        specs = [_operation(spec) for spec in (mates or [])]
        if not specs:
            raise ValueError('mates 不能为空')
        if len(specs) > 50:
            raise ValueError('一次最多50个显式配合')
        target = _target(assembly_path or specs[0]['face_a']['assembly_path'])
        return _run(dict(target, mode='apply', mates=specs), timeout_s)
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'built': 0, 'modified': False}


def inspect_face_mates(assembly_path=None, mates=None) -> dict:
    """只读核对持久面引用、目标几何和原生配合实体；用于保存重开后的验证。"""
    try:
        specs = [_operation(spec) for spec in (mates or [])]
        if not specs:
            raise ValueError('mates 不能为空')
        return _run(dict(_target(assembly_path or specs[0]['face_a']['assembly_path']), mode='inspect', mates=specs))
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}


_ENGINE = r'''
using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;

public class __CLASS__ {
 static ISldWorks sw; static IModelDoc2 md; static IAssemblyDoc ad; static IMathUtility math;
 static JavaScriptSerializer json=new JavaScriptSerializer(){MaxJsonLength=16777216};
 static Dictionary<string,object> cmd;
 static string S(Dictionary<string,object> d,string k){return d.ContainsKey(k)&&d[k]!=null?Convert.ToString(d[k]):"";}
 static Dictionary<string,object> D(object o){return (Dictionary<string,object>)o;}
 static double N(Dictionary<string,object>d,string k){return Convert.ToDouble(d[k]);}
 static bool SamePath(string a,string b){return String.Equals(Path.GetFullPath(a),Path.GetFullPath(b),StringComparison.OrdinalIgnoreCase);}
 static string Config(){return md.ConfigurationManager.ActiveConfiguration.Name;}
 static void EnsureTarget(){
  IModelDoc2 active=(IModelDoc2)sw.ActiveDoc;
  if(active==null||!SamePath(active.GetPathName(),S(cmd,"assembly_path"))||Config()!=S(cmd,"assembly_configuration"))throw new Exception("活动文档或配置发生变化，停止操作，不自动重试");
 }
 static double[] Unit(double[]a){double n=Math.Sqrt(Dot(a,a));if(n<1e-12)throw new Exception("方向向量无效");return new[]{a[0]/n,a[1]/n,a[2]/n};}
 static double Dot(double[]a,double[]b){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
 static double[] Sub(double[]a,double[]b){return new[]{a[0]-b[0],a[1]-b[1],a[2]-b[2]};}
 static double[] Point(double[]a,IComponent2 c){return (double[])((IMathPoint)((IMathPoint)math.CreatePoint(a)).MultiplyTransform(c.Transform2)).ArrayData;}
 static double[] Vector(double[]a,IComponent2 c){return Unit((double[])((IMathVector)((IMathVector)math.CreateVector(a)).MultiplyTransform(c.Transform2)).ArrayData);}
 static double[] MM(double[]a){return Array.ConvertAll(a,x=>x*1000);}
 class Face {public IFace2 f;public IComponent2 c;public string kind;public double radius;public double[] p,u;}
 static Face ReadFace(IFace2 f,IComponent2 c){
  ISurface surface=(ISurface)f.GetSurface();Face result=new Face(){f=f,c=c};
  if(surface.IsCylinder()){double[]v=(double[])surface.CylinderParams;result.kind="cylinder";result.radius=v[6];result.p=new[]{v[0],v[1],v[2]};result.u=Unit(new[]{v[3],v[4],v[5]});}
  else if(surface.IsPlane()){
   // PlaneParams 前三项是法向，后三项才是平面根点；IFace2.Normal 是实际面法向。
   double[]v=(double[])surface.PlaneParams;result.kind="plane";result.p=new[]{v[3],v[4],v[5]};result.u=Unit((double[])f.Normal);
  }else return null;
  return result;
 }
 static Dictionary<string,object> Row(Face f,int index){
  byte[]id=(byte[])md.Extension.GetPersistReference3(f.f);if(id==null||id.Length==0)throw new Exception("无法取得持久面引用");
  return new Dictionary<string,object>{{"assembly_path",md.GetPathName()},{"assembly_configuration",Config()},
   {"component",f.c.Name2},{"part_path",f.c.GetPathName()},{"component_configuration",f.c.ReferencedConfiguration},
   {"face_ref",Convert.ToBase64String(id)},{"face_index",index},{"kind",f.kind},{"radius_mm",f.kind=="cylinder"?(object)(f.radius*1000):null},
   {"area_mm2",f.f.GetArea()*1e6},{"origin_local_mm",MM(f.p)},{"direction_local",f.u},
   {"origin_assembly_mm",MM(Point(f.p,f.c))},{"direction_assembly",Vector(f.u,f.c)}};
 }
 static List<IFeature> Features(){
  var rows=new List<IFeature>();
  for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature()){
   if(f.GetTypeName2().StartsWith("Mate")&&f.GetTypeName2()!="MateGroup")rows.Add(f);
   if(f.GetTypeName2()=="MateGroup")for(IFeature sf=(IFeature)f.GetFirstSubFeature();sf!=null;sf=(IFeature)sf.GetNextSubFeature())if(sf.GetTypeName2().StartsWith("Mate"))rows.Add(sf);
  }
  return rows;
 }
 static bool Same(IFace2 a,IFace2 b){return sw.IsSame(a,b)==1;}
 static IComponent2 Component(string name){
  IComponent2 c=ad.GetComponentByName(name);if(c==null)throw new Exception("找不到组件实例："+name);
  bool top=false;foreach(IComponent2 item in (object[])ad.GetComponents(true))if(item.Name2==name)top=true;
  if(!top)throw new Exception("仅支持顶层零件组件，子装配未验证");
  IModelDoc2 model=(IModelDoc2)c.GetModelDoc2();
  if(c.IsSuppressed()||model==null||model.GetType()!=1)throw new Exception("组件必须为已解析且未压缩的零件："+name);
  return c;
 }
 static Face Resolve(Dictionary<string,object> reference){
  if(!SamePath(S(reference,"assembly_path"),md.GetPathName())||S(reference,"assembly_configuration")!=Config())throw new Exception("面引用的装配路径或配置不符");
  IComponent2 c=Component(S(reference,"component"));
  if(!SamePath(c.GetPathName(),S(reference,"part_path"))||c.ReferencedConfiguration!=S(reference,"component_configuration"))throw new Exception("面引用的零件路径或配置已变化");
  int state;object raw=md.Extension.GetObjectByPersistReference3(Convert.FromBase64String(S(reference,"face_ref")),out state);
  IFace2 face=raw as IFace2;if(face==null||state!=0)throw new Exception("持久面引用已失效，state="+state);
  IComponent2 owner=((IEntity)face).GetComponent() as IComponent2;
  if(owner==null||owner.Name2!=c.Name2)throw new Exception("持久引用所属组件不符");
  Face result=ReadFace(face,c);if(result==null||result.kind!=S(reference,"kind"))throw new Exception("持久面引用几何类型不符");return result;
 }
 static Dictionary<string,object> Geometry(Face a,Face b,string type){
  double[]p=Point(a.p,a.c),q=Point(b.p,b.c),u=Vector(a.u,a.c),v=Vector(b.u,b.c),d=Sub(q,p);
  double parallel=Math.Max(-1,Math.Min(1,Math.Abs(Dot(u,v))));double angle=Math.Acos(parallel)*180/Math.PI;
  double gap;
  if(type=="concentric"){
   double[]cross={d[1]*u[2]-d[2]*u[1],d[2]*u[0]-d[0]*u[2],d[0]*u[1]-d[1]*u[0]};gap=Math.Sqrt(Dot(cross,cross))*1000;
  }else gap=Math.Abs(Dot(d,u))*1000;
  return new Dictionary<string,object>{{"gap_mm",gap},{"parallel_error_deg",angle},{"direction_dot",Dot(u,v)},
   {"origin_a_mm",MM(p)},{"origin_b_mm",MM(q)},{"axis_a",u},{"axis_b",v}};
 }
 static bool GeometryOK(Dictionary<string,object>g,double tol,string align){
  bool sign=align=="closest"||(align=="aligned"?N(g,"direction_dot")>0:N(g,"direction_dot")<0);
  return N(g,"gap_mm")<=tol&&N(g,"parallel_error_deg")<=.001&&sign;
 }
 static bool EntityPair(IMate2 mate,Face a,Face b){
  if(mate==null||mate.GetMateEntityCount()!=2)return false;
  IMateEntity2 x=mate.MateEntity(0),y=mate.MateEntity(1);
  IFace2 xf=x.Reference as IFace2,yf=y.Reference as IFace2;
  if(xf==null||yf==null||x.ReferenceComponent==null||y.ReferenceComponent==null)return false;
  return (x.ReferenceComponent.Name2==a.c.Name2&&y.ReferenceComponent.Name2==b.c.Name2&&Same(xf,a.f)&&Same(yf,b.f))
    ||(x.ReferenceComponent.Name2==b.c.Name2&&y.ReferenceComponent.Name2==a.c.Name2&&Same(xf,b.f)&&Same(yf,a.f));
 }
 static IFeature FindPair(Face a,Face b,int type){
  foreach(IFeature f in Features()){IMate2 m=f.GetSpecificFeature2() as IMate2;if(m!=null&&m.Type==type&&EntityPair(m,a,b))return f;}return null;
 }
 static Dictionary<string,object> Inspect(Dictionary<string,object>spec){
  Face a=Resolve(D(spec["face_a"])),b=Resolve(D(spec["face_b"]));string type=S(spec,"type");
  IFeature f=FindPair(a,b,type=="concentric"?1:0);bool warning=false;int error=f==null?-1:f.GetErrorCode2(out warning);
  var geometry=Geometry(a,b,type);
  return new Dictionary<string,object>{{"ok",f!=null&&error==0&&GeometryOK(geometry,N(spec,"verify_tolerance_mm"),S(spec,"alignment"))},
   {"type",type},{"feature_name",f==null?null:f.Name},{"entity_identity_match",f!=null},{"feature_error",error},{"geometry",geometry}};
 }
 public static string Run(string path){
  var result=new Dictionary<string,object>{{"ok",false},{"modified",false},{"built",0}};
  var created=new List<IFeature>();var transforms=new Dictionary<string,double[]>();var targetComponents=new Dictionary<string,IComponent2>();int baselineCount=-1;
  try{
   cmd=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path,System.Text.Encoding.UTF8));
   sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));
   if(sw.GetProcessID()!=Convert.ToInt32(cmd["process_id"]))throw new Exception("COM连接到不同SolidWorks进程");
   if(int.Parse(sw.RevisionNumber().Split('.')[0])!=typeof(ISldWorks).Assembly.GetName().Version.Major)throw new Exception("Interop DLL与运行的SolidWorks版本不一致");
   md=(IModelDoc2)sw.ActiveDoc;if(md==null||md.GetType()!=2)throw new Exception("当前文档不是装配体");ad=(IAssemblyDoc)md;math=(IMathUtility)sw.GetMathUtility();EnsureTarget();
   result["sw_version"]=sw.RevisionNumber();result["assembly_path"]=md.GetPathName();result["configuration"]=Config();
   string mode=S(cmd,"mode");
   baselineCount=Features().Count;result["mate_count_before"]=baselineCount;
   if(mode=="list"){
    var rows=new List<Dictionary<string,object>>();bool found=false;
    foreach(IComponent2 c in (object[])ad.GetComponents(true)){
     if(S(cmd,"component")!=""&&c.Name2!=S(cmd,"component"))continue;found=true;Component(c.Name2);
     object[]bodies=(object[])c.GetBodies2(0);if(bodies==null)throw new Exception("组件没有可枚举实体："+c.Name2);int index=0;
     foreach(IBody2 body in bodies)foreach(IFace2 raw in (object[])body.GetFaces()){
      Face f=ReadFace(raw,c);int current=index++;if(f!=null&&(S(cmd,"kind")==""||f.kind==S(cmd,"kind")))rows.Add(Row(f,current));
     }
    }
    if(!found)throw new Exception("找不到指定组件");result["faces"]=rows;result["count"]=rows.Count;result["ok"]=true;
   }else{
    var specs=new List<Dictionary<string,object>>();foreach(object o in (IEnumerable)cmd["mates"])specs.Add(D(o));
    // 全部面先解析，避免后面的无效引用导致只完成半批配合。
    foreach(var spec in specs){
     Face a=Resolve(D(spec["face_a"])),b=Resolve(D(spec["face_b"]));
     if(a.c.Name2==b.c.Name2)throw new Exception("不能在同一组件实例内部加装配配合");
     string kind=S(spec,"type")=="concentric"?"cylinder":"plane";if(a.kind!=kind||b.kind!=kind)throw new Exception("指定面类型与配合不符");
     foreach(Face f in new[]{a,b})if(!transforms.ContainsKey(f.c.Name2)){transforms[f.c.Name2]=(double[])f.c.Transform2.ArrayData;targetComponents[f.c.Name2]=f.c;}
    }
    if(mode=="apply"){
     foreach(var spec in specs){
      EnsureTarget();Face a=Resolve(D(spec["face_a"])),b=Resolve(D(spec["face_b"]));int type=S(spec,"type")=="concentric"?1:0;
      if(FindPair(a,b,type)!=null)throw new Exception("目标面之间已有同类型配合，不重复创建");
      int align=S(spec,"alignment")=="aligned"?0:S(spec,"alignment")=="anti_aligned"?1:2;
      if(a.c.IsFixed()&&b.c.IsFixed()&&!GeometryOK(Geometry(a,b,S(spec,"type")),N(spec,"verify_tolerance_mm"),S(spec,"alignment")))throw new Exception("两组件都固定且目标几何不满足配合");
      md.ClearSelection2(true);
      if(!((IEntity)a.f).Select2(false,1)||!((IEntity)b.f).Select2(true,1))throw new Exception("明确指定的面选择失败，不自动换面");
      ISelectionMgr manager=(ISelectionMgr)md.SelectionManager;
      if(manager.GetSelectedObjectCount2(1)!=2||sw.IsSame(manager.GetSelectedObject6(1,1),a.f)!=1||sw.IsSame(manager.GetSelectedObject6(2,1),b.f)!=1)throw new Exception("选择集回读与目标面不一致");
      var beforeFeatures=Features();int error;
      result["modified"]=true;
      IMate2 mate=ad.AddMate5(type,align,false,0,0,0,1,1,0,0,0,false,false,0,out error);
      md.ClearSelection2(true);md.EditRebuild3();
      IFeature createdFeature=null;
      foreach(IFeature f in Features()){
       bool old=false;foreach(IFeature previous in beforeFeatures)if(sw.IsSame(previous,f)==1)old=true;
       if(!old){created.Add(f);if(EntityPair(f.GetSpecificFeature2() as IMate2,a,b))createdFeature=f;}
      }
      if(mate==null||error!=1||createdFeature==null||!EntityPair(mate,a,b))throw new Exception("原生配合创建或面身份回读失败，AddMate5状态="+error);
      var check=Inspect(spec);if(!(bool)check["ok"])throw new Exception("配合几何或原生特征回读失败："+json.Serialize(check));
     }
    }else if(mode!="inspect")throw new Exception("未知操作");
    var checks=new List<Dictionary<string,object>>();bool all=true;
    foreach(var spec in specs){var check=Inspect(spec);checks.Add(check);if(!(bool)check["ok"])all=false;}
    result["mates"]=checks;result["requested"]=specs.Count;result["built"]=created.Count;
    if(mode=="apply"&&!all)throw new Exception("后续配合破坏先前约束，批次回读失败");
    result["ok"]=all;
    if(!all)result["error"]="未找到指定面的原生配合，或几何回读不满足要求";
    var positions=new List<object>();foreach(var pair in targetComponents)positions.Add(new {component=pair.Key,transform=(double[])pair.Value.Transform2.ArrayData});result["component_transforms"]=positions;
   }
   EnsureTarget();result["mate_count_after"]=Features().Count;
  }catch(Exception e){
   result["ok"]=false;result["error"]=e.Message;
   if(created.Count>0||(bool)result["modified"]){
    try{
     EnsureTarget();for(int i=created.Count-1;i>=0;i--){md.ClearSelection2(true);if(!created[i].Select2(false,0)||!md.Extension.DeleteSelection2(0))throw new Exception("无法删除本批次新配合");}
     foreach(var pair in transforms)targetComponents[pair.Key].Transform2=(MathTransform)math.CreateTransform(pair.Value);
     md.ClearSelection2(true);md.EditRebuild3();bool restored=true;
     foreach(var pair in transforms){double[]actual=(double[])targetComponents[pair.Key].Transform2.ArrayData;for(int i=0;i<actual.Length;i++)if(Math.Abs(actual[i]-pair.Value[i])>1e-8)restored=false;}
     restored=restored&&Features().Count==baselineCount;
     result["rollback_ok"]=restored;result["built"]=0;result["mate_count_after"]=Features().Count;
    }catch(Exception rollback){result["rollback_ok"]=false;result["rollback_error"]=rollback.Message;}
   }
  }finally{if(md!=null)try{md.ClearSelection2(true);}catch{}}
  return json.Serialize(result);
 }
}
'''
