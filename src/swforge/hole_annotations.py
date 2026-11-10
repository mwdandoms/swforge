"""Native Hole Wizard callouts, hole tables and explicit XY positions for plate family."""
from pathlib import Path
import json
from .native_bridge import target_document,run_native
from .variants import file_sha256

_ENGINE=r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public class __CLASS__{
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
public static string Run(string req){var json=new JavaScriptSerializer(){MaxJsonLength=16777216};try{var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(req));var sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));var md=(IModelDoc2)sw.ActiveDoc;
if(md==null||md.GetType()!=3||sw.GetProcessID()!=Convert.ToInt32(c["process_id"])||!String.Equals(md.GetPathName(),(string)c["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Active drawing changed");
var dr=(IDrawingDoc)md;IView view=null;for(IView v=(IView)((IView)dr.GetFirstView()).GetNextView();v!=null;v=(IView)v.GetNextView())if(v.Name==(string)c["view"])view=v;if(view==null)throw new Exception("View missing");
var spec=(Dictionary<string,object>)c["spec"];var edges=(object[])view.GetVisibleEntities2(null,1);var results=new List<object>();
foreach(Dictionary<string,object> h in (System.Collections.ArrayList)spec["holes"]){var xy=(System.Collections.ArrayList)((System.Collections.ArrayList)h["positions"])[0];double x=Convert.ToDouble(xy[0])/1000,y=Convert.ToDouble(xy[1])/1000;IEdge target=null;double biggest=0;
foreach(object oe in edges){var e=(IEdge)oe;var curve=(ICurve)e.GetCurve();if(!curve.IsCircle())continue;var p=(double[])curve.CircleParams;if(Math.Abs(p[0]-x)<1e-7&&Math.Abs(p[1]-y)<1e-7&&Math.Abs(p[5])>.999&&p[6]>biggest){target=e;biggest=p[6];}}
if(target==null)throw new Exception("Visible hole missing: "+h["id"]);dr.ActivateView(view.Name);md.ClearSelection2(true);view.SelectEntity((IEntity)target,false);var dd=(IDisplayDimension)dr.AddHoleCallout2(.27,.255-results.Count*.018,0);if(dd==null)throw new Exception("Native hole callout failed");
var ann=(IAnnotation)dd.GetAnnotation();var display=(IDisplayData)ann.GetDisplayData();var texts=new List<string>();for(int i=0;i<display.GetTextCount();i++)texts.Add(display.GetTextAtIndex(i));results.Add(R("id",h["id"],"name",((IDimension)dd.GetDimension2(0)).FullName,"text",texts,"attached",ann.GetAttachedEntityCount3(),"dangling",ann.IsDangling()));
}
var reference=(IModelDoc2)view.ReferencedDocument;IVertex origin=null;foreach(object o in (object[])view.GetVisibleEntities2(null,2)??new object[0]){var v=(IVertex)o;var p=(double[])v.GetPoint();if(Math.Abs(p[0])+Math.Abs(p[1])<1e-7)origin=v;}
IFace2 topFace=null;foreach(object ob in (object[])((IPartDoc)reference).GetBodies2(0,false))foreach(object of in (object[])((IBody2)ob).GetFaces()){var f=(IFace2)of;var surface=(ISurface)f.GetSurface();if(surface.IsPlane()){var box=(double[])f.GetBox();double t=Convert.ToDouble(spec["thickness"])/1000;if(Math.Abs(box[2]-t)+Math.Abs(box[5]-t)<1e-7)topFace=f;}}
origin=null;var math=(IMathUtility)sw.GetMathUtility();var originMath=(IMathPoint)math.CreatePoint(new double[]{0,0,Convert.ToDouble(spec["thickness"])/1000});var projectedOrigin=(double[])((IMathPoint)originMath.MultiplyTransform(view.ModelToViewTransform)).ArrayData;
foreach(object ov in (object[])view.GetVisibleEntities2(null,2)??new object[0]){var vertex=(IVertex)ov;var point=(double[])vertex.GetPoint();if(Math.Abs(point[0]-projectedOrigin[0])+Math.Abs(point[1]-projectedOrigin[1])<1e-7||Math.Abs(point[0])+Math.Abs(point[1])<1e-7)origin=vertex;}
ITableAnnotation table=null;bool nativeHoleTable=false;
if(origin!=null&&topFace!=null){dr.ActivateView(view.Name);md.ClearSelection2(true);var sm=(ISelectionMgr)md.SelectionManager;if(view.SelectEntity((IEntity)origin,false)){sm.SetSelectedObjectMark(1,1,0);if(view.SelectEntity((IEntity)topFace,true)){sm.SetSelectedObjectMark(2,2,0);dr.ActivateView("");table=(ITableAnnotation)view.InsertHoleTable3(false,.28,.145,0,"A",(string)c["template"],1,1,null);nativeHoleTable=table!=null;}}}
if(table==null){
 int count=0;foreach(Dictionary<string,object> h in (System.Collections.ArrayList)spec["holes"])count+=((System.Collections.ArrayList)h["positions"]).Count;
 md.ClearSelection2(true);dr.ActivateView("");table=(ITableAnnotation)md.Extension.InsertGeneralTableAnnotation(false,.275,.14,1,"",count+1,4);if(table==null)throw new Exception("Coordinate schedule insertion failed");
 string[] headings={"HOLE ID","X / mm","Y / mm","SPEC (see native callout)"};for(int j=0;j<4;j++)table.set_Text2(0,j,false,headings[j]);int index=1;
 foreach(Dictionary<string,object> h in (System.Collections.ArrayList)spec["holes"]){int k=0;foreach(System.Collections.ArrayList xy in (System.Collections.ArrayList)h["positions"]){string id=(string)h["id"]+"-"+(++k);table.set_Text2(index,0,false,id);table.set_Text2(index,1,false,Convert.ToDouble(xy[0]).ToString("0.###",System.Globalization.CultureInfo.InvariantCulture));table.set_Text2(index,2,false,Convert.ToDouble(xy[1]).ToString("0.###",System.Globalization.CultureInfo.InvariantCulture));table.set_Text2(index,3,false,Convert.ToString(h["size"])+" / "+h["kind"]);index++;
 double px=Convert.ToDouble(xy[0])/1000,py=Convert.ToDouble(xy[1])/1000;IEdge labelEdge=null;foreach(object oe in edges){var e=(IEdge)oe;var cv=(ICurve)e.GetCurve();if(cv.IsCircle()){var cp=(double[])cv.CircleParams;if(Math.Abs(cp[0]-px)+Math.Abs(cp[1]-py)<1e-7)labelEdge=e;}}
 dr.ActivateView(view.Name);md.ClearSelection2(true);view.SelectEntity((IEntity)labelEdge,false);var note=(INote)md.InsertNote(id);var a=(IAnnotation)note.GetAnnotation();var mu=(IMathUtility)sw.GetMathUtility();var point=(IMathPoint)mu.CreatePoint(new double[]{px,py,0});var q=(double[])((IMathPoint)point.MultiplyTransform(view.ModelToViewTransform)).ArrayData;a.SetPosition2(q[0]+.008,q[1]+.006,0);
 }}
 for(int j=0;j<4;j++)table.SetColumnWidth(j,j==3?.047:.021,0);
}
table.Anchored=false;table.AnchorType=1;table.GetAnnotation().SetPosition2(.28,.145,0);var cells=new List<object>();for(int i=0;i<table.RowCount;i++){var row=new List<string>();for(int j=0;j<table.ColumnCount;j++)row.Add(table.get_DisplayedText2(i,j,false));cells.Add(row);}
md.ClearSelection2(true);md.EditRebuild3();bool ok=table.RowCount>=2;foreach(Dictionary<string,object> r in results)if(Convert.ToInt32(r["attached"])<1||Convert.ToBoolean(r["dangling"]))ok=false;
return json.Serialize(R("ok",ok,"callouts",results,"native_hole_table",nativeHoleTable,"table_kind",nativeHoleTable?"HoleTable":"verified_coordinate_schedule","table_rows",table.RowCount,"table_type",table.Type,"table_cells",cells,"specialized_hole_table_note",nativeHoleTable?"":"InsertHoleTable3 returned null; explicit native general table used; re-generate after geometry changes"));
}catch(Exception e){return json.Serialize(R("ok",false,"error",e.ToString(),"mutation_state","inspect generated drawing"));}}}
'''

def hole_plate_drawing(part_path,out_path,*,positions=True):
    from .drawing import produce,add_dimensions,_view_list,_save_as
    from .resources import document_scope
    from .hole_families import inspect_hole_plate
    from .position_dimensions import list_position_targets,add_position_dimension
    from .drawing_review import record_drawing_revision
    out=Path(out_path).resolve()
    if out.exists() or out.suffix.lower()!='.slddrw':raise ValueError('New drawing required')
    metadata=json.loads(Path(str(part_path)+'.holes.json').read_text(encoding='utf8'))
    if file_sha256(part_path)!=metadata['model_sha256']:raise ValueError('Stale hole model metadata')
    from .modeling import _find_sw_dir
    directory=Path(_find_sw_dir());templates=list(directory.glob('lang/english/standard hole table--letters.sldholtbt')) or list(directory.glob('lang/*/standard hole table--letters.sldholtbt'))
    if not templates:raise ValueError('Native hole table template is not installed')
    with document_scope(str(out),keep_open=False,related_paths=[str(Path(part_path).resolve())]) as lease:
        result=produce(str(part_path),str(out),keep_open=True)
        if not result['ok']:return result
        sw,md,guard=target_document(out,3);lease.own(md)
        result['dimensions']=add_dimensions(str(out),internal=0)
        view,name=_view_list(md)[0]
        native=run_native(dict(guard,view=name,spec=metadata['spec'],template=str(templates[0])),engine=_ENGINE)
        result['native']=native;result['ok']=bool(native.get('ok') and result['dimensions']['ok'])
        result['positions']=[]
        if result['ok'] and positions:
            spec=metadata['spec'];corners=[[x/1000,y/1000,z/1000] for x in (0,spec['length']) for y in (0,spec['width']) for z in (0,spec['thickness'])]
            refs=list_position_targets(str(out),name,model_vertices=corners)
            if not refs.get('ok'):raise RuntimeError('Position reference collection failed: '+str(refs))
            origin=next((r for r in refs['targets'] if r['kind']=='vertex' and abs(r['point_model_m'][0])+abs(r['point_model_m'][1])<1e-7),None)
            if origin is None:raise RuntimeError('Explicit family origin vertex missing: '+str([(r['kind'],r['point_model_m']) for r in refs.get('targets',[])][:20]))
            for h in metadata['spec']['holes']:
                for x,y in h['positions']:
                    target=next(r for r in refs['targets'] if r['kind']=='circle' and abs(r['point_model_m'][0]*1000-x)<1e-5 and abs(r['point_model_m'][1]*1000-y)<1e-5)
                    for axis in ('horizontal','vertical'):
                        from .session import _value
                        o=list(_value(view,'GetOutline'));idx=len(result['positions']);cx=(o[0]+o[2])/2;cy=(o[1]+o[3])/2
                        r=add_position_dimension(str(out),refs,origin['index'],target['index'],axis=axis,x=cx if axis=='horizontal' else max(.03,o[0]-.009-(idx%6)*.005),y=max(.065,o[1]-.009-(idx%6)*.005) if axis=='horizontal' else cy)
                        result['positions'].append(dict(hole_id=h['id'],xy=[x,y],axis=axis,result=r));result['ok']=result['ok'] and r['ok']
        if result['ok']:result['ok']=_save_as(md,str(out))[0]
        if result['ok']:result['revision']=record_drawing_revision(str(out))
        lease.failed=not result['ok'];return result
