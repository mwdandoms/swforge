"""Verify a controlled Z-axis gear's central section using actual cut faces."""
from .native_bridge import target_document,run_native

_ENGINE = r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public class __CLASS__{
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
public static string Run(string request){try{var json=new JavaScriptSerializer();var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));var sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));var md=(IModelDoc2)sw.ActiveDoc;
if(sw.GetProcessID()!=Convert.ToInt32(c["process_id"])||md==null||md.GetType()!=3||!String.Equals(md.GetPathName(),(string)c["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Active drawing changed");
var dr=(IDrawingDoc)md;IView target=null;for(IView v=(IView)((IView)dr.GetFirstView()).GetNextView();v!=null;v=(IView)v.GetNextView())if(v.Name==(string)c["view"])target=v;
if(target==null||target.Type!=2)throw new Exception("Section view missing");var faces=new List<object>();
foreach(object o in (object[])target.GetFaceHatches()??new object[0]){var f=(IFace2)((IFaceHatch)o).Face;var s=(ISurface)f.GetSurface();var vertices=new List<object>();foreach(object oe in (object[])f.GetEdges()??new object[0]){var e=(IEdge)oe;var a=(IVertex)e.GetStartVertex();var b=(IVertex)e.GetEndVertex();if(a!=null)vertices.Add(a.GetPoint());if(b!=null)vertices.Add(b.GetPoint());}faces.Add(R("planar",s.IsPlane(),"vertices_m",vertices,"area_m2",f.GetArea()));}
return json.Serialize(R("ok",true,"view",target.Name,"hatch_count",target.GetFaceHatchCount(),"faces",faces));
}catch(Exception e){return new JavaScriptSerializer().Serialize(R("ok",false,"error",e.ToString()));}}}
'''


def evaluate_central_bore(snapshot,bore_mm,total_width_mm):
    import math
    if not all(math.isfinite(float(v)) and float(v)>0 for v in (bore_mm,total_width_mm)):
        raise ValueError('Positive finite bore and width required')
    radius=bore_mm/2000;tol=1e-7
    facts=[];sides=set()
    for face in snapshot.get('faces',[]):
        pts=face.get('vertices_m',[])
        if not face.get('planar') or not pts:continue
        # Controlled builder: gear axis Z, requested section X=0.
        if any(abs(p[0])>tol for p in pts):continue
        lo,hi=min(p[1] for p in pts),max(p[1] for p in pts)
        side=1 if lo>=radius-tol and abs(lo-radius)<tol else -1 if hi<=-radius+tol and abs(hi+radius)<tol else 0
        zmin,zmax=min(p[2] for p in pts),max(p[2] for p in pts)
        if side and abs(zmin)<tol and abs(zmax-total_width_mm/1000)<tol:
            sides.add(side);facts.append({'side':side,'y_range_m':[lo,hi],'z_range_m':[zmin,zmax]})
    ok=bool(snapshot.get('ok') and {-1,1}<=sides)
    return dict(ok=ok,central_bore_verified=ok,bore_mm=bore_mm,cut_plane='X=0; controlled Z-axis gear only',
                matched_cut_faces=facts,hatch_count=snapshot.get('hatch_count',0),
                error='' if ok else 'Actual cut faces do not prove both sides of the central bore')


def verify_section_bore(drawing_path,view_name,*,bore_mm,total_width_mm):
    _,_,guard=target_document(drawing_path,3)
    native=run_native(dict(guard,view=view_name),engine=_ENGINE)
    return dict(evaluate_central_bore(native,bore_mm,total_width_mm),native=native)
