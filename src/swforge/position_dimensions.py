"""Explicit datum-to-feature drawing dimensions with fresh geometry validation."""
from __future__ import annotations
import math
from .native_bridge import target_document,run_native

_ENGINE=r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public class __CLASS__{
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
static bool SameTarget(object left,object right){var a=(Dictionary<string,object>)left;var b=(Dictionary<string,object>)right;if((string)a["kind"]!=(string)b["kind"])return false;foreach(string key in new string[]{"point_model_m","geometry"}){var aa=new List<double>();var bb=new List<double>();foreach(object v in (System.Collections.IEnumerable)a[key])aa.Add(Convert.ToDouble(v));foreach(object v in (System.Collections.IEnumerable)b[key])bb.Add(Convert.ToDouble(v));if(aa.Count!=bb.Count)return false;for(int i=0;i<aa.Count;i++)if(Math.Abs(aa[i]-bb[i])>1e-8)return false;}return true;}
static List<IEntity> entities=new List<IEntity>();static List<double[]> points=new List<double[]>();static List<object> rows=new List<object>();static double[] matrix;
static double[] Project(double[] p){var q=new double[3];for(int i=0;i<3;i++)q[i]=(p[0]*matrix[i]+p[1]*matrix[3+i]+p[2]*matrix[6+i])*matrix[12]+matrix[9+i];return q;}
static List<double[]> modelVertices=new List<double[]>();static double[] viewPosition;
static double[] NativePoint(IVertex vertex){var p=(double[])vertex.GetPoint();foreach(var q in modelVertices)if(Math.Abs(p[0]-q[0])+Math.Abs(p[1]-q[1])+Math.Abs(p[2]-q[2])<1e-8)return p;
 double best=Double.MaxValue;double[] found=null;foreach(var q in modelVertices){var projected=Project(q);double distance=Math.Abs(p[0]-projected[0])+Math.Abs(p[1]-projected[1]);double contextDistance=Math.Abs(p[0]-(projected[0]-matrix[9]+viewPosition[0]))+Math.Abs(p[1]-(projected[1]-matrix[10]+viewPosition[1]));distance=Math.Min(distance,contextDistance);if(distance<1e-7){double rank=distance+Math.Abs(p[2]-q[2])*1e-8;if(rank<best){best=rank;found=q;}}}if(found!=null)return found;
 if(modelVertices.Count>0)throw new Exception("Visible vertex coordinates unresolved: "+String.Join(",",p)+" matrix="+String.Join(",",matrix));return p;}
static void Add(string kind,IEntity e,double[] p,object geometry){int i=entities.Count;entities.Add(e);points.Add(p);rows.Add(R("index",i,"kind",kind,"point_model_m",p,"point_sheet_m",Project(p),"geometry",geometry));}
public static string Run(string request){try{var json=new JavaScriptSerializer(){MaxJsonLength=16777216};var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));var sw=SwforgeConnection.Connect();var md=(IModelDoc2)sw.ActiveDoc;
if(sw.GetProcessID()!=Convert.ToInt32(c["process_id"])||md==null||md.GetType()!=3||!String.Equals(md.GetPathName(),(string)c["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Active drawing changed");
var dr=(IDrawingDoc)md;IView view=null;for(IView v=(IView)((IView)dr.GetFirstView()).GetNextView();v!=null;v=(IView)v.GetNextView())if(v.Name==(string)c["view"])view=v;if(view==null)throw new Exception("View missing");matrix=(double[])((IMathTransform)view.ModelToViewTransform).ArrayData;
viewPosition=(double[])view.Position;var reference=(IModelDoc2)view.ReferencedDocument;if(reference!=null&&reference.GetType()==1)foreach(object ob in (object[])((IPartDoc)reference).GetBodies2(0,false)??new object[0])foreach(object ov in (object[])((IBody2)ob).GetVertices()??new object[0])modelVertices.Add((double[])((IVertex)ov).GetPoint());
if(c.ContainsKey("model_vertices")){modelVertices.Clear();foreach(System.Collections.ArrayList rawPoint in (System.Collections.ArrayList)c["model_vertices"])modelVertices.Add(new double[]{Convert.ToDouble(rawPoint[0]),Convert.ToDouble(rawPoint[1]),Convert.ToDouble(rawPoint[2])});}
foreach(object o in (object[])view.GetVisibleEntities2(null,2)??new object[0]){var vt=(IVertex)o;var vActual=NativePoint(vt);Add("vertex",(IEntity)o,vActual,vActual);}
foreach(object o in (object[])view.GetVisibleEntities2(null,1)??new object[0]){var e=(IEdge)o;var curve=(ICurve)e.GetCurve();if(curve.IsCircle()){double[] cp=(double[])curve.CircleParams;Add("circle",(IEntity)e,new double[]{cp[0],cp[1],cp[2]},cp);}
else if(curve.IsLine()){var a=(IVertex)e.GetStartVertex();var b=(IVertex)e.GetEndVertex();if(a!=null&&b!=null){var pa=NativePoint(a);var pb=NativePoint(b);Add("line",(IEntity)e,new double[]{(pa[0]+pb[0])/2,(pa[1]+pb[1])/2,(pa[2]+pb[2])/2},new double[]{pa[0],pa[1],pa[2],pb[0],pb[1],pb[2]});}}}
if((string)c["mode"]=="list")return json.Serialize(R("ok",true,"drawing",md.GetPathName(),"view",view.Name,"targets",rows,"model_vertices",modelVertices));
int ia=Convert.ToInt32(c["datum"]),ib=Convert.ToInt32(c["target"]);if(ia<0||ib<0||ia>=rows.Count||ib>=rows.Count||ia==ib)throw new Exception("Invalid exact target indices");
if(!SameTarget(rows[ia],c["datum_geometry"])||!SameTarget(rows[ib],c["target_geometry"]))throw new Exception("Geometry changed; enumerate again");
int axis=(string)c["axis"]=="horizontal"?0:1;double expected=Math.Abs(Project(points[ib])[axis]-Project(points[ia])[axis])/matrix[12]*1000;
if(expected<.001)throw new Exception("Projected location is zero");
foreach(int id in new int[]{ia,ib}){var row=(Dictionary<string,object>)rows[id];if((string)row["kind"]=="line"){var coords=(double[])row["geometry"];var a=Project(new double[]{coords[0],coords[1],coords[2]});var b=Project(new double[]{coords[3],coords[4],coords[5]});if(Math.Abs(a[axis]-b[axis])>1e-7)throw new Exception("Datum/target line must be perpendicular to requested dimension axis");}}
double x=Convert.ToDouble(c["x"]),y=Convert.ToDouble(c["y"]);var sheet=(ISheet)dr.GetCurrentSheet();double w=0,h=0;sheet.GetSize(ref w,ref h);if(x<=0||x>=w||y<=0||y>=h)throw new Exception("Dimension position outside sheet");
dr.ActivateView(view.Name);md.ClearSelection2(true);if(!view.SelectEntity(entities[ia],false)||!view.SelectEntity(entities[ib],true))throw new Exception("Selection failed");
var dd=(IDisplayDimension)(axis==0?md.AddHorizontalDimension2(x,y,0):md.AddVerticalDimension2(x,y,0));if(dd==null)throw new Exception("Native location dimension failed");var dim=(IDimension)dd.GetDimension2(0);var ann=(IAnnotation)dd.GetAnnotation();double actual=dim.SystemValue*1000;bool ok=Math.Abs(actual-expected)<1e-5&&!ann.IsDangling()&&ann.GetAttachedEntityCount3()>=2;
md.ClearSelection2(true);md.EditRebuild3();return json.Serialize(R("ok",ok,"modified",true,"name",dim.FullName,"value_mm",actual,"expected_mm",expected,"position_m",ann.GetPosition(),"attached_entity_count",ann.GetAttachedEntityCount3(),"dangling",ann.IsDangling(),"review_required",true));
}catch(Exception e){return new JavaScriptSerializer().Serialize(R("ok",false,"error",e.ToString(),"mutation_state","inspect before retry"));}}}
'''


def list_position_targets(drawing_path,view_name,*,model_vertices=None):
    _,_,guard=target_document(drawing_path,3)
    command=dict(guard,mode='list',view=view_name)
    if model_vertices is not None:command['model_vertices']=model_vertices
    return run_native(command,engine=_ENGINE)


def add_position_dimension(drawing_path,reference,datum_index,target_index,*,axis,x,y):
    if axis not in ('horizontal','vertical'):raise ValueError('axis must be horizontal/vertical')
    if not all(math.isfinite(float(v)) for v in (x,y)):raise ValueError('Finite sheet metres required')
    _,_,guard=target_document(drawing_path,3)
    if reference.get('drawing','').casefold()!=guard['path'].casefold():raise ValueError('Reference belongs to another drawing')
    rows={r['index']:r for r in reference['targets']}
    if any(isinstance(i,bool) or not isinstance(i,int) or i not in rows for i in (datum_index,target_index)):
        raise ValueError('Exact freshly enumerated datum and feature targets are required')
    return run_native(dict(guard,mode='add',view=reference['view'],model_vertices=reference['model_vertices'],datum=datum_index,target=target_index,
                           datum_geometry=rows[datum_index],target_geometry=rows[target_index],axis=axis,x=x,y=y),engine=_ENGINE)
