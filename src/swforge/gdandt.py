"""Explicit attached datum features and native feature-control frames."""
import math,re,uuid
from .position_dimensions import _ENGINE as _POSITION_ENGINE
from .native_bridge import target_document,run_native

SYMBOLS={'position':'<IGTOL-POSI>','flatness':'<IGTOL-FLAT>','parallelism':'<IGTOL-PARA>','perpendicularity':'<IGTOL-PERP>','circular_runout':'<IGTOL-CRUN>'}

def validate_gdt(spec):
    if not isinstance(spec,dict) or set(spec)-{'id','target_index','symbol','tolerance_mm','diameter_zone','datums','datum_targets','x','y'}:raise ValueError('Unknown GD&T fields')
    if spec.get('symbol') not in SYMBOLS:raise ValueError('Unsupported explicit geometric characteristic')
    t=spec.get('tolerance_mm')
    if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or t<=0:raise ValueError('Explicit positive tolerance_mm required')
    ds=spec.get('datums',[])
    if not isinstance(ds,list) or len(ds)>3 or len(set(ds))!=len(ds) or any(not isinstance(d,str) or not re.fullmatch('[A-Z]{1,3}',d) for d in ds):raise ValueError('Explicit ordered unique datum labels required')
    if spec['symbol']=='flatness' and ds:raise ValueError('Flatness must not reference datums')
    if spec['symbol']!='flatness' and not ds:raise ValueError('Referenced datum system must be explicit')
    if not isinstance(spec.get('target_index'),int) or isinstance(spec['target_index'],bool):raise ValueError('Exact target required')
    if not all(isinstance(spec.get(k),(float,int)) and not isinstance(spec[k],bool) and math.isfinite(spec[k]) and spec[k]>0 for k in ('x','y')):raise ValueError('Positive finite sheet metres x/y required')
    for label,index in spec.get('datum_targets',{}).items():
        if label not in ds or not isinstance(index,int) or isinstance(index,bool):raise ValueError('Datum targets must map requested labels to exact indices')
    return spec

_GDT=r'''
if((string)c["mode"]=="gdt"){
var spec=(Dictionary<string,object>)c["spec"];int target=Convert.ToInt32(spec["target_index"]);var expectedGeometry=(Dictionary<string,object>)c["geometry"];
foreach(var kv in expectedGeometry){int id=Int32.Parse(kv.Key);if(id<0||id>=rows.Count||!SameTarget(rows[id],kv.Value))throw new Exception("GD&T target geometry changed");}
var labels=new HashSet<string>();for(IView vv=(IView)dr.GetFirstView();vv!=null;vv=(IView)vv.GetNextView())foreach(object oo in (object[])vv.GetAnnotations()??new object[0]){var dt=((IAnnotation)oo).GetSpecificAnnotation() as IDatumTag;if(dt!=null&&!labels.Add(dt.GetLabel()))throw new Exception("Duplicate datum label already exists");}
var ds=(System.Collections.ArrayList)spec["datums"];var datumTargets=(Dictionary<string,object>)spec["datum_targets"];
foreach(string label in ds)if(!labels.Contains(label)){
 if(!datumTargets.ContainsKey(label))throw new Exception("Datum "+label+" is not declared on drawing");int di=Convert.ToInt32(datumTargets[label]);
 dr.ActivateView(view.Name);md.ClearSelection2(true);if(!view.SelectEntity(entities[di],false))throw new Exception("Datum selection failed");
 var datum=(IDatumTag)md.InsertDatumTag2();if(datum==null||!datum.SetLabel(label))throw new Exception("Datum insertion failed");var da=(IAnnotation)datum.GetAnnotation();da.SetPosition2(Convert.ToDouble(spec["x"])-.025,Convert.ToDouble(spec["y"])+.015*labels.Count,0);labels.Add(label);
}
dr.ActivateView(view.Name);md.ClearSelection2(true);if(!view.SelectEntity(entities[target],false))throw new Exception("GTol target selection failed");
var gt=(IGtol)md.InsertGtol();if(gt==null)throw new Exception("InsertGtol failed");
gt.SetFrameSymbols2(1,(string)c["symbol"],Convert.ToBoolean(spec["diameter_zone"]),"",false,"","","","");
string value=Convert.ToDouble(spec["tolerance_mm"]).ToString("0.#########",System.Globalization.CultureInfo.InvariantCulture);
if(!gt.SetFrameValues2(1,value,"",ds.Count>0?(string)ds[0]:"",ds.Count>1?(string)ds[1]:"",ds.Count>2?(string)ds[2]:""))throw new Exception("GTol frame rejected");
var gAnn=(IAnnotation)gt.GetAnnotation();gAnn.SetName((string)c["name"]);bool moved=gAnn.SetPosition2(Convert.ToDouble(spec["x"]),Convert.ToDouble(spec["y"]),0);md.EditRebuild3();
return json.Serialize(R("ok",moved&&gt.IsAttached()&&!gAnn.IsDangling(),"name",gAnn.GetName(),"frame_values",gt.GetFrameValues(1),"frame_symbols",gt.GetFrameSymbols2(1),"attached_entity_count",gAnn.GetAttachedEntityCount3(),"dangling",gAnn.IsDangling(),"position_m",gAnn.GetPosition(),"modified",true));
}
'''

def add_geometric_tolerance(drawing_path,reference,spec):
    spec=dict(validate_gdt(spec));spec.setdefault('datums',[]);spec.setdefault('datum_targets',{});spec.setdefault('diameter_zone',False)
    rows={r['index']:r for r in reference['targets']};indices={spec['target_index'],*spec['datum_targets'].values()}
    if not indices<=rows.keys():raise ValueError('Exact target/datum index missing')
    _,_,guard=target_document(drawing_path,3)
    if guard['path'].casefold()!=reference['drawing'].casefold():raise ValueError('References belong to another drawing')
    engine=_POSITION_ENGINE.replace('int ia=Convert.ToInt32(c["datum"])',_GDT+'\nint ia=Convert.ToInt32(c["datum"])')
    return run_native(dict(guard,mode='gdt',view=reference['view'],model_vertices=reference['model_vertices'],geometry={str(i):rows[i] for i in indices},
        spec=spec,symbol=SYMBOLS[spec['symbol']],name='SWFORGE_GDT_'+uuid.uuid4().hex[:10]),engine=engine)
