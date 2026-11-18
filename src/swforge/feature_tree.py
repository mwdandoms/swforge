"""Read native tree structure, errors, body geometry and sketch pattern relations."""
from .native_bridge import target_document,run_native
from .session import get_session,_value

def inspect_feature_tree(part_path):
    sw=None;owned=False
    try:
        import os
        path=os.path.abspath(part_path)
        sw=get_session().sw();owned=sw.GetOpenDocumentByName(path) is None
        _,_,target=target_document(path,1)
        return run_native(target,engine=_ENGINE)
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}
    finally:
        if owned and sw is not None:sw.CloseDoc(path)

_ENGINE=r'''
using System;
using System.IO;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
public class __CLASS__ {
 static JavaScriptSerializer json=new JavaScriptSerializer(){MaxJsonLength=16777216};
 static Dictionary<string,object> R(params object[] a){var r=new Dictionary<string,object>();for(int i=0;i<a.Length;i+=2)r[(string)a[i]]=a[i+1];return r;}
 static List<object> rows=new List<object>();static HashSet<string> seen=new HashSet<string>();
 static void Walk(IFeature f,string parent){
  string key=f.Name+"/"+f.GetTypeName2();if(!seen.Add(key))return;
  if(rows.Count>20000)throw new Exception("Tree traversal limit");
  bool warning=false;int error=f.GetErrorCode2(out warning);
  var row=R("name",f.Name,"type",f.GetTypeName2(),"parent",parent,"error",error,"warning",warning);
  ISketch sketch=f.GetSpecificFeature2() as ISketch;
  if(sketch!=null){
   object[] segments=(object[])sketch.GetSketchSegments();row["sketch_segments"]=segments==null?0:segments.Length;
   int status=sketch.GetConstrainedStatus();row["constrained_status"]=status;row["fully_defined"]=status==3;
  }
  rows.Add(row);
  for(IFeature c=(IFeature)f.GetFirstSubFeature();c!=null;c=(IFeature)c.GetNextSubFeature())Walk(c,f.Name);
 }
 public static string Run(string file){try{
  var cmd=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(file));
  ISldWorks sw=SwforgeConnection.Connect();
  if(sw.GetProcessID()!=Convert.ToInt32(cmd["process_id"]))throw new Exception("Process mismatch");
  if(typeof(ISldWorks).Assembly.GetName().Version.Major!=Int32.Parse(sw.RevisionNumber().Split('.')[0]))throw new Exception("Interop/runtime major version mismatch");
  IModelDoc2 md=(IModelDoc2)sw.ActiveDoc;
  if(md==null||md.GetType()!=1||!String.Equals(md.GetPathName(),(string)cmd["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Document mismatch");
  for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())Walk(f,"");
  var bodies=new List<object>();double volume=0;int errors=0,features=0;
  foreach(Dictionary<string,object> row in rows){if(Convert.ToInt32(row["error"])!=0)errors++;if(((string)row["name"]).StartsWith("SWFORGE_")&&(string)row["type"]!="ProfileFeature")features++;}
  object[] source=(object[])((IPartDoc)md).GetBodies2(0,false);
  if(source!=null)foreach(IBody2 b in source){
   double[] mass=(double[])b.GetMassProperties(1);volume+=mass[3]*1e9;var cylinders=new List<object>();
   foreach(IFace2 face in (object[])b.GetFaces()){
    ISurface s=(ISurface)face.GetSurface();if(!s.IsCylinder())continue;
    double[] c=(double[])s.CylinderParams;
    cylinders.Add(R("origin_mm",new double[]{c[0]*1000,c[1]*1000,c[2]*1000},"axis",new double[]{c[3],c[4],c[5]},"diameter_mm",c[6]*2000));
   }
   bodies.Add(R("name",b.Name,"volume_mm3",mass[3]*1e9,"cylinders",cylinders,"bbox_m",b.GetBodyBox()));
  }
  var equations=new List<string>();IEquationMgr em=(IEquationMgr)md.GetEquationMgr();
  for(int i=0;i<em.GetCount();i++)equations.Add(em.Equation[i]);
  return json.Serialize(R("ok",true,"path",md.GetPathName(),"sw_revision",sw.RevisionNumber(),"features",rows,"equations",equations,"unique_tree_nodes",rows.Count,"swforge_modeling_features",features,"feature_errors",errors,"body_count",bodies.Count,"volume_mm3",volume,"bodies",bodies));
 }catch(Exception e){return json.Serialize(R("ok",false,"error",e.ToString()));}}
}
'''
