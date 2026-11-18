"""Native Hole Wizard plates, explicit hole specifications and geometry verification."""
from __future__ import annotations
from pathlib import Path
import math,json
from .native_bridge import target_document,run_native


def hole_plate_plan(*,length=120,width=80,thickness=20,holes):
    values=[float(x) for x in (length,width,thickness)]
    if not all(math.isfinite(x) and x>0 for x in values):raise ValueError('Positive finite plate dimensions required')
    if not isinstance(holes,list) or not 1<=len(holes)<=100:raise ValueError('1..100 explicit holes required')
    allowed={'id','kind','x','y','diameter','through','depth','head_diameter','head_depth','angle',
             'size','standard_index','fastener_type_index','thread_class','thread_depth','drill_angle','positions'}
    normalized=[];ids=set();locations=[]
    for h in holes:
        if not isinstance(h,dict) or set(h)-allowed:raise ValueError('Unknown hole fields')
        if not isinstance(h.get('id'),str) or not h['id'] or h['id'] in ids:raise ValueError('Unique explicit hole id required')
        ids.add(h['id']);kind=h.get('kind')
        if kind not in ('simple','counterbore','countersink','tapped'):raise ValueError('Unsupported hole type')
        n=dict(h);n['through']=h.get('through',True)
        if not isinstance(n['through'],bool):raise ValueError('through must be boolean')
        for k in ('diameter','x','y','standard_index','fastener_type_index','size'):
            if k not in n:raise ValueError('Explicit Hole Wizard parameter required: '+k)
        for k in ('diameter','depth','head_diameter','head_depth','angle','thread_depth','drill_angle'):
            if k in n and (isinstance(n[k],bool) or not math.isfinite(float(n[k])) or float(n[k])<=0):raise ValueError('Positive finite '+k+' required')
        if not n['through'] and ('depth' not in n or n['depth']>=thickness):raise ValueError('Blind hole depth must be inside plate')
        if kind in ('counterbore','countersink'):
            if n.get('head_diameter',0)<=n['diameter']:raise ValueError('Head diameter must exceed drill diameter')
            if kind=='counterbore' and not 0<n.get('head_depth',0)<thickness:raise ValueError('Counterbore depth must be inside plate')
            if kind=='countersink' and not 0<n.get('angle',0)<180:raise ValueError('Explicit countersink included angle required')
        if kind=='tapped' and (not n.get('thread_class') or not n.get('thread_depth')):raise ValueError('Explicit thread class/depth required')
        n['positions']=h.get('positions') or [[h['x'],h['y']]]
        if not isinstance(n['positions'],list) or len(n['positions'])>100:raise ValueError('Explicit hole position list required')
        radius=max(n['diameter'],n.get('head_diameter',0))/2
        for xy in n['positions']:
            if len(xy)!=2 or not all(math.isfinite(float(v)) for v in xy):raise ValueError('Position must be finite XY mm')
            x,y=map(float,xy)
            if not radius<x<length-radius or not radius<y<width-radius:raise ValueError('Hole/fastener head must fit inside plate')
            if any(math.hypot(x-a,y-b)<radius+r+.1 for a,b,r in locations):raise ValueError('Holes overlap or have insufficient explicit clearance')
            locations.append((x,y,radius))
        normalized.append(n)
    return dict(length=values[0],width=values[1],thickness=values[2],holes=normalized)


_ENGINE=r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public class __CLASS__{
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
static double N(Dictionary<string,object> c,string k,double d=0){return c.ContainsKey(k)?Convert.ToDouble(c[k]):d;}
public static string Run(string req){var json=new JavaScriptSerializer(){MaxJsonLength=16777216};try{
var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(req));var sw=SwforgeConnection.Connect();var md=(IModelDoc2)sw.ActiveDoc;
if(md==null||md.GetType()!=1||sw.GetProcessID()!=Convert.ToInt32(c["process_id"])||!String.Equals(md.GetPathName(),(string)c["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Active part changed");
var spec=(Dictionary<string,object>)c["spec"];var results=new List<object>();double t=N(spec,"thickness")/1000;
if((string)c["mode"]=="create")foreach(Dictionary<string,object> h in (System.Collections.ArrayList)spec["holes"]){
string kind=(string)h["kind"];int generic=kind=="counterbore"?0:kind=="countersink"?1:kind=="tapped"?4:2;bool through=Convert.ToBoolean(h["through"]);
md.ClearSelection2(true);int selections=0;
foreach(System.Collections.ArrayList xy in (System.Collections.ArrayList)h["positions"]){double x=Convert.ToDouble(xy[0])/1000,y=Convert.ToDouble(xy[1])/1000;if(!md.Extension.SelectByRay(x,y,t+.01,0,0,-1,.00001,2,false,0,0))throw new Exception("Cannot select explicit hole location");selections++;break;}
double v1=0,v2=0,v3=0;
if(kind=="counterbore"){v1=N(h,"head_diameter")/1000;v2=N(h,"head_depth")/1000;}
if(kind=="countersink"){v1=N(h,"head_diameter")/1000;v2=N(h,"angle")*Math.PI/180;}
// Thread settings are explicitly applied to valid feature-data fields below.
var f=md.FeatureManager.HoleWizard5(generic,Convert.ToInt32(h["standard_index"]),Convert.ToInt32(h["fastener_type_index"]),(string)h["size"],(short)(through?1:0),N(h,"diameter")/1000,through?t:N(h,"depth")/1000,0,v1,v2,v3,0,0,0,0,0,0,0,0,0,h.ContainsKey("thread_class")?(string)h["thread_class"]:"",false,true,true,false,false,false);
if(f==null)throw new Exception("Hole Wizard failed for "+h["id"]+"; verify installed standards database/size");f.Name="SWFORGE_HOLE_"+h["id"];
var data=(IWizardHoleFeatureData2)f.GetDefinition();if(!data.AccessSelections(md,null))throw new Exception("Cannot access hole definition");
if(kind=="tapped"){data.ThreadDepth=N(h,"thread_depth")/1000;data.ThreadClass=(string)h["thread_class"];data.CosmeticThreadType=2;}
if(!through&&h.ContainsKey("drill_angle"))data.DrillAngle=N(h,"drill_angle")*Math.PI/180;
if(!f.ModifyDefinition(data,md,null))throw new Exception("Hole definition settings rejected");data.ReleaseSelectionAccess();
var locations=(System.Collections.ArrayList)h["positions"];
if(locations.Count>1){
 data=(IWizardHoleFeatureData2)f.GetDefinition();object[] rawPoints=(object[])data.GetSketchPoints();var point=(ISketchPoint)rawPoints[0];var positionSketch=(ISketch)point.GetSketch();IFeature positionFeature=null;
 for(IFeature child=(IFeature)f.GetFirstSubFeature();child!=null;child=(IFeature)child.GetNextSubFeature())if(Object.ReferenceEquals(child.GetSpecificFeature2(),positionSketch))positionFeature=child;
 if(positionFeature==null)throw new Exception("Cannot locate Hole Wizard position sketch");
 md.ClearSelection2(true);positionFeature.Select2(false,0);md.EditSketch();bool old=md.SketchManager.AddToDB;md.SketchManager.AddToDB=true;
 try{var math=(IMathUtility)sw.GetMathUtility();for(int i=1;i<locations.Count;i++){var xy=(System.Collections.ArrayList)locations[i];var mp=(IMathPoint)math.CreatePoint(new double[]{Convert.ToDouble(xy[0])/1000,Convert.ToDouble(xy[1])/1000,t});var local=(double[])((IMathPoint)mp.MultiplyTransform(positionSketch.ModelToSketchTransform)).ArrayData;md.SketchManager.CreatePoint(local[0],local[1],0);}}
 finally{md.SketchManager.AddToDB=old;md.InsertSketch2(true);}md.ForceRebuild3(false);data=(IWizardHoleFeatureData2)f.GetDefinition();
 data.AccessSelections(md,null);if(!f.ModifyDefinition(data,md,null))throw new Exception("Multi-position hole regeneration failed");data.ReleaseSelectionAccess();md.ForceRebuild3(false);data=(IWizardHoleFeatureData2)f.GetDefinition();
 if(data.GetSketchPointCount()!=locations.Count)throw new Exception("Hole Wizard position count mismatch");
}
md.EditRebuild3();results.Add(R("feature",f.Name,"type",f.GetTypeName2(),"wizard_type",data.Type,"standard_index",data.Standard2,"fastener_type_index",data.FastenerType2,"size",data.FastenerSize,"positions",data.GetSketchPointCount(),"thru_diameter_m",data.ThruHoleDiameter,"blind_diameter_m",data.HoleDiameter,"blind_depth_m",data.HoleDepth,"counterbore_depth_m",data.CounterBoreDepth,"counterbore_diameter_m",data.CounterBoreDiameter,"countersink_diameter_m",data.CounterSinkDiameter,"countersink_angle_rad",data.CounterSinkAngle,"thread_depth_m",data.ThreadDepth,"tap_drill_diameter_m",data.ThruTapDrillDiameter));
}
var cylinders=new List<object>();var cones=new List<object>();double volume=0;
foreach(object o in (object[])((IPartDoc)md).GetBodies2(0,false)??new object[0]){var body=(IBody2)o;volume+=((double[])body.GetMassProperties(1))[3];foreach(object of in (object[])body.GetFaces()??new object[0]){var face=(IFace2)of;var s=(ISurface)face.GetSurface();if(s.IsCylinder())cylinders.Add(R("parameters",s.CylinderParams,"bounds",face.GetBox(),"area",face.GetArea()));if(s.IsCone())cones.Add(R("parameters",s.ConeParams,"bounds",face.GetBox()));}}
int errors=0,warnings=0;if((string)c["mode"]=="create"&&(!md.Save3(1,ref errors,ref warnings)||errors!=0))throw new Exception("Hole plate save failed");
return json.Serialize(R("ok",true,"features",results,"cylinders",cylinders,"cones",cones,"volume_m3",volume));
}catch(Exception e){return json.Serialize(R("ok",false,"error",e.ToString(),"mutation_state","inspect generated part"));}}}
'''


def _verify(spec,native):
    matches=[]
    for h in spec['holes']:
        for x,y in h['positions']:
            found=[]
            for face in native.get('cylinders',[]):
                p=face['parameters']
                if abs(p[0]*1000-x)<1e-4 and abs(p[1]*1000-y)<1e-4 and abs(p[5])>.999999:
                    found.append(dict(diameter_mm=p[6]*2000,bounds_m=face['bounds']))
            expected=[h['diameter']]+([h['head_diameter']] if h['kind']=='counterbore' else [])
            ok=all(any(abs(f['diameter_mm']-d)<1e-4 for f in found) for d in expected)
            matches.append(dict(id=h['id'],xy_mm=[x,y],expected_diameters_mm=expected,cylinders=found,ok=ok))
    return dict(ok=native.get('ok',False) and all(r['ok'] for r in matches),holes=matches,
                note='Native cylinder verification; cosmetic thread geometry is not a modeled helical thread')


def create_hole_plate(out_path,*,length=120,width=80,thickness=20,holes,material='Q235'):
    from .modeling import PartBuilder
    from .resources import document_scope
    from .variants import file_sha256
    spec=hole_plate_plan(length=length,width=width,thickness=thickness,holes=holes)
    out=Path(out_path).resolve()
    if out.exists() or out.suffix.lower()!='.sldprt' or Path(str(out)+'.holes.json').exists():raise ValueError('New .SLDPRT output required')
    with document_scope(str(out),keep_open=False) as lease:
        build=PartBuilder(str(out),material=material).box('HOLE_PLATE',0,length,0,width,0,thickness).build()
        if not build.ok:return {'ok':False,'build':build.__dict__}
        _,md,guard=target_document(out,1);lease.own(md)
        native=run_native(dict(guard,mode='create',spec=spec),engine=_ENGINE)
        check=_verify(spec,native)
        result=dict(ok=check['ok'],part=str(out),spec=spec,native=native,verification=check,review_required=True)
        if result['ok']:
            result['model_sha256']=file_sha256(out)
            Path(str(out)+'.holes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        lease.failed=not result['ok'];return result


def inspect_hole_plate(part_path):
    metadata=json.loads(Path(str(part_path)+'.holes.json').read_text(encoding='utf8'))
    from .variants import file_sha256
    if file_sha256(part_path)!=metadata['model_sha256']:raise ValueError('Hole family geometry/revision changed; metadata is stale')
    _,_,guard=target_document(part_path,1)
    native=run_native(dict(guard,mode='inspect',spec=metadata['spec']),engine=_ENGINE)
    return dict(ok=native.get('ok') and _verify(metadata['spec'],native)['ok'],native=native,verification=_verify(metadata['spec'],native),spec=metadata['spec'])
