"""Small typed bridge for v1.5 inspections and copy-only parameter edits."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
import uuid


def run_native(command, timeout_s=120, *, engine=None):
    from .core.trace import event
    event('native_started',mode=command.get('mode',command.get('operation','native')))
    from .modeling import _find_sw_dir
    directory=_find_sw_dir()
    if not directory:
        return {'ok':False,'error':'SolidWorks Interop DLL not found'}
    quote=lambda s:str(s).replace("'","''")
    with tempfile.TemporaryDirectory(prefix='swforge_native15_', ignore_cleanup_errors=True) as work:
        root=Path(work);name='Workflow15_'+uuid.uuid4().hex
        (root/'bridge.cs').write_text((engine or _ENGINE).replace('__CLASS__',name),encoding='utf8')
        (root/'request.json').write_text(json.dumps(command,ensure_ascii=False),encoding='utf8')
        dll=Path(directory)/'SolidWorks.Interop.sldworks.dll'
        const=Path(directory)/'SolidWorks.Interop.swconst.dll'
        (root/'run.ps1').write_text(
            "$ErrorActionPreference='Stop'\n"
            f"[System.Reflection.Assembly]::LoadFrom('{quote(dll)}') | Out-Null\n"
            f"Add-Type -TypeDefinition ([IO.File]::ReadAllText('{quote(root/'bridge.cs')}',[Text.Encoding]::UTF8)) "
            f"-ReferencedAssemblies '{quote(dll)}','{quote(const)}','System.Web.Extensions'\n"
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8\n"
            f"$result=[{name}]::Run('{quote(root/'request.json')}')\n"
            f"[IO.File]::WriteAllText('{quote(root/'response.json')}',$result,(New-Object Text.UTF8Encoding($false)))\n",encoding='utf-8-sig')
        try:
            proc=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'run.ps1')],
                capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout_s)
        except subprocess.TimeoutExpired:
            event('native_timeout',mutation_state='unknown')
            return {'ok':False,'error':'Native operation timed out; inspect state before retrying','mutation_state':'unknown'}
        if proc.returncode:
            return {'ok':False,'error':'Native bridge compile/execution failed','details':proc.stderr[-16000:]}
        try:
            response=root/'response.json'
            result=json.loads(response.read_text(encoding='utf-8') if response.exists() else proc.stdout)
            event('native_returned',ok=result.get('ok'))
            return result
        except ValueError:
            return {'ok':False,'error':'Invalid native bridge response','details':proc.stdout[-5000:]}


def target_document(path, kind):
    """Activate exact saved document, checking capacity before opening."""
    import os
    from .session import get_session,_value
    from .resources import ensure_capacity
    path=os.path.abspath(os.fspath(path))
    if not os.path.isfile(path):
        raise ValueError('Document does not exist: '+path)
    sw=get_session().sw()
    document=sw.GetOpenDocumentByName(path)
    if document is None:
        cap=ensure_capacity(2 if kind==3 else 1)
        if not cap['allowed']:
            raise RuntimeError(cap['error'])
        sw.OpenDoc(path,kind)
    sw.ActivateDoc(path)
    document=sw.ActiveDoc
    if document is None or int(_value(document,'GetType'))!=kind or os.path.normcase(str(_value(document,'GetPathName')))!=os.path.normcase(path):
        raise RuntimeError('Active document path/type mismatch')
    return sw,document,{'path':path,'process_id':int(_value(sw,'GetProcessID'))}


_ENGINE=r'''
using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
public class __CLASS__ {
 static ISldWorks sw;static IModelDoc2 md;
 static JavaScriptSerializer json=new JavaScriptSerializer(){MaxJsonLength=16777216};
 static string S(Dictionary<string,object>d,string k){return d.ContainsKey(k)&&d[k]!=null?Convert.ToString(d[k]):"";}
 static Dictionary<string,object> Row(params object[] pairs){var r=new Dictionary<string,object>();for(int i=0;i<pairs.Length;i+=2)r[(string)pairs[i]]=pairs[i+1];return r;}
 static List<object> parameters=new List<object>();static HashSet<string> names=new HashSet<string>();static int featureCount=0;
 static void Dimensions(IFeature f){
  if(++featureCount>20000)throw new Exception("Feature traversal exceeded limit");
  IDisplayDimension d=(IDisplayDimension)f.GetFirstDisplayDimension();int count=0;
  while(d!=null){
   if(++count>2000)throw new Exception("Dimension traversal exceeded limit");
   IDimension p=(IDimension)d.GetDimension2(0);
   if(p!=null&&names.Add(p.FullName)){
    int kind=p.GetType();double raw=p.SystemValue;
    string unit=kind==(int)swDimensionParamType_e.swDimensionParamTypeDoubleAngular?"deg":kind==(int)swDimensionParamType_e.swDimensionParamTypeDoubleLinear?"mm":"native";
    string key=p.FullName.Substring(0,p.FullName.LastIndexOf('@'));
    parameters.Add(Row("name",p.FullName,"key",key,"feature",f.Name,"kind",kind,"unit",unit,"value",unit=="deg"?raw*180/Math.PI:unit=="mm"?raw*1000:raw,"system_value",raw,"read_only",p.ReadOnly));
   }
   d=(IDisplayDimension)f.GetNextDisplayDimension(d);
  }
  for(IFeature child=(IFeature)f.GetFirstSubFeature();child!=null;child=(IFeature)child.GetNextSubFeature())Dimensions(child);
 }
 static object ListParameters(){
  if(md.GetType()!=1)throw new Exception("Only part documents are supported");
  parameters.Clear();names.Clear();featureCount=0;
  for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())Dimensions(f);
  return Row("ok",true,"path",md.GetPathName(),"configuration",md.ConfigurationManager.ActiveConfiguration.Name,"parameters",parameters);
 }
 static object Edit(Dictionary<string,object> cmd){
  if(md.GetType()!=1)throw new Exception("Only part variants are supported");
  string config=S(cmd,"configuration");
  if(config!=""&&!md.ShowConfiguration2(config))throw new Exception("Requested configuration does not exist");
  ListParameters();
  var changes=(Dictionary<string,object>)cmd["parameters"];
  var plan=new List<object>();
  foreach(var change in changes){
   var matches=parameters.FindAll(x=>S((Dictionary<string,object>)x,"name")==change.Key||S((Dictionary<string,object>)x,"key")==change.Key);
   if(matches.Count!=1)throw new Exception("Unknown or ambiguous exact parameter: "+change.Key);
   var known=matches[0];var p=(IDimension)md.Parameter(S((Dictionary<string,object>)known,"key"));
   if(p==null)throw new Exception("Cannot resolve parameter: "+change.Key);
   var row=(Dictionary<string,object>)known;
   if(p.ReadOnly||S(row,"unit")!="mm")throw new Exception("Only writable linear parameters are supported: "+change.Key);
   double value=Convert.ToDouble(change.Value);
   if(Double.IsNaN(value)||Double.IsInfinity(value)||value<=0)throw new Exception("Parameter must be finite and positive");
   plan.Add(Row("name",p.FullName,"key",S(row,"key"),"before_mm",p.SystemValue*1000,"after_mm",value));
  }
  foreach(Dictionary<string,object> change in plan){
   IDimension p=(IDimension)md.Parameter(S(change,"key"));
   int code=p.SetSystemValue3(Convert.ToDouble(change["after_mm"])/1000,(int)swSetValueInConfiguration_e.swSetValue_InThisConfiguration,null);
   if(code!=0)throw new Exception("SetSystemValue3 rejected parameter: "+p.FullName+" code="+code);
  }
  if(!md.EditRebuild3())throw new Exception("Rebuild returned false");
  foreach(Dictionary<string,object> change in plan){
   IDimension p=(IDimension)md.Parameter(S(change,"key"));
   double got=p.SystemValue*1000;
   if(Math.Abs(got-Convert.ToDouble(change["after_mm"]))>1e-6)throw new Exception("Parameter readback mismatch");
   change["readback_mm"]=got;
  }
  for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature()){
   bool warning=false;int error=f.GetErrorCode2(out warning);
   if(error!=0)throw new Exception("Feature rebuild error: "+f.Name+" code="+error);
  }
  IPartDoc pd=(IPartDoc)md;string material=S(cmd,"material");
  if(material!="")pd.SetMaterialPropertyName2("",S(cmd,"material_db"),material);
  string database="";string actual=pd.GetMaterialPropertyName2("",out database);
  if(material!=""&&actual!=material)throw new Exception("Material readback mismatch");
  md.ForceRebuild3(false);
  IMassProperty mass=(IMassProperty)md.Extension.CreateMassProperty();
  if(mass!=null)mass.UseSystemUnits=true;
  if(mass==null)throw new Exception("Mass properties unavailable");
  // SW2025 SP5: querying Volume before Mass can cache density=1. Read and cache Mass first.
  double massKg=mass.Mass;double volume=mass.Volume;
  if(volume<=0||massKg<=0)throw new Exception("Invalid mass/volume after rebuild");
  if(cmd.ContainsKey("density_kg_m3")&&cmd["density_kg_m3"]!=null&&Math.Abs(massKg/volume-Convert.ToDouble(cmd["density_kg_m3"]))>1)throw new Exception("Material density readback mismatch: "+massKg/volume);
  int errors=0,warnings=0;
  if(!md.Save3(1,ref errors,ref warnings)||errors!=0)throw new Exception("Variant save failed: "+errors);
  md.ShowNamedView2("",7);md.ViewZoomtofit2();
  return Row("ok",true,"path",md.GetPathName(),"configuration",md.ConfigurationManager.ActiveConfiguration.Name,"changes",plan,"material",actual,"volume_mm3",volume*1e9,"mass_kg",massKg,"density_kg_m3",massKg/volume,"save_warnings",warnings);
 }
 static object CopyPart(Dictionary<string,object> cmd){
  if(md.GetType()!=1||md.GetSaveFlag())throw new Exception("Copy source must be a saved part without unsaved changes");
  string output=Path.GetFullPath(S(cmd,"out"));string original=md.GetPathName();
  if(File.Exists(output))throw new Exception("Copy output already exists");
  IMassProperty mass=(IMassProperty)md.Extension.CreateMassProperty();mass.UseSystemUnits=true;
  double density=mass.Mass/mass.Volume;
  string database="";string material=((IPartDoc)md).GetMaterialPropertyName2("",out database);
  int errors=0,warnings=0;
  bool saved=md.Extension.SaveAs(output,0,3,null,ref errors,ref warnings);
  if(!saved||errors!=0||!File.Exists(output))throw new Exception("Native SaveAs copy failed: "+errors);
  if(!String.Equals(original,md.GetPathName(),StringComparison.OrdinalIgnoreCase)||md.GetSaveFlag())throw new Exception("Native copy unexpectedly changed source document state");
  return Row("ok",true,"created",true,"source",original,"output",output,"material",material,"density_kg_m3",density,"save_warnings",warnings);
 }
 static void AddAnnotations(IView view,List<object> rows){
  object[] source=(object[])view.GetAnnotations();if(source==null)return;
  foreach(object item in source){
   IAnnotation a=(IAnnotation)item;
   var row=Row("view",view.Name,"type",a.GetType(),"position_m",a.GetPosition(),"dangling",a.IsDangling());
   object specific=a.GetSpecificAnnotation();ITableAnnotation table=specific as ITableAnnotation;INote note=specific as INote;
   if(note!=null){row["text"]=note.GetText();row["property_linked_text"]=note.PropertyLinkedText;}
   IGtol gtol=specific as IGtol;
   if(gtol!=null){
    row["frame_values"]=gtol.GetFrameValues(1);row["frame_symbols"]=gtol.GetFrameSymbols2(1);
    double[] origin=(double[])a.GetPosition();double left=Double.MaxValue,bottom=Double.MaxValue,right=Double.MinValue,top=Double.MinValue;
    for(int i=0;i<gtol.GetLineCount();i++){double[] line=(double[])gtol.GetLineAtIndex(i);if(line==null||line.Length<6)continue;for(int j=line.Length-6;j<line.Length;j+=3){double x=line[j],y=line[j+1];if(Math.Abs(x)<.08&&Math.Abs(y)<.08){x+=origin[0];y+=origin[1];}left=Math.Min(left,x);bottom=Math.Min(bottom,y);right=Math.Max(right,x);top=Math.Max(top,y);}}
    if(right>left&&top>bottom){row["bounds_m"]=new double[]{left,bottom,right,top};row["bounds_source"]="native GTol frame line geometry";}
   }
   if(table!=null){
    double width=0,height=0;for(int i=0;i<table.ColumnCount;i++)width+=table.GetColumnWidth(i);for(int i=0;i<table.RowCount;i++)height+=table.GetRowHeight(i);
    double[] position=(double[])a.GetPosition();int anchor=table.AnchorType;
    double left=position[0]-(anchor==2||anchor==4?width:0),bottom=position[1]-(anchor==1||anchor==2?height:0);
    row["bounds_m"]=new double[]{left,bottom,left+width,bottom+height};row["bounds_source"]="native table row/column sizes";
   }else if(note!=null){
    double[] extent=(double[])note.GetExtent();if(extent!=null&&extent.Length==6){row["bounds_m"]=new double[]{Math.Min(extent[0],extent[3]),Math.Min(extent[1],extent[4]),Math.Max(extent[0],extent[3]),Math.Max(extent[1],extent[4])};row["bounds_source"]="native note extent";}
   }
   rows.Add(row);
  }
 }
 static object Drawing(){
  if(md.GetType()!=3)throw new Exception("Expected drawing");
  IDrawingDoc drawing=(IDrawingDoc)md;ISheet sheet=(ISheet)drawing.GetCurrentSheet();
  double width=0,height=0;sheet.GetSize(ref width,ref height);
  var views=new List<object>();var annotations=new List<object>();var unknown=new List<string>();
  IView sheetView=(IView)drawing.GetFirstView();
  AddAnnotations(sheetView,annotations);
  for(IView view=(IView)sheetView.GetNextView();view!=null;view=(IView)view.GetNextView()){
   var dims=new List<object>();
   for(IDisplayDimension dd=(IDisplayDimension)view.GetFirstDisplayDimension5();dd!=null;dd=(IDisplayDimension)dd.GetNext5()){
    IDimension dim=(IDimension)dd.GetDimension2(0);IAnnotation a=(IAnnotation)dd.GetAnnotation();
    double raw=dim.SystemValue;int type=dd.Type2;bool angle=type==3||type==16;
    string text=(angle?raw*180/Math.PI:raw*1000).ToString("0.###",System.Globalization.CultureInfo.InvariantCulture);
    double charHeight=.0035;
    try{ITextFormat format=(ITextFormat)a.GetTextFormat(0);if(format!=null&&format.CharHeight>0)charHeight=format.CharHeight;}catch{}
    var row=Row("name",dim.FullName,"view",view.Name,"position_m",a.GetPosition(),"dangling",a.IsDangling(),"text",text,"char_height_m",charHeight,"type",type,"value_mm",angle?0:raw*1000,"attached_entity_count",a.GetAttachedEntityCount3());
    try{row["tolerance_type"]=dim.Tolerance.Type;}catch{row["tolerance_type"]=null;}
    dims.Add(row);
   }
   AddAnnotations(view,annotations);
   IModelDoc2 reference=(IModelDoc2)view.ReferencedDocument;
   bool configExists=reference!=null&&reference.GetConfigurationByName(view.ReferencedConfiguration)!=null;
   views.Add(Row("name",view.Name,"outline_m",view.GetOutline(),"position_m",view.Position,"model_path",view.GetReferencedModelName(),"configuration",view.ReferencedConfiguration,"reference_loaded",reference!=null,"model_modified",reference!=null&&reference.GetSaveFlag(),"configuration_exists",configExists,"dimensions",dims));
  }
  var properties=new Dictionary<string,object>();ICustomPropertyManager manager=md.Extension.CustomPropertyManager[""];
  object[] props=(object[])manager.GetNames();
  if(props!=null)foreach(object p in props){string raw="",resolved="";bool wasResolved=false,linked=false;manager.Get6((string)p,false,out raw,out resolved,out wasResolved,out linked);properties[(string)p]=resolved==""?raw:resolved;}
  return Row("ok",true,"path",md.GetPathName(),"drawing_modified",md.GetSaveFlag(),"sheet",sheet.GetName(),"sheet_names",drawing.GetSheetNames(),"width_m",width,"height_m",height,"views",views,"annotations",annotations,"properties",properties);
 }
 public static string Run(string path){
  try{
   var cmd=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
   sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));
   if(sw.GetProcessID()!=Convert.ToInt32(cmd["process_id"]))throw new Exception("SolidWorks process changed");
   if(typeof(ISldWorks).Assembly.GetName().Version.Major!=Int32.Parse(sw.RevisionNumber().Split('.')[0]))throw new Exception("Interop major version differs from running SolidWorks");
   md=(IModelDoc2)sw.ActiveDoc;
   if(md==null||!String.Equals(Path.GetFullPath(md.GetPathName()),Path.GetFullPath(S(cmd,"path")),StringComparison.OrdinalIgnoreCase))throw new Exception("Active document changed");
   string mode=S(cmd,"mode");object result;
   if(mode=="parameters")result=ListParameters();else if(mode=="copy")result=CopyPart(cmd);else if(mode=="edit")result=Edit(cmd);else if(mode=="drawing")result=Drawing();else throw new Exception("Unknown operation");
   return json.Serialize(result);
  }catch(Exception e){return json.Serialize(Row("ok",false,"error",e.ToString()));}
 }
}
'''
